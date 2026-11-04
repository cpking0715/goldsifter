"""
悠悠有品采集器（Pro 功能，游戏饰品市场）。

Playwright 无头方案：悠悠有品 PC 站有设备指纹风控（deviceW2），直接调 API
需要复刻签名；本采集器用真实浏览器渲染（反检测脚本），再在页面上下文内
fetch 数据接口（携带页面会话），稳定绕过风控。

数据链路：
1. querySaleTemplate（keyWords=任务关键词）→ 饰品模板列表
2. queryOnSaleCommodityList（每模板价格升序）→ 低价在售单品（磨损/价格/发布时间）
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright

from src.ai_handler import download_all_images, get_ai_analysis, send_ntfy_notification
from src.collectors.contract import validate_item_record
from src.collectors.platforms import PLATFORM_YOUPIN
from src.config import SKIP_AI_ANALYSIS, RUN_HEADLESS
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

platform_id = PLATFORM_YOUPIN

MARKET_URL = "https://www.youpin898.com/market?activeKey=10"
API_BASE = "https://pc-api.youpin898.com/api/homepage/pc/goods/market"
GOODS_LINK = "https://www.youpin898.com/goodInfo?id={commodity_no}"
MAX_TEMPLATES = 3       # 每任务最多展开的模板数
ONSALE_PAGE_SIZE = 20   # 每模板取低价在售条数

_ANTIDETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
window.chrome = {runtime: {}, loadTimes: function() {}, csi: function() {}};
Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5});
"""

def _parse_price(text) -> str:
    try:
        return f"¥{float(str(text)):.2f}"
    except (TypeError, ValueError):
        return "价格异常"


def _fmt_publish_time(value) -> str:
    text = str(value or "")
    return text[:19].replace("T", " ") if text else "未知时间"


def _build_item_data(item: dict, template: dict) -> dict:
    """把在售单品 + 模板信息映射为商品契约字段。"""
    images = []
    for key in ("iconUrlLarge", "iconUrl"):
        url = str(item.get(key) or template.get(key) or "").strip()
        if url:
            images = [url]
            break

    abrade = str(item.get("abrade") or "")
    tags = []
    type_name = str(item.get("typeName") or "").strip()
    if type_name:
        tags.append(type_name)
    if item.get("haveSticker"):
        tags.append("含贴纸")
    if item.get("haveNameTag"):
        tags.append("含铭牌")

    return {
        "商品标题": str(item.get("commodityName") or template.get("commodityName") or "未知饰品"),
        "当前售价": _parse_price(item.get("price")),
        "商品原价": _parse_price(template.get("steamPrice")) if template.get("steamPrice") else "暂无",
        "“想要”人数": "NaN",
        "商品标签": tags,
        "发货地区": "悠悠有品平台",
        "卖家昵称": f"用户{item.get('userId', '')}",
        "商品链接": GOODS_LINK.format(commodity_no=item.get("commodityNo") or item.get("id")),
        "发布时间": _fmt_publish_time(item.get("publishTime")),
        "商品ID": str(item.get("commodityNo") or item.get("id") or ""),
        "商品图片列表": images,
        "商品主图链接": images[0] if images else "",
        "浏览量": "-",
        # 饰品特有信息（供 AI 判断与展示）
        "磨损值": abrade[:8],
        "模板英文名": str(item.get("commodityHashName") or template.get("commodityHashName") or ""),
        "模板ID": str(item.get("templateId") or template.get("id") or ""),
        "图案编号": str(item.get("paintSeed") or ""),
        "Steam参考价": _parse_price(template.get("steamPrice")) if template.get("steamPrice") else "",
    }


def _template_payload(keyword: str) -> dict:
    return {
        "listSortType": 0,
        "sortType": 0,
        "keyWords": keyword,
        "pageSize": 20,
        "pageIndex": 1,
    }


def _onsale_payload(template_id, page_index: int = 1) -> dict:
    return {
        "gameId": "730",
        "listType": "10",
        "templateId": str(template_id) if not isinstance(template_id, int) else template_id,
        "listSortType": 1,   # 价格升序（低价优先）
        "sortType": 0,
        "pageIndex": page_index,
        "pageSize": ONSALE_PAGE_SIZE,
    }


def _extract_data(resp: Optional[dict]) -> list:
    if not isinstance(resp, dict):
        return []
    data = resp.get("Data") if "Data" in resp else resp.get("data")
    return data if isinstance(data, list) else []


