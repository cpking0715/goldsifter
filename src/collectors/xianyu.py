"""
闲鱼采集器：薄包装既有 scrape_xianyu。

刻意不改动 src/scraper.py 内部逻辑，保持与上游仓库的可 merge 性；
平台化改造（platform 参数默认闲鱼）让 scraper 无需感知多平台。
"""
from __future__ import annotations

from src.collectors.platforms import PLATFORM_XIANYU
from src.scraper import scrape_xianyu

platform_id = PLATFORM_XIANYU


async def collect(task_config: dict, debug_limit: int = 0) -> int:
    return await scrape_xianyu(task_config=task_config, debug_limit=debug_limit)
