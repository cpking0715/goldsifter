"""
云服务客户端模块测试：License 宽限、行情脱敏回传、更新检查。
网络全部 mock，不实际出网。
"""
import asyncio
from pathlib import Path

import httpx
import pytest

from src.services import cloud_service


@pytest.fixture()
def cloud_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_service, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("QT_CLOUD_BASE_URL", "https://cloud.test/qt")
    monkeypatch.delenv("QT_LICENSE_KEY", raising=False)
    monkeypatch.delenv("QT_TELEMETRY_ENABLED", raising=False)
    return tmp_path


def _seed_snapshots(db_path: Path, rows: list[tuple]) -> None:
    """直接往 price_snapshots 表插测试数据。"""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_slug TEXT NOT NULL, keyword TEXT NOT NULL, task_name TEXT,
            snapshot_time TEXT NOT NULL, snapshot_day TEXT, run_id TEXT,
            item_id TEXT, title TEXT, price REAL NOT NULL, price_display TEXT,
            tags_json TEXT, region TEXT, seller TEXT, publish_time TEXT, link TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO price_snapshots (keyword_slug, keyword, title, price, tags_json,"
        " snapshot_time, seller, region, link) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 设备标识与开关
# ---------------------------------------------------------------------------

def test_device_id_stable(cloud_env):
    first = cloud_service.get_device_id()
    assert first and first != "unknown-device"
    assert cloud_service.get_device_id() == first


def test_telemetry_toggle_roundtrip(cloud_env):
    assert cloud_service.is_telemetry_enabled() is True  # 默认开
    cloud_service.set_telemetry_enabled(False)
    assert cloud_service.is_telemetry_enabled() is False
    cloud_service.set_telemetry_enabled(True)
    assert cloud_service.is_telemetry_enabled() is True


# ---------------------------------------------------------------------------
# License：激活 / 校验 / 宽限
# ---------------------------------------------------------------------------

def _fake_client(responses: dict):
    """构造按 URL 前缀返回预设响应的假 httpx.AsyncClient。"""

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=None)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            for prefix, (code, payload) in responses.items():
                if url.startswith(prefix):
                    return FakeResponse(code, payload)
            return FakeResponse(500, {})

        async def get(self, url, **kwargs):
            for prefix, (code, payload) in responses.items():
                if url.startswith(prefix):
                    return FakeResponse(code, payload)
            return FakeResponse(500, {})

    return FakeClient()


def test_license_activate_success(cloud_env, monkeypatch):
    monkeypatch.setattr(
        cloud_service, "_http_client",
        lambda: _fake_client({"https://cloud.test/qt/api/v1/license/activate": (
            200, {"ok": True, "key": "QT-AAAA-BBBB-CCCC", "plan": "pro",
                  "expires_at": None, "expired": False},
        )}),
    )
    result = asyncio.run(cloud_service.activate_license("QT-AAAA-BBBB-CCCC"))
    assert result["ok"] is True
    cached = cloud_service.get_cached_license()
    assert cached["plan"] == "pro" and cached["last_verified_at"]


def test_license_verify_offline_grace(cloud_env, monkeypatch):
    # 先种一个 3 天前校验成功的缓存 -> 断网后应在宽限期内
    cloud_service._write_json(cloud_service._license_file(), {
        "ok": True, "key": "QT-AAAA-BBBB-CCCC", "plan": "pro",
        "last_verified_at": "2026-01-01T00:00:00+00:00",
    })
    monkeypatch.setenv("QT_LICENSE_KEY", "QT-AAAA-BBBB-CCCC")

    class DeadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(cloud_service, "_http_client", lambda: DeadClient())

    from datetime import datetime, timedelta, timezone
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    cloud_service._write_json(cloud_service._license_file(), {
        "ok": True, "key": "QT-AAAA-BBBB-CCCC", "last_verified_at": recent,
    })
    result = asyncio.run(cloud_service.verify_license())
    assert result["licensed"] is True and result["in_grace"] is True

    # 缓存校验时间超过宽限期 -> 失效
    old = (datetime.now(timezone.utc) - timedelta(days=cloud_service.GRACE_DAYS + 1)).isoformat()
    cloud_service._write_json(cloud_service._license_file(), {
        "ok": True, "key": "QT-AAAA-BBBB-CCCC", "last_verified_at": old,
    })
    result = asyncio.run(cloud_service.verify_license())
    assert result["licensed"] is False


# ---------------------------------------------------------------------------
# 行情回传：脱敏 + 水位推进
# ---------------------------------------------------------------------------

def test_telemetry_sanitizes_and_advances_watermark(cloud_env, tmp_path, monkeypatch):
    db = tmp_path / "local.sqlite3"
    _seed_snapshots(db, [
        ("kongfz_hongloumeng", "红楼梦", "红楼梦（全四册）", 40.0,
         '["品相:九品", "包邮"]', "2026-11-02T10:00:00", "某书店", "上海", "https://book.kongfz.com/1/2"),
        ("macbook", "macbook", "MacBook Pro M1", 7999.0,
         "[]", "2026-11-02T10:01:00", "张三", "北京", "https://www.goofish.com/item?id=1"),
    ])
    monkeypatch.setenv("APP_DATABASE_FILE", str(db))

    items = cloud_service.collect_pending_snapshots()
    assert len(items) == 2
    kongfz = next(i for i in items if i["platform"] == "kongfz")
    xianyu = next(i for i in items if i["platform"] == "xianyu")
    # 平台推断
    assert xianyu["platform"] == "xianyu"
    # 品相提取
    assert kongfz["quality"] == "九品"
    # 脱敏红线：不含 seller/region/link 字段
    for item in items:
        assert set(item.keys()) == {
            "platform", "keyword", "price", "title", "quality", "captured_at", "_local_id"
        }

    # 上传成功后推进水位，二次采集为空
    captured_batches = []

    async def fake_post(url, json=None):
        captured_batches.append(json)
        return None

    class OkClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            await fake_post(url, json=json)
            return _fake_client({}).post.__self__ if False else _Resp()

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(cloud_service, "_http_client", lambda: OkClient())
    uploaded = asyncio.run(cloud_service.run_telemetry_once())
    assert uploaded == 2
    # 上传载荷不含 _local_id
    assert all("_local_id" not in it for it in captured_batches[0]["items"])
    state = cloud_service._read_json(cloud_service._telemetry_state_file(), {})
    assert state["last_snapshot_id"] == 2 and state["uploaded_total"] == 2
    assert cloud_service.collect_pending_snapshots() == []


def test_telemetry_disabled_skips(cloud_env, monkeypatch):
    cloud_service.set_telemetry_enabled(False)
    called = []

    class ProbeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            called.append(1)
            raise AssertionError("不应发起上传")

    monkeypatch.setattr(cloud_service, "_http_client", lambda: ProbeClient())
    assert asyncio.run(cloud_service.run_telemetry_once()) == 0
    assert called == []


# ---------------------------------------------------------------------------
# 更新检查
# ---------------------------------------------------------------------------

def test_update_check_success_and_failure(cloud_env, monkeypatch):
    monkeypatch.setattr(cloud_service, "_http_client", lambda: _fake_client({
        "https://cloud.test/qt/api/v1/update/latest": (200, {"version": "1.1.0"}),
    }))
    result = asyncio.run(cloud_service.check_update())
    assert result["current_version"] == cloud_service.APP_VERSION
    assert result["latest"]["version"] == "1.1.0"

    class DeadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(cloud_service, "_http_client", lambda: DeadClient())
    result = asyncio.run(cloud_service.check_update())
    assert result["latest"] is None and result["current_version"] == cloud_service.APP_VERSION
