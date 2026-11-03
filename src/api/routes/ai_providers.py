"""
AI 供应商预设路由：前端据此渲染供应商选择器与模型下拉。
"""
from fastapi import APIRouter

from src.services.ai_provider_presets import serialize_providers

router = APIRouter(prefix="/api/ai-providers", tags=["ai-providers"])


@router.get("", response_model=list)
async def list_ai_providers():
    """获取内置 AI 供应商预设（含模型列表、免费角标、Vision 支持与领 Key 入口）。"""
    return serialize_providers()
