"""
采集层商品记录契约。

所有平台的 collector 最终产出的商品记录必须满足本契约；
下游（AI 分析 / 存储 / 通知 / 结果页）只依赖这些键名，与具体平台解耦。
新增平台时：采集器输出必须通过 validate_item_record，契约字段只增不删。
"""
from __future__ import annotations

# 商品信息（record["商品信息"]）中下游强依赖的字段
REQUIRED_ITEM_FIELDS: tuple[str, ...] = (
    "商品标题",
    "当前售价",
    "商品链接",
    "商品ID",
)

# 建议提供的字段（缺失不报错，但会降低 AI 判断与展示质量）
RECOMMENDED_ITEM_FIELDS: tuple[str, ...] = (
    "商品图片列表",
    "商品主图链接",
    "发布时间",
    "发货地区",
    "卖家昵称",
    "商品标签",
    "商品原价",
)

# 记录顶层必须存在的字段
REQUIRED_RECORD_FIELDS: tuple[str, ...] = (
    "爬取时间",
    "搜索关键字",
    "任务名称",
    "商品信息",
    "来源平台",
)


def validate_item_record(record: dict) -> tuple[bool, list[str]]:
    """
    校验一条商品记录是否满足契约。

    Returns:
        (是否合法, 缺失字段列表)。缺失字段用 "顶层.字段" / "商品信息.字段" 标注。
    """
    problems: list[str] = []

    if not isinstance(record, dict):
        return False, ["记录不是 dict"]

    for field in REQUIRED_RECORD_FIELDS:
        if field not in record:
            problems.append(field)

    item = record.get("商品信息")
    if not isinstance(item, dict):
        problems.append("商品信息")
        return False, problems

    for field in REQUIRED_ITEM_FIELDS:
        value = item.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"商品信息.{field}")

    return (not problems), problems


def missing_recommended_fields(record: dict) -> list[str]:
    """返回缺失的建议字段（用于采集器自检与调试日志）。"""
    item = record.get("商品信息") if isinstance(record, dict) else None
    if not isinstance(item, dict):
        return list(RECOMMENDED_ITEM_FIELDS)
    return [f for f in RECOMMENDED_ITEM_FIELDS if not item.get(f)]


def describe_contract() -> dict:
    """返回契约描述，供文档化与测试使用。"""
    return {
        "required_record_fields": list(REQUIRED_RECORD_FIELDS),
        "required_item_fields": list(REQUIRED_ITEM_FIELDS),
        "recommended_item_fields": list(RECOMMENDED_ITEM_FIELDS),
    }
