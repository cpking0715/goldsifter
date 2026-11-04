"""
结果数据的 SQLite 读写服务。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.infrastructure.persistence.storage_names import build_result_filename
from src.services.price_history_service import parse_price_value
from src.services.result_blacklist_service import (
    match_blacklist_keywords,
    normalize_blacklist_keywords,
)


SORT_COLUMN_MAP = {
    "crawl_time": "crawl_time",
    "publish_time": "COALESCE(publish_time, '')",
    "price": "COALESCE(price, 0)",
    "keyword_hit_count": "keyword_hit_count",
}

# 高性价比分类的 value_score 阈值（AI 输出的 0-100 性价比分）
HIGH_VALUE_SCORE_THRESHOLD = 60.0

CATEGORY_ALL = "all"
CATEGORY_AI_RECOMMENDED = "ai_recommended"
CATEGORY_HIGH_VALUE = "high_value"
CATEGORY_KEYWORD_HIT = "keyword_hit"
CATEGORY_FAVORITE = "favorite"
CATEGORY_HIDDEN = "hidden"
RESULT_CATEGORIES = (
    CATEGORY_ALL,
    CATEGORY_AI_RECOMMENDED,
    CATEGORY_HIGH_VALUE,
    CATEGORY_KEYWORD_HIT,
    CATEGORY_FAVORITE,
    CATEGORY_HIDDEN,
)


def _get_link_unique_key(link: str) -> str:
    return link.split("&", 1)[0]


def _fallback_unique_key(record: dict, item: dict) -> str:
    item_id = str(item.get("商品ID") or "").strip()
    if item_id:
        return f"item:{item_id}"
    digest = hashlib.sha1(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"hash:{digest}"


def _parse_raw_record(
    raw_json: str, *, status: str | None = None, is_favorite: bool = False
) -> dict:
    record = json.loads(raw_json)
    if status is not None:
        record["_status"] = status
    record["_is_favorite"] = is_favorite
    return record


def _record_value_score(record: dict) -> float | None:
    analysis = record.get("ai_analysis") or {}
    try:
        return float(analysis.get("value_score"))
    except (TypeError, ValueError):
        return None


def _is_ai_recommended_record(record: dict) -> bool:
    analysis = record.get("ai_analysis") or {}
    return (
        analysis.get("analysis_source") == "ai"
        and analysis.get("is_recommended") is True
    )


def _is_keyword_hit_record(record: dict) -> bool:
    analysis = record.get("ai_analysis") or {}
    return (
        analysis.get("analysis_source") == "keyword"
        and analysis.get("is_recommended") is True
    )


def _is_high_value_record(record: dict) -> bool:
    score = _record_value_score(record)
    return score is not None and score >= HIGH_VALUE_SCORE_THRESHOLD


def _record_matches_category(record: dict, category: str) -> bool:
    if category == CATEGORY_AI_RECOMMENDED:
        return _is_ai_recommended_record(record)
    if category == CATEGORY_HIGH_VALUE:
        return _is_high_value_record(record)
    if category == CATEGORY_KEYWORD_HIT:
        return _is_keyword_hit_record(record)
    if category == CATEGORY_FAVORITE:
        return record.get("_is_favorite") is True
    if category == CATEGORY_HIDDEN:
        return not _is_record_visible(record)
    return True


def _record_search_text(record: dict) -> str:
    item = record.get("商品信息", {}) or {}
    seller = record.get("卖家信息", {}) or {}
    parts = [
        str(item.get("商品标题") or ""),
        str(seller.get("卖家昵称") or item.get("卖家昵称") or ""),
    ]
    return " ".join(part for part in parts if part)


def _record_price(record: dict) -> float | None:
    item = record.get("商品信息", {}) or {}
    return parse_price_value(item.get("当前售价"))


def _sort_expression(sort_by: str, sort_order: str) -> str:
    column = SORT_COLUMN_MAP.get(sort_by, SORT_COLUMN_MAP["crawl_time"])
    direction = "ASC" if sort_order == "asc" else "DESC"
    return f"(CASE WHEN status = 'active' THEN 0 ELSE 1 END), {column} {direction}, id {direction}"


def _load_blacklist_keywords_from_conn(conn, filename: str) -> list[str]:
    row = conn.execute(
        """
        SELECT blacklist_keywords_json
        FROM result_blacklist_rules
        WHERE result_filename = ?
        """,
        (filename,),
    ).fetchone()
    if row is None:
        return []
    try:
        payload = json.loads(row["blacklist_keywords_json"] or "[]")
    except json.JSONDecodeError:
        return []
    return normalize_blacklist_keywords(payload)


def _decorate_record_visibility(record: dict, status: str | None, blacklist_keywords: list[str]) -> dict:
    matched_keywords = match_blacklist_keywords(record, blacklist_keywords)
    hidden_reason = None
    if status == "expired":
        hidden_reason = "expired"
    elif status and status != "active":
        hidden_reason = "manual"
    elif matched_keywords:
        hidden_reason = "rule"

    record["_status"] = status or "active"
    record["_matched_blacklist_keywords"] = matched_keywords
    record["_hidden_reason"] = hidden_reason
    record["_effective_hidden"] = hidden_reason is not None
    return record


def _is_record_visible(record: dict) -> bool:
    return record.get("_effective_hidden") is not True


def _load_decorated_records_from_conn(
    conn,
    *,
    filename: str,
    sort_by: str = "crawl_time",
    sort_order: str = "desc",
) -> list[dict]:
    """加载结果集全部记录并完成可见性/收藏装饰（不做任何过滤）。"""
    order_clause = _sort_expression(sort_by, sort_order)
    rows = conn.execute(
        f"""
        SELECT raw_json, status, is_favorite
        FROM result_items
        WHERE result_filename = ?
        ORDER BY {order_clause}
        """,
        (filename,),
    ).fetchall()
    blacklist_keywords = _load_blacklist_keywords_from_conn(conn, filename)

    records: list[dict] = []
    for row in rows:
        record = _parse_raw_record(
            str(row["raw_json"]),
            status=row["status"],
            is_favorite=bool(row["is_favorite"]),
        )
        records.append(
            _decorate_record_visibility(record, row["status"], blacklist_keywords)
        )
    return records


def _apply_record_filters(
    records: list[dict],
    *,
    ai_recommended_only: bool = False,
    keyword_recommended_only: bool = False,
    include_hidden: bool = False,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    found_since: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """在装饰后的记录上应用过滤（分类/搜索/价格/时间/收藏/可见性）。"""
    search_text = (search or "").strip().lower()
    effective_category = category or CATEGORY_ALL
    show_hidden_only = effective_category == CATEGORY_HIDDEN

    filtered: list[dict] = []
    for record in records:
        if show_hidden_only:
            if _is_record_visible(record):
                continue
        else:
            if not include_hidden and not _is_record_visible(record):
                continue
            if not _record_matches_category(record, effective_category):
                continue
            if ai_recommended_only and not _is_ai_recommended_record(record):
                continue
            if keyword_recommended_only and not _is_keyword_hit_record(record):
                continue
        if search_text and search_text not in _record_search_text(record).lower():
            continue
        if min_price is not None or max_price is not None:
            price = _record_price(record)
            if price is None:
                continue
            if min_price is not None and price < min_price:
                continue
            if max_price is not None and price > max_price:
                continue
        # 爬取时间与 found_since 均为本地 naive ISO 字符串，可直接字典序比较
        if found_since and not str(record.get("爬取时间") or "") >= found_since:
            continue
        filtered.append(record)
    return filtered


def _sort_records_by_value_score(records: list[dict], sort_order: str) -> None:
    """按 AI 性价比分排序，缺失分数的记录固定排在末尾。"""
    reverse = sort_order != "asc"
    scored = [record for record in records if _record_value_score(record) is not None]
    unscored = [record for record in records if _record_value_score(record) is None]
    scored.sort(key=_record_value_score, reverse=reverse)
    records[:] = scored + unscored


def _count_result_categories(records: list[dict]) -> dict[str, int]:
    """统计各分类数量（基于全部记录，不叠加搜索/价格等过滤条件）。"""
    visible = [record for record in records if _is_record_visible(record)]
    hidden_count = len(records) - len(visible)
    return {
        CATEGORY_ALL: len(visible),
        CATEGORY_AI_RECOMMENDED: sum(1 for r in visible if _is_ai_recommended_record(r)),
        CATEGORY_HIGH_VALUE: sum(1 for r in visible if _is_high_value_record(r)),
        CATEGORY_KEYWORD_HIT: sum(1 for r in visible if _is_keyword_hit_record(r)),
        CATEGORY_FAVORITE: sum(1 for r in visible if r.get("_is_favorite") is True),
        CATEGORY_HIDDEN: hidden_count,
    }


def _load_filtered_records_from_conn(
    conn,
    *,
    filename: str,
    ai_recommended_only: bool = False,
    keyword_recommended_only: bool = False,
    sort_by: str = "crawl_time",
    sort_order: str = "desc",
    include_hidden: bool = False,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    found_since: str | None = None,
    category: str | None = None,
) -> list[dict]:
    records = _load_decorated_records_from_conn(
        conn, filename=filename, sort_by=sort_by, sort_order=sort_order
    )
    return _apply_record_filters(
        records,
        ai_recommended_only=ai_recommended_only,
        keyword_recommended_only=keyword_recommended_only,
        include_hidden=include_hidden,
        search=search,
        min_price=min_price,
        max_price=max_price,
        found_since=found_since,
        category=category,
    )


async def save_result_record(record: dict, keyword: str, platform: str = "xianyu") -> bool:
    return await asyncio.to_thread(_save_result_record_sync, record, keyword, platform)


def _save_result_record_sync(record: dict, keyword: str, platform: str) -> bool:
    bootstrap_sqlite_storage()
    item = record.get("商品信息", {}) or {}
    analysis = record.get("ai_analysis", {}) or {}
    link = str(item.get("商品链接") or "")
    link_unique_key = _get_link_unique_key(link) if link else _fallback_unique_key(record, item)
    keyword_hit_count = analysis.get("keyword_hit_count", 0)
    try:
        keyword_hit_count = int(keyword_hit_count)
    except (TypeError, ValueError):
        keyword_hit_count = 0

    with sqlite_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO result_items (
                result_filename, keyword, task_name, crawl_time, publish_time, price,
                price_display, item_id, title, link, link_unique_key, seller_nickname,
                is_recommended, analysis_source, keyword_hit_count, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                build_result_filename(keyword, platform),
                record.get("搜索关键字", keyword),
                record.get("任务名称", ""),
                record.get("爬取时间", ""),
                item.get("发布时间"),
                parse_price_value(item.get("当前售价")),
                item.get("当前售价"),
                item.get("商品ID"),
                item.get("商品标题"),
                link,
                link_unique_key,
                (record.get("卖家信息", {}) or {}).get("卖家昵称") or item.get("卖家昵称"),
                1 if analysis.get("is_recommended") else 0,
                analysis.get("analysis_source"),
                keyword_hit_count,
                json.dumps(record, ensure_ascii=False),
            ),
        )
        conn.commit()
    return True


def load_processed_link_keys(keyword: str, platform: str = "xianyu") -> set[str]:
    bootstrap_sqlite_storage()
    filename = build_result_filename(keyword, platform)
    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT link_unique_key FROM result_items WHERE result_filename = ?",
            (filename,),
        ).fetchall()
    return {str(row["link_unique_key"]) for row in rows if row["link_unique_key"]}


async def list_result_filenames() -> list[str]:
    return await asyncio.to_thread(_list_result_filenames_sync)


def _list_result_filenames_sync() -> list[str]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        rows = conn.execute(
            """
            SELECT result_filename, MAX(crawl_time) AS latest_crawl_time
            FROM result_items
            GROUP BY result_filename
            ORDER BY latest_crawl_time DESC, result_filename DESC
            """
        ).fetchall()
    return [str(row["result_filename"]) for row in rows]


async def result_file_exists(filename: str) -> bool:
    return await asyncio.to_thread(_result_file_exists_sync, filename)


def _result_file_exists_sync(filename: str) -> bool:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM result_items WHERE result_filename = ? LIMIT 1",
            (filename,),
        ).fetchone()
    return row is not None


async def delete_result_file_records(filename: str) -> int:
    return await asyncio.to_thread(_delete_result_file_records_sync, filename)


def _delete_result_file_records_sync(filename: str) -> int:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM result_items WHERE result_filename = ?",
            (filename,),
        )
        conn.commit()
    return int(cursor.rowcount or 0)


async def query_result_records(
    filename: str,
    *,
    ai_recommended_only: bool = False,
    keyword_recommended_only: bool = False,
    sort_by: str = "crawl_time",
    sort_order: str = "desc",
    page: int = 1,
    limit: int = 20,
    include_hidden: bool = False,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    found_since: str | None = None,
    category: str | None = None,
) -> tuple[int, list[dict], dict[str, int]]:
    return await asyncio.to_thread(
        _query_result_records_sync,
        filename,
        ai_recommended_only,
        keyword_recommended_only,
        sort_by,
        sort_order,
        page,
        limit,
        include_hidden,
        search,
        min_price,
        max_price,
        found_since,
        category,
    )


def _query_result_records_sync(
    filename: str,
    ai_recommended_only: bool,
    keyword_recommended_only: bool,
    sort_by: str,
    sort_order: str,
    page: int,
    limit: int,
    include_hidden: bool,
    search: str | None,
    min_price: float | None,
    max_price: float | None,
    found_since: str | None,
    category: str | None,
) -> tuple[int, list[dict], dict[str, int]]:
    bootstrap_sqlite_storage()
    offset = max(page - 1, 0) * limit
    with sqlite_connection() as conn:
        all_records = _load_decorated_records_from_conn(
            conn, filename=filename, sort_by=sort_by, sort_order=sort_order
        )
    counts = _count_result_categories(all_records)
    records = _apply_record_filters(
        all_records,
        ai_recommended_only=ai_recommended_only,
        keyword_recommended_only=keyword_recommended_only,
        include_hidden=include_hidden,
        search=search,
        min_price=min_price,
        max_price=max_price,
        found_since=found_since,
        category=category,
    )
    if sort_by == "value_score":
        _sort_records_by_value_score(records, sort_order)
    total = len(records)
    return total, records[offset: offset + limit], counts


async def load_result_category_counts(filename: str) -> dict[str, int]:
    return await asyncio.to_thread(_load_result_category_counts_sync, filename)


def _load_result_category_counts_sync(filename: str) -> dict[str, int]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        records = _load_decorated_records_from_conn(conn, filename=filename)
    return _count_result_categories(records)


async def load_all_result_records(
    filename: str,
    *,
    ai_recommended_only: bool = False,
    keyword_recommended_only: bool = False,
    sort_by: str = "crawl_time",
    sort_order: str = "desc",
    include_hidden: bool = False,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    found_since: str | None = None,
    category: str | None = None,
) -> list[dict]:
    return await asyncio.to_thread(
        _load_all_result_records_sync,
        filename,
        ai_recommended_only,
        keyword_recommended_only,
        sort_by,
        sort_order,
        include_hidden,
        search,
        min_price,
        max_price,
        found_since,
        category,
    )


def _load_all_result_records_sync(
    filename: str,
    ai_recommended_only: bool,
    keyword_recommended_only: bool,
    sort_by: str,
    sort_order: str,
    include_hidden: bool,
    search: str | None,
    min_price: float | None,
    max_price: float | None,
    found_since: str | None,
    category: str | None,
) -> list[dict]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        records = _load_filtered_records_from_conn(
            conn,
            filename=filename,
            ai_recommended_only=ai_recommended_only,
            keyword_recommended_only=keyword_recommended_only,
            sort_by=sort_by,
            sort_order=sort_order,
            include_hidden=include_hidden,
            search=search,
            min_price=min_price,
            max_price=max_price,
            found_since=found_since,
            category=category,
        )
    if sort_by == "value_score":
        _sort_records_by_value_score(records, sort_order)
    return records


async def build_result_ndjson(filename: str) -> str:
    return await asyncio.to_thread(_build_result_ndjson_sync, filename)


def _build_result_ndjson_sync(filename: str) -> str:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT raw_json FROM result_items WHERE result_filename = ? ORDER BY id ASC",
            (filename,),
        ).fetchall()
    return "\n".join(str(row["raw_json"]) for row in rows)


async def load_result_summary(filename: str) -> dict | None:
    return await asyncio.to_thread(_load_result_summary_sync, filename)


def _load_result_summary_sync(filename: str) -> dict | None:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        visible_records = _load_filtered_records_from_conn(
            conn,
            filename=filename,
            ai_recommended_only=False,
            keyword_recommended_only=False,
            sort_by="crawl_time",
            sort_order="desc",
            include_hidden=False,
        )
    if not visible_records:
        return None

    recommended_records = [
        record
        for record in visible_records
        if (record.get("ai_analysis", {}) or {}).get("is_recommended") is True
    ]
    ai_recommended_items = 0
    keyword_recommended_items = 0
    for record in recommended_records:
        source = (record.get("ai_analysis", {}) or {}).get("analysis_source")
        if source == "ai":
            ai_recommended_items += 1
        elif source == "keyword":
            keyword_recommended_items += 1

    return {
        "total_items": len(visible_records),
        "recommended_items": len(recommended_records),
        "ai_recommended_items": ai_recommended_items,
        "keyword_recommended_items": keyword_recommended_items,
        "latest_crawl_time": visible_records[0].get("爬取时间"),
        "latest_record": visible_records[0],
        "latest_recommendation": recommended_records[0] if recommended_records else None,
    }


async def update_item_favorite(filename: str, item_id: str, favorite: bool) -> bool:
    return await asyncio.to_thread(
        _update_item_favorite_sync, filename, item_id, favorite
    )


def _update_item_favorite_sync(filename: str, item_id: str, favorite: bool) -> bool:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        cursor = conn.execute(
            "UPDATE result_items SET is_favorite = ? WHERE result_filename = ? AND item_id = ?",
            (1 if favorite else 0, filename, item_id),
        )
        conn.commit()
        return cursor.rowcount > 0


async def update_item_status(filename: str, item_id: str, status: str) -> bool:
    valid = {"active", "hidden", "expired"}
    if status not in valid:
        raise ValueError(f"status must be one of {valid}")
    return await asyncio.to_thread(_update_item_status_sync, filename, item_id, status)


def _update_item_status_sync(filename: str, item_id: str, status: str) -> bool:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        cursor = conn.execute(
            "UPDATE result_items SET status = ? WHERE result_filename = ? AND item_id = ?",
            (status, filename, item_id),
        )
        conn.commit()
        return cursor.rowcount > 0


async def load_result_blacklist_keywords(filename: str) -> list[str]:
    return await asyncio.to_thread(_load_result_blacklist_keywords_sync, filename)


def _load_result_blacklist_keywords_sync(filename: str) -> list[str]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        return _load_blacklist_keywords_from_conn(conn, filename)


async def save_result_blacklist_keywords(filename: str, keywords: list[str]) -> list[str]:
    return await asyncio.to_thread(_save_result_blacklist_keywords_sync, filename, keywords)


def _save_result_blacklist_keywords_sync(filename: str, keywords: list[str]) -> list[str]:
    bootstrap_sqlite_storage()
    normalized_keywords = normalize_blacklist_keywords(keywords)
    now = datetime.now().isoformat()
    with sqlite_connection() as conn:
        conn.execute(
            """
            INSERT INTO result_blacklist_rules (
                result_filename, blacklist_keywords_json, updated_at
            ) VALUES (?, ?, ?)
            ON CONFLICT(result_filename) DO UPDATE SET
                blacklist_keywords_json = excluded.blacklist_keywords_json,
                updated_at = excluded.updated_at
            """,
            (filename, json.dumps(normalized_keywords, ensure_ascii=False), now),
        )
        conn.commit()
    return normalized_keywords


def load_visible_result_item_ids(filename: str) -> set[str]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        visible_records = _load_filtered_records_from_conn(
            conn,
            filename=filename,
            ai_recommended_only=False,
            keyword_recommended_only=False,
            sort_by="crawl_time",
            sort_order="desc",
            include_hidden=False,
        )
    item_ids: set[str] = set()
    for record in visible_records:
        product = record.get("商品信息", {}) or {}
        item_id = str(product.get("商品ID") or "").strip()
        if item_id:
            item_ids.add(item_id)
    return item_ids
