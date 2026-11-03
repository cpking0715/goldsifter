"""
千淘 Windows 客户端打包脚本（绿色版目录 + 可选 Inno Setup 安装包）。

产物结构（build/Qiantao/）：
  runtime/            嵌入式 Python（免装环境）
  site-packages/      依赖
  chromium/           Playwright Chromium（--with-deps 的系统库由目标机自带或补装）
  app/                应用代码（src/ spider_v2.py desktop_tray.py dist/ prompts/ ca/ …）
  data/               用户数据（升级保留）
  启动千淘.bat         托盘启动（无控制台窗口）
  首次检查环境.bat     诊断脚本（缺 DLL/端口占用时用）

用法：
  python scripts/make_dist.py              # 完整构建
  python scripts/make_dist.py --skip-deps  # 跳过依赖安装（迭代打包）

说明：
- Chromium 优先复制本机 %LOCALAPPDATA%/ms-playwright（离线），否则联网安装。
- Inno Setup 编译：安装 Inno Setup 后用 installer/qiantao.iss 出安装包（可选）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "build" / "Qiantao"
PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.13.1/python-3.13.1-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"

LAUNCHER_BAT = """@echo off
chcp 65001 >nul
set PYTHONPATH=
set PLAYWRIGHT_BROWSERS_PATH=%~dp0chromium
set QT_CLOUD_CA_FILE=%~dp0app\\ca\\qiantao-cloud-root.crt
set QT_TELEMETRY_ENABLED=true
cd /d "%~dp0app"
start "" "%~dp0runtime\\pythonw.exe" desktop_tray.py --port 8000
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8000"
"""

DIAG_BAT = """@echo off
chcp 65001 >nul
echo === 千淘环境自检 ===
cd /d "%~dp0app"
"%~dp0runtime\\python.exe" -c "import fastapi, playwright, pystray; print('依赖 OK')"
if errorlevel 1 (echo 依赖缺失，请联系支持) else (echo 依赖 OK)
"%~dp0runtime\\python.exe" -c "import sys; sys.exit(0)"
netstat -ano | findstr :8000 >nul && (echo 端口 8000 已被占用：可能千淘已在运行) || (echo 端口 8000 可用)
pause
"""


def log(msg: str) -> None:
    print(f"[打包] {msg}", flush=True)


def download(url: str, dest: Path) -> None:
    if dest.exists():
        log(f"已存在，跳过下载: {dest.name}")
        return
    log(f"下载 {url}")
    urllib.request.urlretrieve(url, dest)


def build_runtime() -> None:
    runtime = BUILD / "runtime"
    if (runtime / "python.exe").exists():
        log("runtime 已就绪")
        return
    archive = REPO / "build" / "python-embed.zip"
    download(PYTHON_EMBED_URL, archive)
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(runtime)
    # 解锁 site-packages：把 import site 加回 ._pth
    pth = runtime / "python313._pth"
    if pth.exists():
        lines = pth.read_text(encoding="utf-8").splitlines()
        lines = ["import site"] + [l for l in lines if l != "import site"]
        # ._pth 模式忽略脚本目录：显式加入同级 app 目录（应用代码根）
        if "..\\app" not in lines:
            lines.append("..\\app")
        pth.write_text("\n".join(lines), encoding="utf-8")
    get_pip = runtime / "get-pip.py"
    download(GET_PIP_URL, get_pip)
    subprocess.run(
        [str(runtime / "python.exe"), str(get_pip), "-i", PIP_INDEX, "--no-warn-script-location"],
        check=True, cwd=runtime,
    )
    log("runtime 构建完成")


def install_deps() -> None:
    runtime = BUILD / "runtime"
    log("安装依赖（首次较慢）")
    subprocess.run(
        [
            str(runtime / "python.exe"), "-m", "pip", "install", "-i", PIP_INDEX,
            "--no-warn-script-location",
            "fastapi", "uvicorn[standard]", "pydantic-settings", "python-dotenv",
            "playwright", "requests", "openai", "httpx[socks]", "python-socks",
            "apscheduler", "aiofiles", "Pillow", "pyzbar", "qrcode", "jinja2", "pystray",
        ],
        check=True,
    )


def copy_chromium() -> None:
    dest = BUILD / "chromium"
    if dest.exists() and any(dest.iterdir()):
        log("chromium 已就绪")
        return
    local_root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if local_root.exists():
        all_names = [p.name for p in local_root.iterdir() if p.name.startswith(("chromium", "ffmpeg"))]
        # 只保留最高版本的 chromium/headless_shell（旧版本会撑爆安装包）+ ffmpeg
        top = max(
            (n.rsplit("-", 1)[-1] for n in all_names if n.startswith("chromium-")),
            default="",
        )
        names = [n for n in all_names if n.rsplit("-", 1)[-1] == top or n.startswith("ffmpeg")]
        if names:
            dest.mkdir(parents=True, exist_ok=True)
            for name in names:
                src = local_root / name
                log(f"复制本机浏览器: {name}")
                shutil.copytree(src, dest / name, dirs_exist_ok=True)
            return
    log("本机无 Playwright 浏览器，联网安装 chromium")
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(dest))
    subprocess.run(
        [str(BUILD / "runtime" / "python.exe"), "-m", "playwright", "install", "chromium"],
        check=True, env=env,
    )


def copy_app() -> None:
    app = BUILD / "app"
    if app.exists():
        shutil.rmtree(app)
    app.mkdir(parents=True)
    for item in ["src", "spider_v2.py", "desktop_tray.py", "prompts", "ca", "chrome-extension", "static"]:
        src = REPO / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, app / item, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, app / item)
    (app / "dist").mkdir(exist_ok=True)
    web_dist = REPO / "dist"
    if web_dist.exists():
        shutil.copytree(web_dist, app / "dist", dirs_exist_ok=True)
    else:
        log("警告：前端 dist/ 不存在，请先 cd web-ui && npm run build")
    docs = BUILD / "app" / "docs"
    docs.mkdir(exist_ok=True)
    for f in ["AI-SETUP.md", "DEV-SPEC.md"]:
        if (REPO / "docs" / f).exists():
            shutil.copy2(REPO / "docs" / f, docs / f)
    (BUILD / "app" / ".env.example").exists() or shutil.copy2(REPO / ".env.example", app / ".env.example")
    log("app 复制完成")


def write_launchers() -> None:
    (BUILD / "启动千淘.bat").write_text(LAUNCHER_BAT, encoding="utf-8")
    (BUILD / "环境自检.bat").write_text(DIAG_BAT, encoding="utf-8")
    # 生成 ico（Inno/快捷方式用）
    try:
        from PIL import Image

        png = REPO / "docs" / "logo.png"
        if png.exists():
            img = Image.open(png)
            ico = BUILD / "qiantao.ico"
            img.save(ico, sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
            log(f"图标: {ico.name}")
    except Exception as exc:  # noqa: BLE001 - 图标失败不阻塞打包
        log(f"图标生成跳过: {exc}")


def make_portable_zip() -> None:
    log("生成绿色版压缩包")
    shutil.make_archive(str(BUILD.parent / "Qiantao-portable"), "zip", root_dir=BUILD.parent, base_dir=BUILD.name)
    log(f"产物: build/Qiantao-portable.zip")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-deps", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()

    BUILD.mkdir(parents=True, exist_ok=True)
    build_runtime()
    if not args.skip_deps:
        install_deps()
    copy_chromium()
    copy_app()
    write_launchers()
    if not args.no_zip:
        make_portable_zip()
    log(f"构建完成: {BUILD}")


if __name__ == "__main__":
    main()
