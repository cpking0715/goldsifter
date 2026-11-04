"""
采集平台注册元数据。

仅存放轻量元数据（平台标识 / 展示名 / 筛选能力声明），
不引入任何重型依赖，API 进程与爬虫子进程都可安全导入。
"""
from __future__ import annotations

from dataclasses import dataclass

PLATFORM_XIANYU = "xianyu"
PLATFORM_KONGFZ = "kongfz"
PLATFORM_EBAY = "ebay"
PLATFORM_YOUPIN = "youpin"


@dataclass(frozen=True)
class PlatformCapabilities:
    """平台支持的筛选能力声明，用于任务表单动态显隐与启动前校验。"""

    price_range: bool = False
    personal_only: bool = False
    free_shipping: bool = False
    new_publish_option: bool = False
    region: bool = False
    # 是否需要登录态（state 文件）
    requires_login_state: bool = False
    # 是否支持卖家深度画像采集
    seller_profile: bool = False


@dataclass(frozen=True)
class PlatformInfo:
    platform_id: str
    display_name: str
    capabilities: PlatformCapabilities


_PLATFORMS: dict[str, PlatformInfo] = {
    PLATFORM_XIANYU: PlatformInfo(
        platform_id=PLATFORM_XIANYU,
        display_name="闲鱼",
        capabilities=PlatformCapabilities(
            price_range=True,
            personal_only=True,
            free_shipping=True,
            new_publish_option=True,
            region=True,
            requires_login_state=True,
            seller_profile=True,
        ),
    ),
    PLATFORM_KONGFZ: PlatformInfo(
        platform_id=PLATFORM_KONGFZ,
        display_name="孔夫子旧书网",
        capabilities=PlatformCapabilities(
            price_range=True,
        ),
    ),
    PLATFORM_EBAY: PlatformInfo(
        platform_id=PLATFORM_EBAY,
        display_name="eBay（需海外网络·Pro）",
        capabilities=PlatformCapabilities(
            price_range=True,
        ),
    ),
    PLATFORM_YOUPIN: PlatformInfo(
        platform_id=PLATFORM_YOUPIN,
        display_name="悠悠有品（游戏饰品·Pro）",
        capabilities=PlatformCapabilities(
            price_range=True,
        ),
    ),
}


def get_platform_info(platform: str | None) -> PlatformInfo:
    """获取平台元数据，未知平台抛 ValueError。"""
    key = str(platform or "").strip().lower()
    info = _PLATFORMS.get(key)
    if info is None:
        raise ValueError(f"未知采集平台: {platform}")
    return info


def normalize_platform(platform: str | None) -> str:
    """归一化平台标识；空值/未知值回退闲鱼（只用于读旧数据）。"""
    key = str(platform or "").strip().lower()
    return key if key in _PLATFORMS else PLATFORM_XIANYU


def require_platform(platform: str | None) -> str:
    """校验并归一化调用方显式传入的平台；未知值拒绝，避免静默写成闲鱼。"""
    key = str(platform or "").strip().lower()
    if key not in _PLATFORMS:
        known = ", ".join(sorted(_PLATFORMS))
        raise ValueError(f"未知采集平台: {platform}（可选: {known}）")
    return key


def list_platforms() -> list[PlatformInfo]:
    return list(_PLATFORMS.values())


def platform_requires_login(platform: str | None) -> bool:
    return get_platform_info(normalize_platform(platform)).capabilities.requires_login_state
