"""
Collector 协议定义。

一个平台采集器 = 一个模块，模块级约定：
- ``platform_id: str`` 平台标识（与 platforms.py 注册一致）
- ``async def collect(task_config: dict, debug_limit: int = 0) -> int``
  执行一次采集，返回本次处理的新商品数。

采集器内部职责：
1. 按任务筛选条件抓取商品列表；
2. 组装满足 src.collectors.contract 契约的商品记录；
3. 经 ItemAnalysisDispatcher 完成 AI/关键词判定、落盘、通知；
4. 记录价格快照（record_market_snapshots），为行情数据蓄能。

闲鱼平台通过薄包装 src.scraper.scrape_xianyu 接入（保持上游可 merge）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# 采集函数签名：(task_config, debug_limit=0) -> 新商品数
CollectFn = Callable[..., Awaitable[int]]


@dataclass(frozen=True)
class CollectorDefinition:
    """注册表中的采集器定义。"""

    platform_id: str
    collect: CollectFn


def validate_collector_module(module: Any) -> CollectorDefinition:
    """校验模块是否满足 Collector 协议并包装为定义。"""
    platform_id = getattr(module, "platform_id", None)
    collect = getattr(module, "collect", None)
    if not isinstance(platform_id, str) or not platform_id:
        raise ValueError(f"采集器模块 {module!r} 缺少 platform_id")
    if not callable(collect):
        raise ValueError(f"采集器模块 {module!r} 缺少 async collect(task_config, debug_limit)")
    return CollectorDefinition(platform_id=platform_id, collect=collect)
