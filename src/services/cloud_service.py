"""
千淘客户端云服务模块（对接轻服务端）。

职责（全部可失败降级，云服务不可达不影响本地功能）：
1. License 激活与校验：本地缓存 + 离线宽限期（服务端不可达/过期后仍可宽限 N 天）
2. 匿名行情回传：从本地 price_snapshots 取新增记录，脱敏后批量上报（默认开启，可关）
3. 更新检查：查询轻服务端最新版本清单

隐私红线：只上传行情字段（平台/关键词/价格/标题截断/品相/采集时间），
绝不上传卖家昵称、地区、商品链接、cookie、账号等任何可关联个人的信息。
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

APP_VERSION = "1.0.0"
DEFAULT_CLOUD_BASE_URL = "https://qiantao.qingmuxi.com:8790/qt"
GRACE_DAYS = 14  # 服务端不可达/过期后的离线宽限天数
TELEMETRY_BATCH = 200

_DATA_DIR = Path("data")


def _device_file() -> Path:
    return _DATA_DIR / "device_id"


def _license_file() -> Path:
    return _DATA_DIR / "license_status.json"


def _cloud_settings_file() -> Path:
    return _DATA_DIR / "cloud_settings.json"


def _telemetry_state_file() -> Path:
    return _DATA_DIR / "telemetry_state.json"



def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def get_cloud_base_url() -> str:
    return _env("QT_CLOUD_BASE_URL", DEFAULT_CLOUD_BASE_URL)


def get_device_id() -> str:
    """稳定的设备标识（首次生成后持久化）。"""
    try:
        if _device_file().exists():
            existing = _device_file().read_text(encoding="utf-8").strip()
            if existing:
                return existing
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        device_id = uuid.uuid4().hex
        _device_file().write_text(device_id, encoding="utf-8")
        return device_id
    except OSError:
        return "unknown-device"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[云服务] 写入 {path.name} 失败: {exc}")


def _http_client() -> httpx.AsyncClient:
    # 轻服务端为 tls internal 自签证书，客户端跳过校验
    return httpx.AsyncClient(verify=False, timeout=8.0, follow_redirects=True)


# ---------------------------------------------------------------------------
# 设置（运行时开关，默认值来自环境变量）
# ---------------------------------------------------------------------------

def is_telemetry_enabled() -> bool:
    settings = _read_json(_cloud_settings_file(), {})
    if "telemetry_enabled" in settings:
        return bool(settings["telemetry_enabled"])
    return _env("QT_TELEMETRY_ENABLED", "true").lower() != "false"


def set_telemetry_enabled(enabled: bool) -> bool:
    settings = _read_json(_cloud_settings_file(), {})
    settings["telemetry_enabled"] = bool(enabled)
    _write_json(_cloud_settings_file(), settings)
    return is_telemetry_enabled()


def get_telemetry_interval_minutes() -> int:
    try:
        return max(30, int(_env("QT_TELEMETRY_INTERVAL_MINUTES", "360")))
    except ValueError:
        return 360


# ---------------------------------------------------------------------------
# License
# ---------------------------------------------------------------------------

def get_cached_license() -> dict:
    return _read_json(_license_file(), {})


def _save_license(payload: dict) -> None:
    _write_json(_license_file(), payload)


def _env_license_key() -> str:
    return _env("QT_LICENSE_KEY") or get_cached_license().get("key", "")


async def activate_license(key: str) -> dict:
    """激活 License 并缓存结果。"""
    body = {"key": key.strip(), "device_id": get_device_id()}
    async with _http_client() as client:
        resp = await client.post(
            f"{get_cloud_base_url()}/api/v1/license/activate", json=body
        )
        if resp.status_code == 404:
            return {"ok": False, "reason": "License 不存在"}
        if resp.status_code == 403:
            return {"ok": False, "reason": resp.json().get("detail", "设备数达上限或已过期")}
        resp.raise_for_status()
        payload = resp.json()
    payload["last_verified_at"] = _now().isoformat()
    _save_license(payload)
    return payload


async def verify_license() -> dict:
    """校验 License；网络失败时依据缓存与宽限期给出结论。"""
    key = _env_license_key()
    if not key:
        return {"licensed": False, "reason": "未配置 License"}
    try:
        async with _http_client() as client:
            resp = await client.post(
                f"{get_cloud_base_url()}/api/v1/license/verify",
                json={"key": key, "device_id": get_device_id()},
            )
            if resp.status_code == 404:
                result = {"licensed": False, "reason": "License 不存在", "in_grace": False}
                _save_license({**get_cached_license(), "ok": False, "last_verified_at": _now().isoformat()})
                return result
            if resp.status_code == 403:
                result = {"licensed": False, "reason": resp.json().get("detail", "未激活"), "in_grace": False}
                return result
            resp.raise_for_status()
            payload = resp.json()
            payload["last_verified_at"] = _now().isoformat()
            _save_license(payload)
            return {"licensed": bool(payload.get("ok")), "reason": None, "detail": payload}
    except (httpx.HTTPError, ValueError) as exc:
        # 云端不可达：进入宽限期判定
        cached = get_cached_license()
        last_ok = str(cached.get("last_verified_at") or "")
        was_valid = cached.get("ok") is True
        if was_valid and last_ok:
            try:
                elapsed = _now() - datetime.fromisoformat(last_ok)
            except ValueError:
                elapsed = timedelta(days=999)
            in_grace = elapsed <= timedelta(days=GRACE_DAYS)
            return {
                "licensed": in_grace,
                "reason": None if in_grace else "离线宽限期已过",
                "in_grace": in_grace,
                "offline": True,
                "error": str(exc),
            }
        return {"licensed": False, "reason": "云端不可达且无有效缓存", "offline": True}


# ---------------------------------------------------------------------------
# 更新检查
# ---------------------------------------------------------------------------

async def check_update() -> dict:
    """查询轻服务端最新版本；失败返回当前版本。"""
    try:
        async with _http_client() as client:
            resp = await client.get(f"{get_cloud_base_url()}/api/v1/update/latest")
            resp.raise_for_status()
            latest = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"current_version": APP_VERSION, "latest": None, "error": str(exc)}
    return {"current_version": APP_VERSION, "latest": latest}


# ---------------------------------------------------------------------------
# 匿名行情回传
# ---------------------------------------------------------------------------

def _infer_platform(keyword_slug: str) -> str:
    slug = str(keyword_slug or "")
    if slug.startswith("kongfz_"):
        return "kongfz"
    return "xianyu"


def _extract_quality(tags_json: str) -> str:
    try:
        tags = json.loads(tags_json or "[]")
    except json.JSONDecodeError:
        return ""
    for tag in tags:
        text = str(tag or "")
        if text.startswith("品相:"):
            return text[len("品相:"):]
    return ""


def collect_pending_snapshots(limit: int = TELEMETRY_BATCH) -> list[dict]:
    """读取本地新增价格快照（脱敏：只保留行情字段）。"""
    from src.infrastructure.persistence.sqlite_connection import sqlite_connection

    state = _read_json(_telemetry_state_file(), {})
    watermark = int(state.get("last_snapshot_id") or 0)
    items: list[dict] = []
    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT id, keyword_slug, keyword, price, title, tags_json, snapshot_time"
            " FROM price_snapshots WHERE id > ? ORDER BY id ASC LIMIT ?",
            (watermark, limit),
        ).fetchall()
        last_id = watermark
        for row in rows:
            last_id = max(last_id, row["id"])
            items.append(
                {
                    "platform": _infer_platform(row["keyword_slug"]),
                    "keyword": str(row["keyword"] or "")[:128],
                    "price": float(row["price"]),
                    "title": str(row["title"] or "")[:80],
                    "quality": _extract_quality(row["tags_json"]),
                    "captured_at": str(row["snapshot_time"] or "")[:32],
                    "_local_id": row["id"],
                }
            )
    return items


async def run_telemetry_once() -> int:
    """上传一批待传快照，返回成功条数（0=无新增或失败）。"""
    if not is_telemetry_enabled():
        return 0
    items = collect_pending_snapshots()
    if not items:
        return 0
    payload = [{k: v for k, v in item.items() if k != "_local_id"} for item in items]
    try:
        async with _http_client() as client:
            resp = await client.post(
                f"{get_cloud_base_url()}/api/v1/telemetry/snapshots",
                json={"items": payload},
            )
            resp.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[云回馈] 行情回传失败（下次重试）: {exc}")
        return 0
    # 成功后推进水位线
    state = _read_json(_telemetry_state_file(), {})
    state["last_snapshot_id"] = max(item["_local_id"] for item in items)
    state["last_uploaded_at"] = _now().isoformat()
    state["uploaded_total"] = int(state.get("uploaded_total") or 0) + len(items)
    _write_json(_telemetry_state_file(), state)
    return len(items)


async def telemetry_loop() -> None:
    """后台循环：按间隔回传行情快照。"""
    interval = get_telemetry_interval_minutes() * 60
    while True:
        try:
            uploaded = await run_telemetry_once()
            if uploaded:
                print(f"[云回馈] 已匿名回传 {uploaded} 条行情快照")
        except Exception as exc:  # noqa: BLE001 - 后台循环不允许退出
            print(f"[云回馈] 异常: {exc}")
        await asyncio.sleep(interval)
