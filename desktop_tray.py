"""
千淘 Windows 托盘启动器。

以后台服务方式启动 Web 管理台（uvicorn），并在系统托盘常驻：
- 双击托盘图标 / 菜单「打开管理台」→ 打开浏览器 http://127.0.0.1:8000
- 菜单「退出」→ 停止服务并退出

依赖 pystray（可选）：未安装或无桌面环境时自动退化为普通前台启动。
    pip install pystray

用法：
    python desktop_tray.py            # 托盘模式（默认 8000 端口）
    python desktop_tray.py --port 8000 --no-tray
"""
from __future__ import annotations

import argparse
import threading
import webbrowser


def build_tray_icon(port: int, stop_event: threading.Event, on_exit):
    """构造托盘图标；pystray 缺失时返回 None。"""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("提示: 未安装 pystray，退化为前台模式（pip install pystray 可启用托盘）")
        return None

    # 用产品 logo 的简化版做托盘图标（深底 + 金块）
    img = Image.new("RGBA", (64, 64), (15, 23, 42, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, 52, 52], outline=(226, 232, 240, 255), width=4)
    d.polygon([(32, 16), (46, 26), (44, 40), (32, 48), (20, 40), (18, 26)],
              fill=(251, 191, 36, 255))
    d.line([(46, 46), (58, 58)], fill=(217, 119, 6, 255), width=7)
    d.ellipse([54, 54, 62, 62], fill=(180, 83, 9, 255))

    url = f"http://127.0.0.1:{port}"

    def open_console(icon=None, item=None):
        webbrowser.open(url)

    def quit_app(icon=None, item=None):
        stop_event.set()
        if icon:
            icon.stop()
        on_exit()

    menu = pystray.Menu(
        pystray.MenuItem("打开管理台", open_console, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_app),
    )
    icon = pystray.Icon("qiantao", img, title=f"千淘 · http://127.0.0.1:{port}", menu=menu)
    return icon


def main() -> None:
    parser = argparse.ArgumentParser(description="千淘托盘启动器")
    parser.add_argument("--port", type=int, default=8000, help="Web 服务端口（默认 8000）")
    parser.add_argument("--no-tray", action="store_true", help="禁用托盘，前台运行")
    args = parser.parse_args()

    import uvicorn
    from src.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="info")
    server = uvicorn.Server(config)

    serve_thread = threading.Thread(target=server.run, daemon=True)
    serve_thread.start()

    stop_event = threading.Event()
    if not args.no_tray:
        icon = build_tray_icon(args.port, stop_event, on_exit=server.should_exit)
        if icon is not None:
            webbrowser.open(f"http://127.0.0.1:{args.port}")
            icon.run()  # 阻塞直到托盘退出
            return

    print(f"千淘管理台运行中: http://127.0.0.1:{args.port}（Ctrl+C 退出）")
    try:
        serve_thread.join()
    except KeyboardInterrupt:
        server.should_exit = True


if __name__ == "__main__":
    main()
