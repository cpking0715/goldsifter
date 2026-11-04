"""
获取千淘轻服务端管理令牌（Admin Token）。

本地执行，经 SSH 从 tx-51 的 systemd 配置中取回令牌：
  python scripts/get_admin_token.py             # 显示 + 写入本地缓存（发放脚本可直接用）
  python scripts/get_admin_token.py --persist   # 额外写入当前用户环境变量 QT_ADMIN_TOKEN（永久）

前提：本机已配置 ubuntu-tx-51 的 SSH 免密（~/.ssh/config）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_HOST = "ubuntu-tx-51"
TOKEN_CACHE = Path(os.environ.get("TEMP", "/tmp")) / "qt_admin_token.txt"


def fetch_token(host: str) -> str:
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
        "sudo -n grep -h '^Environment=QT_ADMIN_TOKEN' /etc/systemd/system/qiantao-server.service | head -1 | cut -d= -f3",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        sys.exit(f"SSH 获取失败：{result.stderr.strip() or f'exit {result.returncode}'}（检查免密与 sudo -n 权限）")
    token = result.stdout.strip()
    if not token or " " in token:
        sys.exit(f"令牌解析异常：{token[:20]!r}")
    return token


def main() -> None:
    parser = argparse.ArgumentParser(description="获取轻服务端管理令牌")
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH 主机名（默认 ubuntu-tx-51）")
    parser.add_argument("--persist", action="store_true", help="同时写入用户环境变量 QT_ADMIN_TOKEN（永久，新开终端生效）")
    args = parser.parse_args()

    token = fetch_token(args.host)
    print(f"管理令牌：{token}")

    TOKEN_CACHE.write_text(token, encoding="utf-8")
    print(f"已写入本地缓存：{TOKEN_CACHE}（scripts/issue_license.py 自动读取）")

    if args.persist:
        r = subprocess.run(["setx", "QT_ADMIN_TOKEN", token], capture_output=True, text=True)
        if r.returncode == 0:
            print("已写入用户环境变量 QT_ADMIN_TOKEN（新开的终端生效）")
        else:
            print(f"setx 失败：{r.stderr.strip()}")
    print("\n用途：python scripts/issue_license.py --days 365 --devices 2")


if __name__ == "__main__":
    main()
