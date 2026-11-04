import asyncio
import sqlite3

import pytest
from pydantic import ValidationError

from src.domain.models.task import Task, TaskCreate, TaskUpdate
from src.infrastructure.persistence.sqlite_connection import _migrate_tasks_platform
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
from src.infrastructure.persistence.storage_names import (
    build_result_filename,
    normalize_keyword_slug,
    parse_result_filename,
)


def _task(**overrides) -> Task:
    payload = {
        "task_name": "红楼梦",
        "enabled": True,
        "keyword": "红楼梦",
        "description": "收一本品相好的红楼梦",
        "max_pages": 1,
        "personal_only": False,
        "ai_prompt_base_file": "prompts/base_prompt.txt",
        "ai_prompt_criteria_file": "prompts/criteria.txt",
    }
    payload.update(overrides)
    return Task(**payload)


def test_create_accepts_kongfz_and_defaults_xianyu():
    created = TaskCreate(
        task_name="红楼梦",
        keyword="红楼梦",
        description="收一本品相好的红楼梦",
        platform="KONGFZ",
    )
    assert created.platform == "kongfz"

    defaulted = TaskCreate(
        task_name="相机",
        keyword="a7m4",
        description="机身成色好",
    )
    assert defaulted.platform == "xianyu"


def test_unknown_platform_is_rejected():
    # 未注册平台直接拒绝（错误消息动态列出可选平台）
    with pytest.raises(ValidationError):
        TaskCreate(
            task_name="相机",
            keyword="a7m4",
            description="机身成色好",
            platform="amazon",
        )


def test_patch_without_platform_does_not_reset_it():
    updated = TaskUpdate(description="只改描述")
    assert "platform" not in updated.model_dump(exclude_unset=True)


def test_result_names_keep_xianyu_compatible_and_namespace_others():
    assert build_result_filename("红楼梦", "xianyu") == "红楼梦_full_data.jsonl"
    assert build_result_filename("红楼梦", "kongfz") == "kongfz__红楼梦_full_data.jsonl"
    assert parse_result_filename("红楼梦_full_data.jsonl") == ("xianyu", "红楼梦")
    assert parse_result_filename("kongfz__红楼梦_full_data.jsonl") == ("kongfz", "红楼梦")
    assert normalize_keyword_slug("红楼梦", "xianyu") == normalize_keyword_slug("红楼梦")
    assert normalize_keyword_slug("红楼梦", "kongfz").startswith("kongfz_")


def test_legacy_tasks_table_gains_xianyu_platform(tmp_path):
    conn = sqlite3.connect(tmp_path / "legacy.sqlite3")
    conn.execute("CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, task_name TEXT NOT NULL)")
    conn.execute("INSERT INTO tasks (id, task_name) VALUES (1, 'legacy')")
    _migrate_tasks_platform(conn)
    conn.commit()
    cols = [row[1] for row in conn.execute("PRAGMA table_info(tasks)")]
    assert "platform" in cols
    stored = conn.execute("SELECT platform FROM tasks WHERE id = 1").fetchone()[0]
    assert stored == "xianyu"


def test_legacy_result_items_gain_favorite_column_idempotently(tmp_path):
    from src.infrastructure.persistence.sqlite_connection import (
        _migrate_result_items_favorite,
    )

    conn = sqlite3.connect(tmp_path / "legacy.sqlite3")
    conn.execute("CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE result_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            result_filename TEXT NOT NULL,
            link_unique_key TEXT NOT NULL,
            crawl_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            raw_json TEXT NOT NULL
        )
        """
    )
    _migrate_result_items_favorite(conn)
    conn.commit()
    cols = [row[1] for row in conn.execute("PRAGMA table_info(result_items)")]
    assert "is_favorite" in cols
    indexes = {
        row[1]
        for row in conn.execute("PRAGMA index_list(result_items)")
    }
    assert "idx_results_filename_favorite_crawl" in indexes

    # 重复执行不报错也不重复加列
    _migrate_result_items_favorite(conn)
    conn.commit()
    cols_again = [row[1] for row in conn.execute("PRAGMA table_info(result_items)")]
    assert cols_again.count("is_favorite") == 1


def test_platform_roundtrip(tmp_path):
    repo = SqliteTaskRepository(db_path=str(tmp_path / "app.sqlite3"), legacy_config_file=None)
    saved = asyncio.run(repo.save(_task(platform="kongfz")))
    loaded = asyncio.run(repo.find_by_id(saved.id))
    assert loaded is not None
    assert loaded.platform == "kongfz"

    legacy = asyncio.run(repo.save(_task(task_name="闲鱼机", keyword="a7m4", description="机身")))
    loaded_legacy = asyncio.run(repo.find_by_id(legacy.id))
    assert loaded_legacy is not None
    assert loaded_legacy.platform == "xianyu"
