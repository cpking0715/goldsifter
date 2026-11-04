"""price_snapshots.platform 列迁移与跨平台隔离测试。"""
import sqlite3

import pytest

from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection
from src.services.price_history_service import (
    load_price_snapshots,
    normalize_keyword_slug,
    record_market_snapshots,
)


def _mk_item(item_id: str, price: float) -> dict:
    return {
        "商品ID": item_id,
        "商品标题": f"item-{item_id}",
        "当前售价": f"¥{price}",
        "商品链接": f"https://example.com/{item_id}",
        "商品标签": [],
        "发货地区": "",
        "卖家昵称": "",
        "发布时间": "",
    }


def test_slug_normalized_without_platform_prefix():
    assert normalize_keyword_slug("红楼梦", "kongfz") == normalize_keyword_slug("红楼梦")
    assert normalize_keyword_slug("AK-47") == "ak-47"


def test_migration_backfills_platform_and_strips_prefix(tmp_path, monkeypatch):
    """存量 kongfz_xxx slug 迁移为 platform=kongfz + 归一化 slug。"""
    db = tmp_path / "legacy.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(db))
    conn = sqlite3.connect(db)
    # 造一个"旧 schema"表（无 platform 列，带前缀 slug）
    conn.executescript("""
        CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE price_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_slug TEXT NOT NULL, keyword TEXT NOT NULL, task_name TEXT,
            snapshot_time TEXT NOT NULL, snapshot_day TEXT, run_id TEXT,
            item_id TEXT, title TEXT, price REAL NOT NULL, price_display TEXT,
            tags_json TEXT, region TEXT, seller TEXT, publish_time TEXT, link TEXT,
            UNIQUE(keyword_slug, run_id, item_id)
        );
        CREATE INDEX idx_snapshots_keyword_time ON price_snapshots(keyword_slug, snapshot_time DESC);
        CREATE INDEX idx_snapshots_keyword_item_time ON price_snapshots(keyword_slug, item_id, snapshot_time DESC);
    """)
    conn.execute(
        "INSERT INTO price_snapshots (keyword_slug, keyword, snapshot_time, snapshot_day, run_id, item_id, title, price) "
        "VALUES ('kongfz_hongloumeng', '红楼梦', '2026-01-01', '2026-01-01', 'r1', 'i1', '红楼梦', 40.0)"
    )
    conn.execute(
        "INSERT INTO price_snapshots (keyword_slug, keyword, snapshot_time, snapshot_day, run_id, item_id, title, price) "
        "VALUES ('hongloumeng', '红楼梦', '2026-01-01', '2026-01-01', 'r1', 'i2', '红楼梦（闲鱼同名）', 55.0)"
    )
    conn.commit()
    conn.close()

    # 触发迁移（init_schema 内含迁移逻辑）
    with sqlite_connection(str(db)) as conn2:
        init_schema(conn2)

    with sqlite_connection(str(db)) as conn3:
        rows = conn3.execute(
            "SELECT keyword_slug, platform FROM price_snapshots ORDER BY id"
        ).fetchall()
    by_item = {r["keyword_slug"]: r["platform"] for r in rows}
    assert by_item.get("hongloumeng", "").count("kongfz") == 0
    # 两条都归一化为 hongloumeng，platform 分别为 kongfz / xianyu
    platforms = sorted(r["platform"] for r in rows)
    assert platforms == ["kongfz", "xianyu"]
    assert all(r["keyword_slug"] == "hongloumeng" for r in rows)


def test_record_and_load_isolated_by_platform(tmp_path, monkeypatch):
    """同关键词双平台快照互不串读（根治审计 open#3-5）。"""
    db = tmp_path / "iso.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(db))
    with sqlite_connection(str(db)) as conn:
        init_schema(conn)

    record_market_snapshots(
        keyword="macbook", task_name="t-kf", items=[_mk_item("a", 100.0)],
        run_id="r1", platform="kongfz",
    )
    record_market_snapshots(
        keyword="macbook", task_name="t-xy", items=[_mk_item("b", 200.0)],
        run_id="r1", platform="xianyu",
    )

    kf = load_price_snapshots("macbook", "kongfz")
    xy = load_price_snapshots("macbook", "xianyu")
    assert len(kf) == 1 and len(xy) == 1
    assert kf[0]["item_id"] == "a" and xy[0]["item_id"] == "b"
