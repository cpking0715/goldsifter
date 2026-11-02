import asyncio
from datetime import datetime

from src.collectors.contract import validate_item_record
from src.collectors.kongfz import _build_item_data
from src.parsers import _parse_search_results_json


def _wrap(item: dict, platform: str, keyword: str = "测试") -> dict:
    return {
        "爬取时间": datetime.now().isoformat(),
        "搜索关键字": keyword,
        "任务名称": "契约测试",
        "商品信息": item,
        "卖家信息": {},
        "来源平台": platform,
    }


def test_xianyu_fixture_satisfies_contract(load_json_fixture):
    items = asyncio.run(
        _parse_search_results_json(load_json_fixture("search_results.json"), "fixture")
    )
    assert items
    ok, problems = validate_item_record(_wrap(items[0], "xianyu"))
    assert ok, problems
    assert items[0]["商品标题"] == "Sony A7M4 Body"
    assert items[0]["商品链接"].startswith("https://www.goofish.com/")


def test_kongfz_fixture_satisfies_contract(load_json_fixture):
    item = _build_item_data(load_json_fixture("kongfz_item.json"))
    record = _wrap(item, "kongfz", keyword="红楼梦")
    ok, problems = validate_item_record(record)
    assert ok, problems
    assert item["商品ID"] == "88001"
    assert item["商品链接"] == "https://book.kongfz.com/item/88001"
    assert "品相:九品" in item["商品标签"]
    assert record["来源平台"] == "kongfz"


def test_contract_rejects_blank_identity_fields():
    item = {
        "商品标题": "有标题",
        "当前售价": "¥1",
        "商品链接": "https://example.com/item/1",
        "商品ID": "   ",
    }
    ok, problems = validate_item_record(_wrap(item, "kongfz"))
    assert ok is False
    assert "商品信息.商品ID" in problems

    incomplete = _wrap(item, "xianyu")
    incomplete.pop("来源平台")
    ok, problems = validate_item_record(incomplete)
    assert ok is False
    assert "来源平台" in problems
