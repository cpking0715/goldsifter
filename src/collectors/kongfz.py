"""
孔夫子旧书网采集器。

走服务端 JSON 搜索接口（无需登录态、无签名），产出与闲鱼一致的商品契约，
复用 ItemAnalysisDispatcher 完成 AI/关键词判定、落盘与通知。
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Optional

import httpx

from src.ai_handler import download_all_images, get_ai_analysis, send_ntfy_notification
from src.collectors.contract import validate_item_record
from src.collectors.platforms import PLATFORM_KONGFZ
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

platform_id = PLATFORM_KONGFZ

SEARCH_API = "https://search.kongfz.com/pc-gw/search-web/client/pc/product/keyword/list"
PAGE_SIZE = 20
DEFAULT_TIMEOUT = 30.0
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://search.kongfz.com/product/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _ai_concurrency() -> int:
    try:
        return max(1, int(os.getenv("AI_ANALYSIS_CONCURRENCY", "2")))
    except ValueError:
        return 2


async def _noop_seller_loader(seller_id: str) -> dict:
    """孔夫子 MVP 不采集卖家深度画像。"""
    return {}


def _build_item_data(raw: dict) -> dict:
    """把孔夫子接口字段映射为统一的商品契约字段。"""
    link = ""
    raw_link = raw.get("link")
    if isinstance(raw_link, dict):
        link = str(raw_link.get("pc") or "")

    images = []
    for key in ("imgBigUrl", "imgUrl"):
        url = str(raw.get(key) or "").strip()
        if url:
            images.append(url)
            break

    price_text = str(raw.get("priceText") or raw.get("price") or "价格异常")
    price_text = f"¥{price_text}" if not price_text.startswith("¥") else price_text

    tags = []
    quality = str(raw.get("qualityText") or "").strip()
    if quality:
        tags.append(f"品相:{quality}")
    postage = raw.get("postage")
    if isinstance(postage, dict) and postage.get("sellerPayFreight"):
        tags.append("包邮")

    return {
        "商品标题": str(raw.get("title") or "未知标题"),
        "当前售价": price_text,
        "商品原价": "暂无",
        "“想要”人数": "NaN",
        "商品标签": tags,
        "发货地区": str(raw.get("shopAreaText") or "地区未知"),
        "卖家昵称": str(raw.get("shopNickName") or raw.get("shopName") or "匿名卖家"),
        "商品链接": link,
        "发布时间": str(raw.get("showTimeText") or "未知时间"),
        "商品ID": str(raw.get("itemId") or ""),
        "商品图片列表": images,
        "商品主图链接": images[0] if images else "",
        "浏览量": "-",
        # 孔夫子特有信息（供 AI 与结果展示使用）
        "品相": quality,
        "作者": str(raw.get("author") or ""),
        "出版社": str(raw.get("press") or ""),
        "出版时间": str(raw.get("pubDateText") or ""),
        "书店发货时效": str(raw.get("shopAvgShippingTime") or ""),
        "书店成单率": str(raw.get("shopSuccessOrderRate") or ""),
    }


def _build_price_param(min_price, max_price) -> Optional[str]:
    """组装孔夫子价格筛选参数（格式 min~max）。"""
    min_text = str(min_price or "").strip()
    max_text = str(max_price or "").strip()
    if min_text and max_text:
        return f"{min_text}~{max_text}"
    if min_text:
        return f"{min_text}~"
    if max_text:
        return f"~{max_text}"
    return None


async def _fetch_page(
    client: httpx.AsyncClient,
    keyword: str,
    page: int,
    min_price,
    max_price,
) -> list[dict]:
    """抓取一页搜索结果，带 2 次重试。"""
    params = {
        "keyword": keyword,
        "page": page,
        "size": PAGE_SIZE,
        "status": 0,
    }
    price_param = _build_price_param(min_price, max_price)
    if price_param:
        params["price"] = price_param

    last_error: Optional[Exception] = None
    for attempt in range(1, 3):
        try:
            response = await client.get(SEARCH_API, params=params)
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") not in (1, 0, "1", "0"):
                raise ValueError(f"孔夫子接口返回异常: {payload.get('message') or payload.get('errType')}")
            items = (
                payload.get("data", {}).get("itemResponse", {}).get("list", []) or []
            )
            return items
        except Exception as exc:
            last_error = exc
            print(f"   [孔夫子] 第 {attempt}/2 次抓取第 {page} 页失败: {exc}")
            if attempt < 2:
                await asyncio.sleep(3)
    raise RuntimeError(f"孔夫子搜索第 {page} 页抓取失败: {last_error}")


async def collect(task_config: dict, debug_limit: int = 0) -> int:
    """执行一次孔夫子采集，返回本次处理的新商品数。"""
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

    platform = PLATFORM_KONGFZ
    processed_links = load_processed_link_keys(keyword, platform=platform)
    historical_snapshots = load_price_snapshots(keyword, platform=platform)
    history_run_id = datetime.now().strftime("%Y%m%d%H%M%S")

    async def _save_record(record: dict, kw: str) -> bool:
        return await save_result_record(record, kw, platform=platform)

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
        headers=REQUEST_HEADERS,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for page_num in range(1, max_pages + 1):
            log_time(f"[孔夫子] 抓取第 {page_num}/{max_pages} 页，关键词: {keyword}")
            raw_items = await _fetch_page(client, keyword, page_num, min_price, max_price)
            if not raw_items:
                print(f"   [孔夫子] 第 {page_num} 页无结果，停止翻页。")
                break

            page_items = [
                _build_item_data(raw)
                for raw in raw_items
                if not raw.get("isSoldOut")
            ]

            # 全量记录价格快照（含已见商品），为行情数据蓄能
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
                    print(f"   [孔夫子] 商品记录未通过契约校验，跳过: {problems}")
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
                log_time(
                    f"商品已提交后台分析。累计处理 {processed_count} 个新商品。"
                )

            if 0 < debug_limit <= processed_count:
                break
            if page_num < max_pages:
                await random_sleep(2, 5)

    await dispatcher.join()
    return processed_count
