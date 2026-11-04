"""eBay 采集器解析与契约测试。"""
from pathlib import Path

import pytest

from src.collectors.ebay import _extract_item_id, _parse_price, parse_search_html
from src.collectors.contract import validate_item_record


@pytest.fixture()
def ebay_html() -> str:
    return (Path(__file__).parent.parent / "fixtures" / "ebay_search.html").read_text(encoding="utf-8")


def test_parse_ebay_search_filters_placeholder(ebay_html):
    items = parse_search_html(ebay_html)
    # 占位卡 "Shop on eBay" 应被过滤，剩 2 个真实商品
    assert len(items) == 2
    titles = [i["商品标题"] for i in items]
    assert any("X100V Silver" in t for t in titles)


def test_parse_ebay_fields_and_contract(ebay_html):
    items = parse_search_html(ebay_html)
    first = items[0]
    assert first["当前售价"] == "$1,299.00"
    assert first["商品ID"] == "135298461234"
    assert first["商品链接"].startswith("https://www.ebay.com/itm/")
    assert first["成色"] == "Pre-owned"
    assert "Free shipping" in first["商品标签"]
    assert first["发货地区"] == "Japan"
    assert "camera_jp" in first["卖家昵称"]
    assert first["商品图片列表"] and first["商品主图链接"]

    # 满足商品契约
    record = {
        "爬取时间": "2026-11-04T00:00:00",
        "搜索关键字": "fuji x100v",
        "任务名称": "test",
        "商品信息": first,
        "卖家信息": {},
        "来源平台": "ebay",
    }
    ok, problems = validate_item_record(record)
    assert ok, problems


def test_parse_price_variants():
    assert _parse_price("$1,299.00") == "$1,299.00"
    assert _parse_price("US $99.99") == "$99.99"
    assert _parse_price("") == "价格异常"


def test_extract_item_id_variants():
    assert _extract_item_id("https://www.ebay.com/itm/135298461234?hash=x") == "135298461234"
    assert _extract_item_id("https://www.ebay.com/itm/31-vintage-lens-99881/nav") == "99881"
    assert _extract_item_id("https://www.ebay.com/other") == ""