def _ai_concurrency() -> int:
    import os

    try:
        return max(1, int(os.getenv("AI_ANALYSIS_CONCURRENCY", "2")))
    except ValueError:
        return 2


async def collect(task_config: dict, debug_limit: int = 0) -> int:
    """执行一次悠悠有品采集，返回本次处理的新商品数。

    监听 + UI 导航方案（不伪造签名）：市场页 UI 搜索拿模板响应；
    每个模板导航到在售列表页拿单品响应——全部使用页面真实请求。
    """
    keyword = task_config["keyword"]
    task_name = task_config.get("task_name", "Untitled Task")
    min_price = task_config.get("min_price")
    max_price = task_config.get("max_price")
    ai_prompt_text = task_config.get("ai_prompt_text", "")
    analyze_images = bool(task_config.get("analyze_images", True))
    decision_mode = str(task_config.get("decision_mode", "ai")).strip().lower()
    if decision_mode not in {"ai", "keyword"}:
        decision_mode = "ai"
    keyword_rules = task_config.get("keyword_rules") or []

    def _price_in_range(price_text: str) -> bool:
        try:
            value = float(str(price_text).replace("¥", ""))
        except (TypeError, ValueError):
            return True
        if min_price and str(min_price).strip() and value < float(min_price):
            return False
        if max_price and str(max_price).strip() and value > float(max_price):
            return False
        return True

    platform = PLATFORM_YOUPIN
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
    template_responses: list[dict] = []
    onsale_responses: dict[str, list[dict]] = {}

    async with async_playwright() as pw:
        chromium = await pw.chromium.launch(
            headless=RUN_HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await chromium.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        await context.add_init_script(_ANTIDETECT_SCRIPT)
        page = await context.new_page()

        async def _on_response(resp):
            url = resp.url
            try:
                if "querySaleTemplate" in url:
                    body = await resp.json()
                    if _extract_data(body):
                        template_responses.append(body)
                elif "queryOnSaleCommodityList" in url:
                    body = await resp.json()
                    items = _extract_data(body)
                    if items and items[0].get("templateId") is not None:
                        onsale_responses[str(items[0]["templateId"])] = items
            except Exception:
                pass

        page.on("response", lambda r: asyncio.ensure_future(_on_response(r)))

        log_time(f"[悠悠] 打开市场页并搜索「{keyword}」…")
        await page.goto(MARKET_URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(4000)

        # UI 搜索（页面真实请求带全套签名头）
        searched = False
        inputs = page.locator("input")
        for i in range(min(await inputs.count(), 6)):
            inp = inputs.nth(i)
            ph = (await inp.get_attribute("placeholder")) or ""
            if "名称" in ph or "搜索" in ph or "饰品" in ph:
                await inp.click()
                await inp.fill(keyword)
                await page.keyboard.press("Enter")
                searched = True
                break
        if not searched:
            print("   [悠悠] 未找到搜索框。")
            return 0
        await page.wait_for_timeout(8000)

        # 从带关键词的那次响应取模板（后出现的优先）
        templates: list[dict] = []
        for resp in reversed(template_responses):
            templates = _extract_data(resp)
            if templates:
                break
        templates = templates[:MAX_TEMPLATES]
        if not templates:
            print(f"   [悠悠] 关键词「{keyword}」未找到饰品模板。")
            return 0
        print(f"   [悠悠] 命中 {len(templates)} 个模板："
              + "、".join(str(t.get("commodityName"))[:20] for t in templates))

        # 逐模板导航到在售列表页（真实路由自动加载在售单品）
        for template in templates:
            tid = template.get("id")
            await page.goto(
                f"https://www.youpin898.com/market/goods-list?listType=10&templateId={tid}&gameId=730",
                wait_until="networkidle",
                timeout=60000,
            )
            await page.wait_for_timeout(5000)
            await random_sleep(1, 2)

        # 汇总在售单品 → 契约 → 分析
        for template in templates:
            tid = str(template.get("id"))
            onsale = onsale_responses.get(tid) or []
            if not onsale:
                print(f"   [悠悠] 模板 {template.get('commodityName')} 未取到在售列表。")
                continue

            page_items = [_build_item_data(item, template) for item in onsale]
            page_items = [it for it in page_items if _price_in_range(it["当前售价"])]

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
                    print(f"   [悠悠] 商品记录未通过契约校验，跳过: {problems}")
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

        await dispatcher.join()

    return processed_count
