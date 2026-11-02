"""
千淘轻服务端测试：License 发放/激活/校验、行情回传、更新检查。
"""
import json

import pytest
from fastapi.testclient import TestClient

from server import app as server_app


@pytest.fixture()
def light_server(tmp_path, monkeypatch):
    monkeypatch.setattr(server_app, "DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setattr(server_app, "ADMIN_TOKEN", "test-admin-token")
    client = TestClient(server_app.app)
    yield client


def _issue(client, **payload):
    resp = client.post(
        "/api/v1/admin/licenses",
        json=payload,
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


DEVICE = "device-abcdefghijklmnop"


def test_health(light_server):
    resp = light_server.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "qiantao-light-server"


def test_admin_requires_token(light_server):
    resp = light_server.post("/api/v1/admin/licenses", json={})
    assert resp.status_code in (401, 503)


def test_license_issue_activate_verify_flow(light_server):
    issued = _issue(light_server, plan="pro", max_devices=2, valid_days=30)
    key = issued["key"]
    assert key.startswith("QT-") and len(key) == 17  # QT-XXXX-XXXX-XXXX

    # 激活
    resp = light_server.post("/api/v1/license/activate", json={"key": key, "device_id": DEVICE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["plan"] == "pro" and body["expired"] is False

    # 校验
    resp = light_server.post("/api/v1/license/verify", json={"key": key, "device_id": DEVICE})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 第二台设备（max_devices=2）可激活，第三台被拒
    resp = light_server.post("/api/v1/license/activate", json={"key": key, "device_id": "device-b-12345678"})
    assert resp.status_code == 200
    resp = light_server.post("/api/v1/license/activate", json={"key": key, "device_id": "device-c-12345678"})
    assert resp.status_code == 403
    assert "上限" in resp.json()["detail"]

    # 重复激活同一设备幂等（不算新设备）
    resp = light_server.post("/api/v1/license/activate", json={"key": key, "device_id": DEVICE})
    assert resp.status_code == 200


def test_license_invalid_and_unactivated(light_server):
    resp = light_server.post("/api/v1/license/activate", json={"key": "QT-XXXX-YYYY", "device_id": DEVICE})
    assert resp.status_code == 404

    issued = _issue(light_server)
    resp = light_server.post("/api/v1/license/verify", json={"key": issued["key"], "device_id": DEVICE})
    assert resp.status_code == 403


def test_telemetry_snapshots_roundtrip(light_server):
    items = [
        {"platform": "kongfz", "keyword": "红楼梦", "price": 40.0, "title": "红楼梦（全四册）", "quality": "九品", "captured_at": "2026-11-02T10:00:00"},
        {"platform": "xianyu", "keyword": "macbook", "price": 7999.0, "title": "MacBook Pro M1", "captured_at": "2026-11-02T10:01:00"},
    ]
    resp = light_server.post("/api/v1/telemetry/snapshots", json={"items": items})
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 2

    # 落库校验
    with server_app.db() as conn:
        rows = conn.execute(
            "SELECT platform, keyword, price FROM market_snapshots ORDER BY id"
        ).fetchall()
    assert [(r["platform"], r["keyword"]) for r in rows] == [("kongfz", "红楼梦"), ("xianyu", "macbook")]


def test_telemetry_rejects_oversized_batch(light_server):
    items = [
        {"platform": "kongfz", "keyword": "k", "price": 1.0, "captured_at": "2026-11-02T10:00:00"}
    ] * (server_app.MAX_SNAPSHOT_BATCH + 1)
    resp = light_server.post("/api/v1/telemetry/snapshots", json={"items": items})
    assert resp.status_code == 422


def test_update_latest_default_and_file(light_server, tmp_path, monkeypatch):
    # 无清单文件：返回默认
    resp = light_server.get("/api/v1/update/latest")
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.0.0"

    # 有清单文件：读取并可按 channel 覆写
    update_file = tmp_path / "update.json"
    update_file.write_text(json.dumps({
        "version": "1.2.0", "url": "https://example.com/dl", "notes": "n",
        "channels": {"beta": {"version": "1.3.0-beta1"}},
    }), encoding="utf-8")
    monkeypatch.setattr(server_app, "UPDATE_FILE", update_file)
    assert light_server.get("/api/v1/update/latest").json()["version"] == "1.2.0"
    assert light_server.get("/api/v1/update/latest?channel=beta").json()["version"] == "1.3.0-beta1"


def test_license_rate_limit(light_server):
    """同一 IP 高频激活被 429 限流。"""
    server_app._RATE_BUCKETS.clear()  # 测试隔离：清空限流桶
    issued = _issue(light_server, max_devices=10)
    codes = []
    for i in range(12):
        resp = light_server.post(
            "/api/v1/license/activate",
            json={"key": issued["key"], "device_id": f"device-{i:04d}-abcdefghijklmnop"[:24]},
        )
        codes.append(resp.status_code)
    assert codes.count(200) == 10
    assert codes.count(429) >= 1


def test_telemetry_rate_limit(light_server):
    server_app._RATE_BUCKETS.clear()  # 测试隔离：清空限流桶
    body = {"items": [{"platform": "kongfz", "keyword": "k", "price": 1.0, "captured_at": "2026-11-02T10:00:00"}]}
    codes = [light_server.post("/api/v1/telemetry/snapshots", json=body).status_code for _ in range(25)]
    assert codes.count(200) == 20
    assert codes.count(429) >= 1
