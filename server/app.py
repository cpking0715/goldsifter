"""
千淘轻服务端（License 校验 / 更新分发 / 行情回传收集）。

架构定位：重的都在客户端（爬虫/AI/存储），本服务只承担三件轻活：
1. License 发放与激活校验（客户端本地缓存 + 离线宽限，服务端不强制在线）
2. 客户端更新检查（读 data/update.json，可热改无需重启）
3. 匿名行情快照回传收集（为路线3 众包行情蓄数据）

设计约束：
- 单文件小应用，无 ORM，sqlite3 直接访问（与主仓库风格一致）
- 绝不接收/存储任何个人身份信息：回传仅限行情字段
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import string
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

DB_PATH = os.getenv("QT_DB_PATH", "server_data/app.sqlite3")
ADMIN_TOKEN = os.getenv("QT_ADMIN_TOKEN", "")
UPDATE_FILE = Path(os.getenv("QT_UPDATE_FILE", "")) if os.getenv("QT_UPDATE_FILE") else Path(__file__).parent / "data" / "update.json"
MAX_SNAPSHOT_BATCH = 200

app = FastAPI(title="千淘轻服务端", version="0.1.0")

SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    key TEXT PRIMARY KEY,
    plan TEXT NOT NULL,
    max_devices INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activations (
    key TEXT NOT NULL,
    device_id TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (key, device_id)
);
CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    keyword TEXT NOT NULL,
    price REAL NOT NULL,
    title TEXT,
    quality TEXT,
    captured_at TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_platform_keyword_time
ON market_snapshots(platform, keyword, captured_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def generate_license_key() -> str:
    alphabet = string.ascii_uppercase + string.digits
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "QT-" + "-".join(groups)


# ---------------------------------------------------------------------------
# 内存滑动窗口限流（单进程部署足够；防公网无限打 telemetry/license 端点）
# ---------------------------------------------------------------------------

_RATE_BUCKETS: dict[str, deque] = defaultdict(deque)
_RATE_BUCKET_GC_SIZE = 10000

# 众包数据配额：防止持续灌数据撑爆磁盘/污染行情（多 IP 也受全局上限约束）
TELEMETRY_DAILY_LIMIT = 200_000
TELEMETRY_TOTAL_LIMIT = 5_000_000
_telemetry_counter: dict[str, object] = {"day": "", "count": 0, "calibrated": False}


def _rate_limit(request: Request, bucket: str, limit: int, window_seconds: int = 60) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"{bucket}:{client_ip}"
    now = time.monotonic()
    queue = _RATE_BUCKETS[key]
    while queue and now - queue[0] > window_seconds:
        queue.popleft()
    if len(queue) >= limit:
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    queue.append(now)
    if len(_RATE_BUCKETS) > _RATE_BUCKET_GC_SIZE:
        _RATE_BUCKETS.clear()


def _enforce_telemetry_quota(conn: sqlite3.Connection) -> None:
    """每日 + 总量配额（内存计数，重启后按 DB 校准一次）。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _telemetry_counter["day"] != today:
        _telemetry_counter["day"] = today
        _telemetry_counter["count"] = 0
        _telemetry_counter["calibrated"] = False
    if not _telemetry_counter["calibrated"]:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM market_snapshots WHERE received_at >= ?",
            (today,),
        ).fetchone()
        _telemetry_counter["count"] = int(row["c"])
        _telemetry_counter["calibrated"] = True
    if int(_telemetry_counter["count"]) >= TELEMETRY_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail="今日行情回传配额已满")
    total = conn.execute("SELECT COUNT(*) AS c FROM market_snapshots").fetchone()["c"]
    if int(total) >= TELEMETRY_TOTAL_LIMIT:
        raise HTTPException(status_code=429, detail="行情数据总量已达上限，请联系管理员")


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "qiantao-light-server"}


# ---------------------------------------------------------------------------
# License
# ---------------------------------------------------------------------------

class LicenseIssueRequest(BaseModel):
    plan: str = Field(default="pro", description="套餐标识：free/pro/yearly 等")
    max_devices: int = Field(default=1, ge=1, le=10)
    valid_days: Optional[int] = Field(default=None, description="有效天数；None=永久")
    note: Optional[str] = None


class LicenseActivateRequest(BaseModel):
    key: str
    device_id: str = Field(min_length=8, max_length=128)


def _load_license(conn: sqlite3.Connection, key: str):
    return conn.execute(
        "SELECT * FROM licenses WHERE key = ?", (key.strip().upper(),)
    ).fetchone()


def _license_payload(row, device_id: str) -> dict:
    expires_at = row["expires_at"]
    expired = bool(expires_at and expires_at < _now())
    return {
        "ok": not expired,
        "key": row["key"],
        "plan": row["plan"],
        "expires_at": expires_at,
        "expired": expired,
        "device_id": device_id,
    }


