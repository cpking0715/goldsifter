"""
云服务路由（License / 行情回传 / 更新检查）——对接千淘轻服务端。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.services import cloud_service

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


class LicenseActivateRequest(BaseModel):
    key: str = Field(min_length=8, max_length=32)


class TelemetryToggleRequest(BaseModel):
    enabled: bool


@router.get("/status")
async def cloud_status():
    """云服务状态：设备标识、License 缓存、回传开关、云端连通性。"""
    reachable = False
    try:
        import httpx

        async with cloud_service._http_client() as client:
            resp = await client.get(f"{cloud_service.get_cloud_base_url()}/health", timeout=5.0)
            reachable = resp.status_code == 200
    except Exception:
        reachable = False
    return {
        "server_url": cloud_service.get_cloud_base_url(),
        "server_reachable": reachable,
        "device_id": cloud_service.get_device_id(),
        "app_version": cloud_service.APP_VERSION,
        "license": cloud_service.get_cached_license() or None,
        "telemetry": {
            "enabled": cloud_service.is_telemetry_enabled(),
            "state": cloud_service._read_json(cloud_service._telemetry_state_file(), {}),
        },
    }


@router.post("/license/activate")
async def license_activate(req: LicenseActivateRequest):
    """激活 License。"""
    try:
        result = await cloud_service.activate_license(req.key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"云端激活失败：{exc}")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason") or "激活失败")
    return {"message": "激活成功", "license": cloud_service.get_cached_license()}


@router.post("/license/verify")
async def license_verify():
    """校验 License（含离线宽限判定）。"""
    return await cloud_service.verify_license()


@router.put("/telemetry")
async def telemetry_toggle(req: TelemetryToggleRequest):
    """开关匿名行情回传。"""
    enabled = cloud_service.set_telemetry_enabled(req.enabled)
    return {"message": "已开启匿名行情回传" if enabled else "已关闭匿名行情回传", "enabled": enabled}


@router.post("/telemetry/flush")
async def telemetry_flush():
    """立即上传一批行情快照。"""
    if not cloud_service.is_telemetry_enabled():
        raise HTTPException(status_code=400, detail="行情回传已关闭")
    uploaded = await cloud_service.run_telemetry_once()
    return {"uploaded": uploaded}


@router.post("/update-check")
async def update_check():
    """检查客户端更新。"""
    return await cloud_service.check_update()
