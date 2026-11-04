"""
行情数据路由（Pro 功能）：代理轻服务端的众包行情聚合。

行情数据来自全体客户端匿名回传的价格快照——单个用户看不到的
跨用户大样本，是 Pro 的核心增值之一。
"""
from fastapi import APIRouter, HTTPException, Query

from src.services import cloud_service, license_gate

router = APIRouter(prefix="/api/market", tags=["market"])


def _require_pro() -> None:
    if not license_gate.is_pro_licensed():
        raise HTTPException(
            status_code=403,
            detail="行情数据为 Pro 功能：激活授权后可查看全网众包价格行情。",
        )


@router.get("/keywords")
async def market_keywords(limit: int = Query(default=50, ge=1, le=200)):
    """行情覆盖的关键词列表（全网样本量排序）。"""
    _require_pro()
    data = await cloud_service.fetch_json(
        f"{cloud_service.get_cloud_base_url()}/api/v1/market/keywords?limit={limit}"
    )
    if data is None:
        raise HTTPException(status_code=502, detail="云端行情服务不可达")
    return data


@router.get("/summary")
async def market_summary(platform: str = Query(default=""), keyword: str = Query(..., min_length=1)):
    """单个关键词的全网行情详情（最新概览 + 30 天日趋势）。"""
    _require_pro()
    from urllib.parse import quote

    url = (
        f"{cloud_service.get_cloud_base_url()}/api/v1/market/summary"
        f"?keyword={quote(keyword)}&platform={quote(platform)}"
    )
    data = await cloud_service.fetch_json(url)
    if data is None:
        raise HTTPException(status_code=502, detail="云端行情服务不可达")
    return data