def _require_admin(x_admin_token: Optional[str]) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="服务端未配置管理令牌（QT_ADMIN_TOKEN）")
    supplied = x_admin_token or ""
    # 长度先比，避免 compare_digest 长度不等时抛异常导致 500
    if len(supplied) != len(ADMIN_TOKEN) or not secrets.compare_digest(supplied, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="管理令牌无效")


@app.post("/api/v1/admin/licenses")
async def issue_license(
    req: LicenseIssueRequest,
    request: Request,
    x_admin_token: Optional[str] = Header(default=None),
):
    """发放 License key（仅管理令牌可调用）。"""
    _rate_limit(request, "admin", limit=10)
    _require_admin(x_admin_token)
    key = generate_license_key()
    expires_at = (
        (_now_ts() + timedelta(days=req.valid_days)).isoformat() if req.valid_days else None
    )
    with db() as conn:
        conn.execute(
            "INSERT INTO licenses (key, plan, max_devices, expires_at, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (key, req.plan, req.max_devices, expires_at, req.note, _now()),
        )
    return {"key": key, "plan": req.plan, "max_devices": req.max_devices, "expires_at": expires_at}


def _now_ts() -> datetime:
    return datetime.now(timezone.utc)


@app.post("/api/v1/license/activate")
async def activate_license(req: LicenseActivateRequest, request: Request):
    """激活 License 到指定设备；超设备数返回 403。"""
    _rate_limit(request, "license", limit=10)
    with db() as conn:
        # 写锁互斥：防止多 worker 部署时 COUNT+INSERT 竞态突破 max_devices
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = _load_license(conn, req.key)
        if not row:
            raise HTTPException(status_code=404, detail="License 不存在")
        if row["expires_at"] and row["expires_at"] < _now():
            raise HTTPException(status_code=403, detail="License 已过期")
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM activations WHERE key = ?", (row["key"],)
        ).fetchone()["c"]
        exists = conn.execute(
            "SELECT 1 FROM activations WHERE key = ? AND device_id = ?",
            (row["key"], req.device_id),
        ).fetchone()
        if not exists and count >= row["max_devices"]:
            raise HTTPException(
                status_code=403,
                detail=f"设备数已达上限（{row['max_devices']}）",
            )
        conn.execute(
            "INSERT INTO activations (key, device_id, activated_at, last_seen_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(key, device_id) DO UPDATE SET last_seen_at = excluded.last_seen_at",
            (row["key"], req.device_id, _now(), _now()),
        )
    with db() as conn:
        row = _load_license(conn, req.key)
        return _license_payload(row, req.device_id)


@app.post("/api/v1/license/verify")
async def verify_license(req: LicenseActivateRequest, request: Request):
    """校验 License 与设备绑定状态；过期返回 ok=false（客户端进入离线宽限期）。"""
    _rate_limit(request, "license", limit=10)
    with db() as conn:
        row = _load_license(conn, req.key)
        if not row:
            raise HTTPException(status_code=404, detail="License 不存在")
        activated = conn.execute(
            "SELECT 1 FROM activations WHERE key = ? AND device_id = ?",
            (row["key"], req.device_id),
        ).fetchone()
        if not activated:
            raise HTTPException(status_code=403, detail="该设备未激活此 License")
        conn.execute(
            "UPDATE activations SET last_seen_at = ? WHERE key = ? AND device_id = ?",
            (_now(), row["key"], req.device_id),
        )
    return _license_payload(row, req.device_id)


# ---------------------------------------------------------------------------
# 更新检查
# ---------------------------------------------------------------------------

@app.get("/api/v1/update/latest")
async def latest_update(channel: str = Query(default="stable")):
    """客户端更新检查：读 data/update.json，可热改。"""
    if not UPDATE_FILE.exists():
        return {"channel": channel, "version": "0.0.0", "url": None, "notes": "", "mandatory": False}
    import json

    try:
        payload = json.loads(UPDATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=500, detail="更新清单损坏")
    if channel and isinstance(payload.get("channels"), dict):
        payload = {**payload, **(payload["channels"].get(channel) or {})}
        payload.pop("channels", None)
    payload.setdefault("channel", channel)
    return payload


# ---------------------------------------------------------------------------
# 行情聚合（众包快照 → 全平台行情；Phase 3 第一块）
# ---------------------------------------------------------------------------

