import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.auth import create_access_token, require_auth, verify_token
from src.api.routes import websocket
from src.app import app as main_app
from src.infrastructure.config.settings import get_settings


@pytest.fixture()
def auth_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "web_username", "admin", raising=False)
    monkeypatch.setattr(settings, "web_password", "admin123", raising=False)
    monkeypatch.setattr(settings, "web_auth_secret", "unit-test-secret", raising=False)
    return settings


def _protected_app() -> FastAPI:
    api = FastAPI()

    @api.get("/health")
    async def health():
        return {"status": "healthy"}

    @api.get("/api/ping", dependencies=[Depends(require_auth)])
    async def ping():
        return {"ok": True}

    return api


def test_token_roundtrip_and_rejection(auth_settings):
    token = create_access_token(auth_settings.web_username, ttl_seconds=60)
    assert verify_token(token) is True
    assert verify_token(token[:-4] + "xxxx") is False
    assert verify_token("") is False
    assert verify_token("not-a-token") is False

    expired = create_access_token(auth_settings.web_username, ttl_seconds=-10)
    assert verify_token(expired) is False


def test_token_rejected_after_username_changes(auth_settings, monkeypatch):
    token = create_access_token("admin")
    monkeypatch.setattr(auth_settings, "web_username", "other", raising=False)
    assert verify_token(token) is False


def test_api_requires_bearer_token(auth_settings):
    client = TestClient(_protected_app())
    assert client.get("/health").status_code == 200
    assert client.get("/api/ping").status_code == 401

    token = create_access_token("admin")
    ok = client.get("/api/ping", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    via_header = client.get("/api/ping", headers={"X-Auth-Token": token})
    assert via_header.status_code == 200


def _iter_included_routers(application):
    for route in application.routes:
        if type(route).__name__ != "_IncludedRouter":
            continue
        yield route


def test_main_app_mounts_websocket_and_protects_api():
    direct_paths = {getattr(route, "path", "") for route in main_app.routes}
    assert "/health" in direct_paths
    assert "/auth/status" in direct_paths

    included = list(_iter_included_routers(main_app))
    assert included

    protected = []
    websocket_paths = []
    for route in included:
        dependencies = [dep.dependency for dep in route.include_context.dependencies]
        for endpoint in route.original_router.routes:
            path = getattr(endpoint, "path", "")
            if path == "/ws":
                websocket_paths.append(path)
                assert require_auth not in dependencies
            elif path.startswith("/api/"):
                protected.append(path)
                assert require_auth in dependencies

    assert "/ws" in websocket_paths
    assert "/api/tasks" in protected
    assert "/api/platforms" in protected


def test_websocket_rejects_missing_or_bad_token(auth_settings):
    mini = FastAPI()
    mini.include_router(websocket.router)
    client = TestClient(mini)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as socket:
            socket.receive_text()

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=bad") as socket:
            socket.receive_text()

    token = create_access_token("admin", ttl_seconds=60)
    with client.websocket_connect(f"/ws?token={token}") as socket:
        assert socket is not None
        time.sleep(0.01)
