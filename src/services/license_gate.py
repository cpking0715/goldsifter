"""
License 功能门禁：free / Pro 分界与判定。

free：最多 2 个任务、仅闲鱼平台
Pro：全平台、无限任务（激活授权即解锁；云端不可达时 14 天离线宽限）

判定基于本地缓存（data/license_status.json，由 /api/cloud/license/verify 刷新），
纯同步、可失败降级——云服务不可用不影响本地运行，只按 free 限制。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from src.services import cloud_service

FREE_MAX_TASKS = 2
FREE_PLATFORMS = frozenset({"xianyu"})
GRACE_DAYS = 14


def _parse_iso(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def is_pro_licensed() -> bool:
    """缓存中的授权是否有效（含宽限判定；无缓存/过期/宽限超期均为 False）。"""
    cached = cloud_service.get_cached_license()
    if not cached or cached.get("ok") is not True:
        return False

    now = datetime.now(timezone.utc)
    expires = _parse_iso(cached.get("expires_at"))
    if expires:
        expires_aware = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        if expires_aware < now:
            return False

    # 离线宽限：最近一次成功校验需在 14 天内
    last_verified = _parse_iso(cached.get("last_verified_at"))
    if last_verified:
        lv = last_verified if last_verified.tzinfo else last_verified.replace(tzinfo=timezone.utc)
        if now - lv > timedelta(days=GRACE_DAYS):
            return False
    return True


def gate_platform(platform: str) -> Optional[str]:
    """平台门禁：返回 None=放行，否则为拒绝原因。"""
    if is_pro_licensed():
        return None
    if str(platform or "xianyu").strip().lower() not in FREE_PLATFORMS:
        return f"平台「{platform}」为 Pro 功能：免费版支持闲鱼平台，激活授权后解锁全平台。"
    return None


def gate_task_count(current_task_count: int) -> Optional[str]:
    """任务数门禁：返回 None=放行，否则为拒绝原因。"""
    if is_pro_licensed():
        return None
    if current_task_count >= FREE_MAX_TASKS:
        return f"免费版最多 {FREE_MAX_TASKS} 个监控任务，激活授权后不限量。"
    return None
