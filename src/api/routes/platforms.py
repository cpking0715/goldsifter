"""
采集平台元数据路由
供前端任务表单动态渲染平台选择器与筛选能力
"""
from fastapi import APIRouter

from src.collectors.platforms import list_platforms

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("", response_model=list)
async def get_platforms():
    """获取全部已注册采集平台及其筛选能力声明"""
    return [
        {
            "platform_id": info.platform_id,
            "display_name": info.display_name,
            "capabilities": {
                "price_range": info.capabilities.price_range,
                "personal_only": info.capabilities.personal_only,
                "free_shipping": info.capabilities.free_shipping,
                "new_publish_option": info.capabilities.new_publish_option,
                "region": info.capabilities.region,
                "requires_login_state": info.capabilities.requires_login_state,
                "seller_profile": info.capabilities.seller_profile,
            },
        }
        for info in list_platforms()
    ]
