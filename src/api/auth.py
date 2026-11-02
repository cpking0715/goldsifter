"""
Web 鉴权模块。

登录成功签发 HMAC-SHA256 签名 token（无状态，不落库），
依赖项 require_auth 保护全部 /api/*，WebSocket 在握手前校验 query 参数 token。

密钥来源（优先级）：
1. 环境变量 WEB_AUTH_SECRET；
2. 缺省从 WEB_USERNAME/WEB_PASSWORD 派生 —— 修改账密即吊销全部旧 token。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import HTTPException, Request, WebSocket

TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 天


def _get_secret() -> str:
    """获取签名密钥（WEB_AUTH_SECRET 优先，缺省从账密派生）。"""
    from src.infrastructure.config.settings import get_settings

    configured = str(getattr(get_settings(), "web_auth_secret", None) or "").strip()
    configured = configured or os.getenv("WEB_AUTH_SECRET", "").strip()
    if configured:
        return configured
    app_settings = get_settings()
    material = f"{app_settings.web_username}:{app_settings.web_password}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _sign(payload_bytes: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_access_token(username: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """为指定用户签发 token：base64(payload).base64(signature)。"""
    payload = {"sub": username, "exp": int(time.time()) + ttl_seconds}
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = _sign(payload_bytes, _get_secret())
    return f"{_b64encode(payload_bytes)}.{_b64encode(signature)}"


def verify_token(token: str) -> bool:
    """校验 token 签名、有效期与用户名是否匹配当前配置。"""
    from src.infrastructure.config.settings import get_settings

    if not token or "." not in token:
        return False
    payload_text, signature_text = token.rsplit(".", 1)
    try:
        payload_bytes = _b64decode(payload_text)
        signature = _b64decode(signature_text)
    except (ValueError, TypeError):
        return False

    expected = _sign(payload_bytes, _get_secret())
    # compare_digest 对长度不等的 bytes 抛异常，先比长度保证畸形 token 稳定返回 False
    if len(signature) != len(expected) or not hmac.compare_digest(signature, expected):
        return False
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if int(payload.get("exp") or 0) < int(time.time()):
        return False
    app_settings = get_settings()
    if str(payload.get("sub") or "") != str(app_settings.web_username or ""):
        return False
    return True


def _extract_token(request: Request) -> Optional[str]:
    """从 Authorization: Bearer <token> 或 X-Auth-Token 头提取 token。"""
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    x_auth = request.headers.get("x-auth-token") or ""
    return x_auth.strip() or None


def require_auth(request: Request) -> None:
    """API 鉴权依赖项：校验失败抛 401。"""
    token = _extract_token(request)
    if not token or not verify_token(token):
        raise HTTPException(status_code=401, detail="未授权或登录已过期")


def verify_websocket_token(websocket: WebSocket) -> bool:
    """WebSocket 握手前校验 query 参数中的 token。"""
    token = websocket.query_params.get("token") or ""
    return verify_token(token)
