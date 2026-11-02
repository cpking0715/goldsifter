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
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
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
    if not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="管理令牌无效")


@app.post("/api/v1/admin/licenses")
async def issue_license(
    req: LicenseIssueRequest,
    x_admin_token: Optional[str] = Header(default=None),
):
    """发放 License key（仅管理令牌可调用）。"""
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
async def activate_license(req: LicenseActivateRequest):
    """激活 License 到指定设备；超设备数返回 403。"""
    with db() as conn:
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
async def verify_license(req: LicenseActivateRequest):
    """校验 License 与设备绑定状态；过期返回 ok=false（客户端进入离线宽限期）。"""
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
async def receive_snapshots(batch: SnapshotBatch):
    """匿名行情快照回传（仅行情字段，禁止携带任何个人身份信息）。"""
    received_at = _now()
    with db() as conn:
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
    return {"accepted": len(batch.items)}
