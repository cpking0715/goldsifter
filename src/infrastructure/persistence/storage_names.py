"""
SQLite 持久化相关的统一命名规则。

多平台约定：
- 闲鱼保持历史命名 `<keyword>_full_data.jsonl`（向后兼容存量数据）；
- 其他平台加平台前缀 `<platform>__<keyword>_full_data.jsonl`；
- 价格快照 slug 同理：闲鱼为 `<keyword_slug>`，其他平台为 `<platform>_<keyword_slug>`。
"""
from __future__ import annotations

from src.collectors.platforms import PLATFORM_XIANYU, list_platforms

DEFAULT_DATABASE_PATH = "data/app.sqlite3"
RESULT_FILE_SUFFIX = "_full_data.jsonl"
PLATFORM_PREFIX_SEP = "__"


def build_result_filename(keyword: str, platform: str = PLATFORM_XIANYU) -> str:
    base = f"{str(keyword or '').replace(' ', '_')}{RESULT_FILE_SUFFIX}"
    if not platform or platform == PLATFORM_XIANYU:
        # 闲鱼保持历史命名，向后兼容
        return base
    return f"{platform}{PLATFORM_PREFIX_SEP}{base}"


def parse_result_filename(filename: str) -> tuple[str, str]:
    """从结果文件名解析 (platform, keyword)。无前缀视为闲鱼。"""
    name = str(filename or "")
    for info in list_platforms():
        if info.platform_id == PLATFORM_XIANYU:
            continue
        prefix = f"{info.platform_id}{PLATFORM_PREFIX_SEP}"
        if name.startswith(prefix):
            keyword = name[len(prefix):].replace(RESULT_FILE_SUFFIX, "")
            return info.platform_id, keyword
    return PLATFORM_XIANYU, name.replace(RESULT_FILE_SUFFIX, "")


def normalize_keyword_from_filename(filename: str) -> str:
    """兼容旧调用：仅返回关键词（丢弃平台前缀）。"""
    _platform, keyword = parse_result_filename(filename)
    return keyword


def normalize_keyword_slug(keyword: str, platform: str = PLATFORM_XIANYU) -> str:
    text = "".join(
        char for char in str(keyword or "").lower().replace(" ", "_")
        if char.isalnum() or char in "_-"
    ).rstrip("_")
    slug = text or "unknown"
    if not platform or platform == PLATFORM_XIANYU:
        # 闲鱼保持历史 slug，向后兼容存量快照
        return slug
    return f"{platform}_{slug}"