def _summarize_rows(rows) -> dict:
    prices = sorted(float(r["price"]) for r in rows if r["price"] is not None)
    if not prices:
        return {"sample_count": 0, "avg_price": None, "median_price": None,
                "min_price": None, "max_price": None}
    mid = len(prices) // 2
    median = prices[mid] if len(prices) % 2 else round((prices[mid - 1] + prices[mid]) / 2, 2)
    return {
        "sample_count": len(prices),
        "avg_price": round(sum(prices) / len(prices), 2),
        "median_price": round(median, 2),
        "min_price": min(prices),
        "max_price": max(prices),
    }


@app.get("/api/v1/market/keywords")
async def market_keywords(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    """行情覆盖的关键词列表（按样本量排序）。"""
    _rate_limit(request, "market", limit=30)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT platform, keyword, COUNT(*) AS samples,
                   MAX(captured_at) AS latest_at,
                   AVG(price) AS avg_price, MIN(price) AS min_price, MAX(price) AS max_price
            FROM market_snapshots
            GROUP BY platform, keyword
            ORDER BY samples DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "platform": r["platform"], "keyword": r["keyword"],
            "samples": r["samples"],
            "latest_at": r["latest_at"],
            "avg_price": round(r["avg_price"], 2) if r["avg_price"] is not None else None,
            "min_price": r["min_price"], "max_price": r["max_price"],
        }
        for r in rows
    ]


@app.get("/api/v1/market/summary")
async def market_summary(
    request: Request,
    platform: str = Query(default=""),
    keyword: str = Query(default=""),
):
    """单个关键词的行情详情：最新样本概览 + 近 30 天日趋势。"""
    _rate_limit(request, "market", limit=30)
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword 必填")
    conditions = ["keyword = ?"]
    params: list = [keyword]
    if platform:
        conditions.append("platform = ?")
        params.append(platform)

    with db() as conn:
        latest_rows = conn.execute(
            f"""
            SELECT price FROM market_snapshots
            WHERE {' AND '.join(conditions)}
              AND substr(captured_at, 1, 10) = (
                SELECT MAX(substr(captured_at, 1, 10)) FROM market_snapshots
                WHERE {' AND '.join(conditions)}
              )
            """,
            params + params,
        ).fetchall()
        latest_summary = _summarize_rows(latest_rows)

        trend_rows = conn.execute(
            f"""
            SELECT substr(captured_at, 1, 10) AS day, price FROM market_snapshots
            WHERE {' AND '.join(conditions)} AND captured_at >= datetime('now', '-30 day')
            ORDER BY captured_at ASC
            """,
            params,
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) AS c, MAX(captured_at) AS latest_at FROM market_snapshots WHERE {' AND '.join(conditions)}",
            params,
        ).fetchone()

    # 日趋势：按天聚合（样本数/均价/最低/最高）
    from collections import defaultdict

    by_day: dict[str, list[float]] = defaultdict(list)
    for r in trend_rows:
        try:
            by_day[r["day"]].append(float(r["price"]))
        except (TypeError, ValueError):
            continue
    daily = []
    for day in sorted(by_day.keys()):
        vals = by_day[day]
        daily.append({
            "day": day, "sample_count": len(vals),
            "avg_price": round(sum(vals) / len(vals), 2),
            "min_price": min(vals), "max_price": max(vals),
        })

    return {
        "platform": platform or None,
        "keyword": keyword,
        "latest": latest_summary,
        "daily_trend": daily,
        "total_samples": total["c"],
        "latest_snapshot_at": total["latest_at"],
    }


# ---------------------------------------------------------------------------
# 行情快照回传
# ---------------------------------------------------------------------------

class SnapshotItem(BaseModel):
    platform: str = Field(max_length=32)
    keyword: str = Field(max_length=128)
    price: float = Field(ge=0, le=10_000_000)
    title: Optional[str] = Field(default=None, max_length=256)
    quality: Optional[str] = Field(default=None, max_length=32)
    captured_at: str = Field(max_length=32)


class SnapshotBatch(BaseModel):
    items: list[SnapshotItem] = Field(max_length=MAX_SNAPSHOT_BATCH)


@app.post("/api/v1/telemetry/snapshots")
async def receive_snapshots(batch: SnapshotBatch, request: Request):
    """匿名行情快照回传（仅行情字段，禁止携带任何个人身份信息）。"""
    _rate_limit(request, "telemetry", limit=20)
    received_at = _now()
    with db() as conn:
        _enforce_telemetry_quota(conn)
        conn.executemany(
            "INSERT INTO market_snapshots"
            " (platform, keyword, price, title, quality, captured_at, received_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    it.platform, it.keyword, it.price,
                    (it.title or "")[:256], (it.quality or "")[:32],
                    it.captured_at, received_at,
                )
                for it in batch.items
            ],
        )
    _telemetry_counter["count"] = int(_telemetry_counter["count"]) + len(batch.items)
    return {"accepted": len(batch.items)}
