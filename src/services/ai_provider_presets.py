"""
内置 AI 供应商预设清单。

只描述"预填信息"，不存任何密钥；免费角标信息以各供应商官网为准，
数据集中在此文件便于随官方政策更新。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPreset:
    name: str
    vision: bool = False          # 支持图片输入（千淘"看图识货"必需）
    badge: str = ""               # "" 无 / "free" 长期免费 / "free_quota" 有免费额度
    note: str = ""


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    display_name: str
    base_url: str
    models: tuple[ModelPreset, ...]
    key_url: str = ""             # 获取 API Key 的入口
    docs_url: str = ""
    note: str = ""
    recommended_text_model: str = ""  # 长文本（分析标准生成）推荐模型


PROVIDERS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        id="zhipu",
        display_name="智谱 AI（推荐·有免费 Vision 模型）",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=(
            ModelPreset("glm-4v-flash", vision=True, badge="free", note="免费·看图识货首选"),
            ModelPreset("glm-4-flash", vision=False, badge="free", note="免费·纯文本"),
            ModelPreset("glm-4v-plus", vision=True, note="付费·更强看图"),
            ModelPreset("glm-4-air", vision=False, note="付费·纯文本"),
        ),
        key_url="https://open.bigmodel.cn/usercenter/apikeys",
        docs_url="https://docs.bigmodel.cn/",
        note="注册即送额度；glm-4v-flash 长期免费，是国内直连的最省心方案。",
        recommended_text_model="glm-4-flash",
    ),
    ProviderPreset(
        id="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com",
        models=(
            ModelPreset("deepseek-chat", vision=False, note="便宜好用，但不支持看图"),
            ModelPreset("deepseek-reasoner", vision=False, note="推理型，不支持看图"),
        ),
        key_url="https://platform.deepseek.com/api_keys",
        docs_url="https://api-docs.deepseek.com/",
        note="无 Vision 模型：选 DeepSeek 时请在任务中关闭「图片分析」，AI 仅基于文字判断。",
    ),
    ProviderPreset(
        id="siliconflow",
        display_name="硅基流动 SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        models=(
            ModelPreset("Qwen/Qwen2.5-VL-32B-Instruct", vision=True, note="看图"),
            ModelPreset("THUDM/glm-4-9b-chat", vision=False, badge="free", note="免费小模型"),
            ModelPreset("deepseek-ai/DeepSeek-V3", vision=False, note="纯文本"),
        ),
        key_url="https://cloud.siliconflow.cn/account/ak",
        docs_url="https://docs.siliconflow.cn/",
        note="聚合平台，模型多；新用户有赠送额度。",
    ),
    ProviderPreset(
        id="modelscope",
        display_name="ModelScope 魔搭（新用户免费额度）",
        base_url="https://api-inference.modelscope.cn/v1",
        models=(
            ModelPreset("Qwen/Qwen2.5-VL-72B-Instruct", vision=True, badge="free_quota", note="看图·大模型"),
            ModelPreset("Qwen/Qwen2.5-72B-Instruct", vision=False, badge="free_quota", note="纯文本"),
        ),
        key_url="https://modelscope.cn/my/accesstokens",
        docs_url="https://modelscope.cn/docs/model-service/API-Inference/intro",
        note="阿里旗下，注册送免费额度，国内直连。",
    ),
    ProviderPreset(
        id="dashscope",
        display_name="阿里云百炼",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=(
            ModelPreset("qwen-vl-plus", vision=True, badge="free_quota", note="看图·有免费额度"),
            ModelPreset("qwen-vl-max", vision=True, note="看图·旗舰"),
            ModelPreset("qwen-turbo", vision=False, badge="free_quota", note="纯文本·便宜"),
        ),
        key_url="https://bailian.console.aliyun.com/",
        docs_url="https://help.aliyun.com/zh/model-studio/",
        note="需阿里云账号；新用户各模型有免费额度。",
    ),
    ProviderPreset(
        id="moonshot",
        display_name="月之暗面 Kimi",
        base_url="https://api.moonshot.cn/v1",
        models=(
            ModelPreset("moonshot-v1-8k-vision-preview", vision=True, note="看图"),
            ModelPreset("kimi-k2-0905-preview", vision=False, note="纯文本"),
        ),
        key_url="https://platform.moonshot.cn/console/api-keys",
        docs_url="https://platform.moonshot.cn/docs/",
    ),
    ProviderPreset(
        id="openai",
        display_name="OpenAI（需国际网络）",
        base_url="https://api.openai.com/v1",
        models=(
            ModelPreset("gpt-4o", vision=True),
            ModelPreset("gpt-4o-mini", vision=True, note="便宜"),
        ),
        key_url="https://platform.openai.com/api-keys",
        docs_url="https://platform.openai.com/docs",
        note="国内访问需代理；可在下方「代理地址」填写。",
    ),
    ProviderPreset(
        id="custom",
        display_name="自定义（任意 OpenAI 兼容服务）",
        base_url="",
        models=(),
        note="填 Base URL 与模型名；任何 OpenAI 兼容接口均可（OneAPI/NewAPI/本地 Ollama 等）。",
    ),
)


def serialize_providers() -> list[dict]:
    return [
        {
            "id": p.id,
            "display_name": p.display_name,
            "base_url": p.base_url,
            "key_url": p.key_url,
            "docs_url": p.docs_url,
            "note": p.note,
            "recommended_text_model": p.recommended_text_model,
            "models": [
                {"name": m.name, "vision": m.vision, "badge": m.badge, "note": m.note}
                for m in p.models
            ],
        }
        for p in PROVIDERS
    ]
