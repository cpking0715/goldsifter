"""
千淘 License 发放工具（仅产品方使用）。

用法：
  # 发 1 个 Pro key：3 台设备、365 天
  python scripts/issue_license.py --days 365 --devices 3

  # 批量发 5 个
  python scripts/issue_license.py --n 5 --days 365 --devices 2 --note "首发内测"

  # 永久 key
  python scripts/issue_license.py --devices 1

管理令牌来源（三选一，优先级从高到低）：
  --token 参数 > 环境变量 QT_ADMIN_TOKEN > 服务器上查看：
  sudo grep QT_ADMIN_TOKEN /etc/systemd/system/qiantao-server.service
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import ssl
from pathlib import Path

DEFAULT_BASE = "https://qiantao.qingmuxi.com:8790/qt"
CA_FILE = Path(__file__).resolve().parents[1] / "ca" / "qiantao-cloud-root.crt"


def issue(base_url: str, token: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base_url}/api/v1/admin/licenses",
        method="POST",
        data=json.dumps(payload).encode(),
        headers={"X-Admin-Token": token, "Content-Type": "application/json"},
    )
    context = ssl.create_default_context(cafile=str(CA_FILE)) if CA_FILE.exists() else None
    # 直连轻服务端（国内目标）：绕开本机代理劫持
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    resp = opener.open(req, timeout=15)
    return json.loads(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description="千淘 License 发放工具")
    parser.add_argument("--n", type=int, default=1, help="发放数量（默认 1）")
    parser.add_argument("--plan", default="pro", help="套餐标识（默认 pro）")
    parser.add_argument("--days", type=int, default=None, help="有效天数（缺省=永久）")
    parser.add_argument("--devices", type=int, default=2, help="可绑定设备数（默认 2）")
    parser.add_argument("--note", default="", help="备注（发给谁/什么活动）")
    parser.add_argument("--base", default=DEFAULT_BASE, help="轻服务端地址")
    parser.add_argument("--token", default="", help="管理令牌（缺省读 QT_ADMIN_TOKEN）")
    args = parser.parse_args()

    token = args.token or os.getenv("QT_ADMIN_TOKEN", "").strip()
    if not token:
        # 兼容：本机开发环境留存的令牌文件
        local = Path(os.getenv("TEMP", "/tmp")) / "qt_admin_token.txt"
        if local.exists():
            token = local.read_text(encoding="utf-8").strip()
    if not token:
        sys.exit("缺少管理令牌：--token 或环境变量 QT_ADMIN_TOKEN，或在 tx-51 上查看 systemd 配置")

    print(f"发放 {args.n} 个 key（plan={args.plan}, 设备={args.devices}, "
          f"{'永久' if args.days is None else f'{args.days} 天'}）\n")
    keys = []
    for _ in range(max(1, args.n)):
        result = issue(args.base, token, {
            "plan": args.plan,
            "max_devices": args.devices,
            "valid_days": args.days,
            "note": args.note,
        })
        keys.append(result["key"])
        print(f"  {result['key']}  到期: {result['expires_at'] or '永久'}")
    print(f"\n共 {len(keys)} 个。客户激活路径：设置 → 云服务 → 授权 → 粘贴 key → 激活")


if __name__ == "__main__":
    main()
