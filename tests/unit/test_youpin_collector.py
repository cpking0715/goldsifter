"""悠悠有品采集器解析与契约测试。"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from src.collectors.youpin import (
    _build_item_data,
    _extract_data,
    _fmt_publish_time,
    _onsale_payload,
    _parse_price,
    _template_payload,
)
from src.collectors.contract import validate_item_record


@pytest.fixture()
def sample() -> dict:
    path = Path(__file__).parent.parent / "fixtures" / "youpin_api_sample.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_template_search_payload_has_keyword():
    payload = _template_payload("AK-47 二西莫夫")
    assert payload["keyWords"] == "AK-47 二西莫夫"
    assert payload["pageSize"] == 20


def test_onsale_payload_sorted_by_price_asc():
    payload = _onsale_payload(51329)
    assert payload["templateId"] == 51329
    assert payload["listSortType"] == 1
    assert payload["pageSize"] == 20


def test_extract_data_handles_both_casings():
    assert _extract_data({"Data": [1, 2]}) == [1, 2]
    assert _extract_data({"data": [3]}) == [3]
    assert _extract_data({"Code": 1}) == []
    assert _extract_data(None) == []


def test_parse_price_and_time():
    assert _parse_price("824.99") == "¥824.99"
    assert _parse_price(None) == "价格异常"
    assert _fmt_publish_time("2026-11-04T03:03:27.985+00:00") == "2026-11-04 03:03:27"
    assert _fmt_publish_time(None) == "未知时间"


def test_build_item_data_satisfies_contract():
    item = {
        "id": 2094472829,
        "userId": 201436,
        "commodityNo": "2094472829",
        "commodityName": "专业手套（★） | 老虎精英 (久经沙场)",
        "templateId": 51329,
        "iconUrl": "https://youpin.img898.com/csgo/template/8076c86e93f94a1f87880eda252b33fc.png",
        "iconUrlLarge": "https://youpin.img898.com/csgo/template/9acc3bf18f2042dd87713146d73be194.png",
        "price": "824.99",
        "publishTime": "2026-11-04T03:03:27.985+00:00",
        "typeName": "手套",
        "commodityHashName": "★ Specialist Gloves | Tiger Strike (Field-Tested)",
        "abrade": "0.3696036338806152300",
        "paintSeed": 995,
    }
    template = {
        "id": 51329,
        "commodityName": "专业手套（★） | 老虎精英 (久经沙场)",
        "commodityHashName": "★ Specialist Gloves | Tiger Strike (Field-Tested)",
        "steamPrice": "1110.59",
    }
    data = _build_item_data(item, template)
    assert data["当前售价"] == "¥824.99"
    assert data["商品ID"] == "2094472829"
    assert data["商品链接"] == "https://www.youpin898.com/goodInfo?id=2094472829"
    assert data["磨损值"] == "0.369603"
    assert "手套" in data["商品标签"]

    record = {
        "爬取时间": datetime.now().isoformat(),
        "搜索关键字": "老虎精英",
        "任务名称": "test",
        "商品信息": data,
        "卖家信息": {},
        "来源平台": "youpin",
    }
    ok, problems = validate_item_record(record)
    assert ok, problems


def test_fixture_template_response_parseable(sample):
    """模板接口真实响应可解析且含价格字段。"""
    body = json.loads(sample["template_response"])
    templates = _extract_data(body)
    assert templates, "fixture 模板列表为空"
    first = templates[0]
    assert first.get("price")
    assert first.get("commodityName")
