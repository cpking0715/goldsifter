"""
首次启动状态与账号安全路由。

- /api/setup/status：首启向导三项检测（默认账密未改 / AI 未配 / 通知未配）
- /api/auth/password：修改管理员用户名与密码（改后旧 token 自动失效——
  签名密钥默认从账密派生）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.auth import create_access_token
from src.infrastructure.config import env_manager
from src.infrastructure.config.settings import get_settings
from src.services.notification_config_service import load_notification_settings

router = APIRouter(tags=["setup"])


class PasswordChangeRequest(BaseModel):
    old_username: str
    old_password: str
    new_username: str = Field(min_length=3, max_length=32)
    new_password: str = Field(min_length=6, max_length=64)


def _is_default_credential() -> bool:
    settings = get_settings()
    import secrets as _secrets

    return (
        _secrets.compare_digest(str(settings.web_username or ""), "admin")
        and _secrets.compare_digest(str(settings.web_password or ""), "admin123")
    )


@router.get("/api/setup/status")
async def setup_status():
    """首启向导检测：默认凭据是否未改、AI/通知是否已配置。"""
    from src.infrastructure.config.settings import AISettings

    ai = AISettings()
    notification = load_notification_settings()
    return {
        "password_changed": not _is_default_credential(),
        "ai_configured": bool(ai.api_key and ai.base_url and ai.model_name),
        "notification_configured": notification.has_any_notification_enabled(),
    }


@router.put("/api/auth/password")
async def change_password(payload: PasswordChangeRequest):
    """修改管理员用户名/密码（校验旧凭据；成功返回新 token）。"""
    import secrets as _secrets

    settings = get_settings()
    user_ok = _secrets.compare_digest(
        payload.old_username.encode("utf-8"), str(settings.web_username or "").encode("utf-8")
    )
    pass_ok = _secrets.compare_digest(
        payload.old_password.encode("utf-8"), str(settings.web_password or "").encode("utf-8")
    )
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="原账号或密码不正确")

    updates = {
        "WEB_USERNAME": payload.new_username,
        "WEB_PASSWORD": payload.new_password,
    }
    if not env_manager.update_values(updates):
        raise HTTPException(status_code=500, detail="写入配置失败")
    # 热重载：签名密钥由账密派生，改完旧 token 全部失效
    from src.infrastructure.config.settings import reload_settings

    reload_settings()
    return {
        "message": "账号密码已更新，请使用新凭据重新登录",
        "token": create_access_token(payload.new_username),
        "username": payload.new_username,
    }
