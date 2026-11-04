"""
License 门禁与首启状态测试。
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import tasks as tasks_router
from src.services import cloud_service, license_gate


@pytest.fixture()
def gate_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_service, "_DATA_DIR", tmp_path)
    return tmp_path


def _set_license(ok: bool, **extra) -> None:
    payload = {
        "ok": ok,
        "key": "QT-TEST-TEST-TEST",
        "plan": "pro",
        "expires_at": None,
        "last_verified_at": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(extra)
    cloud_service._write_json(cloud_service._license_file(), payload)


def test_no_license_is_free(gate_env):
    _set_license.__wrapped__ if hasattr(_set_license, "__wrapped__") else None
    cloud_service._license_file().unlink(missing_ok=True)
    assert license_gate.is_pro_licensed() is False
    assert license_gate.gate_platform("kongfz") is not None
    assert license_gate.gate_platform("xianyu") is None
    assert license_gate.gate_task_count(0) is None
    assert license_gate.gate_task_count(license_gate.FREE_MAX_TASKS) is not None


def test_valid_license_unlocks_all(gate_env):
    _set_license(True)
    assert license_gate.is_pro_licensed() is True
    assert license_gate.gate_platform("kongfz") is None
    assert license_gate.gate_task_count(999) is None


def test_expired_license_rejected(gate_env):
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _set_license(True, expires_at=expired)
    assert license_gate.is_pro_licensed() is False


def test_stale_cache_beyond_grace_rejected(gate_env):
    stale = (datetime.now(timezone.utc) - timedelta(days=license_gate.GRACE_DAYS + 1)).isoformat()
    _set_license(True, last_verified_at=stale)
    assert license_gate.is_pro_licensed() is False


def test_explicitly_revoked_license_rejected(gate_env):
    _set_license(False)
    assert license_gate.is_pro_licensed() is False


def test_create_task_enforces_platform_gate(tmp_path, monkeypatch, gate_env):
    """未授权时经 API 创建 Pro 平台任务被 403，闲鱼放行。"""
    monkeypatch.setattr(cloud_service, "_DATA_DIR", tmp_path)
    cloud_service._license_file().unlink(missing_ok=True)

    from src.api import dependencies as deps
    from src.domain.models.task import TaskCreate
    from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
    from src.services.task_service import TaskService

    class FakeScheduler:
        async def reload_jobs(self, tasks):
            return None

        def get_next_run_time(self, task_id):
            return None

    repo = SqliteTaskRepository(db_path=str(tmp_path / "t.sqlite3"), legacy_config_file=None)
    service = TaskService(repo)

    app = FastAPI()
    app.include_router(tasks_router.router)
    app.dependency_overrides[deps.get_task_service] = lambda: service
    app.dependency_overrides[deps.get_scheduler_service] = lambda: FakeScheduler()
    app.dependency_overrides[deps.get_process_service] = lambda: None
    app.dependency_overrides[deps.get_task_generation_service] = lambda: None
    client = TestClient(app)

    def payload(platform: str, name: str):
        return {
            "task_name": name,
            "keyword": "kw",
            "platform": platform,
            "decision_mode": "keyword",
            "keyword_rules": ["k"],
            "max_pages": 1,
            "personal_only": False,
            "free_shipping": False,
            "analyze_images": False,
        }

    # 关键词模式走 /generate
    resp = client.post("/api/tasks/generate", json=payload("kongfz", "t-kf"))
    assert resp.status_code == 403 and "Pro" in resp.json()["detail"]

    resp = client.post("/api/tasks/generate", json=payload("xianyu", "t-xy1"))
    assert resp.status_code == 200
    resp = client.post("/api/tasks/generate", json=payload("xianyu", "t-xy2"))
    assert resp.status_code == 200
    # 第 3 个闲鱼任务超免费额度
    resp = client.post("/api/tasks/generate", json=payload("xianyu", "t-xy3"))
    assert resp.status_code == 403 and "免费版" in resp.json()["detail"]

    # 授权后全部放行
    _set_license(True)
    resp = client.post("/api/tasks/generate", json=payload("kongfz", "t-kf2"))
    assert resp.status_code == 200
