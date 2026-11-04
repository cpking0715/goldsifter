"""
eBay 采集器（Pro 功能）。

走 eBay 搜索页（https://www.ebay.com/sch/i.html），服务端渲染 HTML + BeautifulSoup 解析；
无需登录态。海外站点：默认跟随系统代理（trust_env），国内用户建议配置代理。

注意：解析基于 eBay 公开页面结构（li.s-item 卡片），eBay 改版需更新选择器
（fixture 测试锁格式：tests/fixtures/ebay_search.html）。
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.ai_handler import download_all_images, get_ai_analysis, send_ntfy_notification
from src.collectors.contract import validate_item_record
from src.collectors.platforms import PLATFORM_EBAY
from src.config import SKIP_AI_ANALYSIS
from src.services.item_analysis_dispatcher import ItemAnalysisDispatcher, ItemAnalysisJob
from src.services.price_history_service import (
    build_market_reference,
    load_price_snapshots,
    record_market_snapshots,
)
from src.services.result_storage_service import (
    load_processed_link_keys,
    save_result_record,
)
from src.utils import get_link_unique_key, log_time, random_sleep

platform_id = PLATFORM_EBAY

SEARCH_URL = "https://www.ebay.com/sch/i.html"
PAGE_SIZE = 60
DEFAULT_TIMEOUT = 25.0
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
# 搜索结果首项常是占位卡（"Shop on eBay"）
_PLACEHOLDER_PREFIX = "shop on ebay"

_PRICE_RE = re.compile(r"[\d,]+\.?\d*")


def _parse_price(text: str) -> str:
    """'$1,234.56' -> '¥...' 不做汇率换算，保留美元符号与数值。"""
    match = _PRICE_RE.search(text or "")
    if not match:
        return "价格异常"
    return f"${match.group(0)}"


def _extract_item_id(link: str) -> str:
    # 两种形态：/itm/<纯数字> 与 /itm/<slug>-<数字>；ID 恒为路径末段中的数字
    match = re.search(r"/itm/(\d+)(?:[/?]|$)", link or "")
    if match:
        return match.group(1)
    match = re.search(r"/itm/[^/]*?-(\d+)(?:[/?]|$)", link or "")
    if match:
        return match.group(1)
    return ""


def parse_search_html(html: str) -> list[dict]:
    """解析 eBay 搜索页 HTML 为商品契约字段列表。"""
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for card in soup.select("li.s-item, .srp-results li[data-view]"):
        title_el = card.select_one(".s-item__title")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title or title.lower().startswith(_PLACEHOLDER_PREFIX):
            continue

        price_el = card.select_one(".s-item__price")
        link_el = card.select_one(".s-item__link")
        link = (link_el.get("href") or "").split("?")[0] if link_el else ""
        if not link:
            continue

        img_el = card.select_one("img")
        image = ""
        if img_el:
            image = img_el.get("src") or img_el.get("data-src") or ""

        condition_el = card.select_one(".SECONDARY_INFO")
        condition = condition_el.get_text(strip=True) if condition_el else ""
        shipping_el = card.select_one(".s-item__shipping, .s-item__freeXdays")
        shipping = shipping_el.get_text(strip=True) if shipping_el else ""
        location_el = card.select_one(".s-item__location")
        location = location_el.get_text(strip=True).replace("from ", "") if location_el else ""
        seller_el = card.select_one(".s-item__seller-info-text")
        seller = seller_el.get_text(strip=True) if seller_el else ""

        tags = []
        if condition:
            tags.append(condition)
        if "free" in shipping.lower() or "免" in shipping:
            tags.append("Free shipping")

        items.append(
            {
                "商品标题": title,
                "当前售价": _parse_price(price_el.get_text(strip=True) if price_el else ""),
                "商品原价": "暂无",
                "“想要”人数": "NaN",
                "商品标签": tags,
                "发货地区": location or "地区未知",
                "卖家昵称": seller or "eBay Seller",
                "商品链接": link,
                "发布时间": "未知时间",
                "商品ID": _extract_item_id(link) or link.rsplit("/", 1)[-1],
                "商品图片列表": [image] if image else [],
                "商品主图链接": image,
                "浏览量": "-",
                # eBay 特有信息
                "成色": condition,
                "运费": shipping,
            }
        )
    return items


async def _fetch_page(
    client: httpx.AsyncClient, keyword: str, page: int, min_price, max_price
) -> str:
    params = {"_nkw": keyword, "_ipg": str(PAGE_SIZE)}
    if page > 1:
        params["_pgn"] = str(page)
    if str(min_price or "").strip() or str(max_price or "").strip():
        params["_mPrRngCbx"] = "1"
        if str(min_price or "").strip():
            params["_udlo"] = str(min_price).strip()
        if str(max_price or "").strip():
            params["_udhi"] = str(max_price).strip()

    last_error: Optional[Exception] = None
    for attempt in range(1, 3):
        try:
            resp = await client.get(SEARCH_URL, params=params)
            if resp.status_code == 403:
                raise RuntimeError(
                    "eBay 拒绝访问（403）：当前出口 IP 被限制。国内网络请配置代理后重试。"
                )
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            last_error = exc
            print(f"   [eBay] 第 {attempt}/2 次抓取第 {page} 页失败: {exc}")
            if attempt < 2:
                await asyncio.sleep(5)
    raise RuntimeError(f"eBay 第 {page} 页抓取失败: {last_error}")


def _ai_concurrency() -> int:
    import os

    try:
        return max(1, int(os.getenv("AI_ANALYSIS_CONCURRENCY", "2")))
    except ValueError:
        return 2


async def collect(task_config: dict, debug_limit: int = 0) -> int:
    """执行一次 eBay 采集，返回本次处理的新商品数。"""
    keyword = task_config["keyword"]
    task_name = task_config.get("task_name", "Untitled Task")
    max_pages = int(task_config.get("max_pages", 1) or 1)
    min_price = task_config.get("min_price")
    max_price = task_config.get("max_price")
    ai_prompt_text = task_config.get("ai_prompt_text", "")
    analyze_images = bool(task_config.get("analyze_images", True))
    decision_mode = str(task_config.get("decision_mode", "ai")).strip().lower()
    if decision_mode not in {"ai", "keyword"}:
        decision_mode = "ai"
    keyword_rules = task_config.get("keyword_rules") or []

    platform = PLATFORM_EBAY
    processed_links = load_processed_link_keys(keyword, platform=platform)
    historical_snapshots = load_price_snapshots(keyword, platform=platform)
    history_run_id = datetime.now().strftime("%Y%m%d%H%M%S")

    async def _save_record(record: dict, kw: str) -> bool:
        return await save_result_record(record, kw, platform=platform)

    async def _noop_seller_loader(seller_id: str) -> dict:
        return {}

    dispatcher = ItemAnalysisDispatcher(
        concurrency=_ai_concurrency(),
        skip_ai_analysis=SKIP_AI_ANALYSIS,
        seller_loader=_noop_seller_loader,
        image_downloader=download_all_images,
        ai_analyzer=get_ai_analysis,
        notifier=send_ntfy_notification,
        saver=_save_record,
    )

    processed_count = 0
    seen_snapshot_ids: set[str] = set()

    async with httpx.AsyncClient(
        headers=REQUEST_HEADERS,  # 海外站：默认跟随系统代理（trust_env）
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for page_num in range(1, max_pages + 1):
            log_time(f"[eBay] 抓取第 {page_num}/{max_pages} 页，关键词: {keyword}")
            html = await _fetch_page(client, keyword, page_num, min_price, max_price)
            page_items = parse_search_html(html)
            if not page_items:
                print(f"   [eBay] 第 {page_num} 页无结果，停止翻页。")
                break

            record_market_snapshots(
                keyword=keyword,
                task_name=task_name,
                items=page_items,
                run_id=history_run_id,
                seen_item_ids=seen_snapshot_ids,
                platform=platform,
            )

            for item_data in page_items:
                unique_key = get_link_unique_key(item_data["商品链接"])
                if not unique_key or unique_key in processed_links:
                    continue
                if 0 < debug_limit <= processed_count:
                    break

                final_record = {
                    "爬取时间": datetime.now().isoformat(),
                    "搜索关键字": keyword,
                    "任务名称": task_name,
                    "商品信息": item_data,
                    "卖家信息": {},
                    "来源平台": platform,
                }
                price_reference = build_market_reference(
                    keyword=keyword,
                    item=item_data,
                    current_market_items=page_items,
                    historical_snapshots=historical_snapshots,
                )
                final_record["价格参考"] = price_reference
                final_record["price_insight"] = price_reference.get("本商品价格位置", {})

                ok, problems = validate_item_record(final_record)
                if not ok:
                    print(f"   [eBay] 商品记录未通过契约校验，跳过: {problems}")
                    processed_links.add(unique_key)
                    continue

                dispatcher.submit(
                    ItemAnalysisJob(
                        keyword=keyword,
                        task_name=task_name,
                        decision_mode=decision_mode,
                        analyze_images=analyze_images,
                        prompt_text=ai_prompt_text,
                        keyword_rules=tuple(keyword_rules),
                        final_record=final_record,
                        seller_id=None,
                        zhima_credit_text=None,
                        registration_duration_text="",
                    )
                )
                processed_links.add(unique_key)
                processed_count += 1
                log_time(f"商品已提交后台分析。累计处理 {processed_count} 个新商品。")

            if 0 < debug_limit <= processed_count:
                break
            if page_num < max_pages:
                await random_sleep(2, 5)

    await dispatcher.join()
    return processed_count
