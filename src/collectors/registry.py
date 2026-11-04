"""
Collector 注册表：platform_id -> 采集器模块路径。

懒加载：仅在真正需要采集时 import 对应模块，
避免 API 进程加载 playwright 等重型依赖。
"""
from __future__ import annotations

import importlib

from src.collectors.base import CollectorDefinition, validate_collector_module
from src.collectors.platforms import PLATFORM_EBAY, PLATFORM_KONGFZ, PLATFORM_XIANYU

# 平台 -> 采集器模块路径
_COLLECTOR_MODULES: dict[str, str] = {
    PLATFORM_XIANYU: "src.collectors.xianyu",
    PLATFORM_KONGFZ: "src.collectors.kongfz",
    PLATFORM_EBAY: "src.collectors.ebay",
}

_cache: dict[str, CollectorDefinition] = {}


def get_collector(platform: str | None) -> CollectorDefinition:
    """按平台获取采集器定义，未注册平台抛 ValueError。"""
    key = str(platform or "").strip().lower()
    if key not in _COLLECTOR_MODULES:
        raise ValueError(
            f"平台 '{platform}' 没有注册采集器，已注册: {sorted(_COLLECTOR_MODULES)}"
        )
    if key not in _cache:
        module = importlib.import_module(_COLLECTOR_MODULES[key])
        _cache[key] = validate_collector_module(module)
    return _cache[key]
