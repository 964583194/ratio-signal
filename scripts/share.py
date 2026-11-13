"""小红书分享图：用 share.html 渲染两张 3:4 竖图（1080×1440），放在 data/share/。
div.png 红利每日；week.png 每周总览。网页上的“生成分享图”按钮直接打开这两张图，长按保存。"""
import functools
import http.server
import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "share")


def run():
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    os.makedirs(OUT, exist_ok=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    h = functools.partial(Quiet, directory=ROOT)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    info = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 360, "height": 480}, device_scale_factor=3)
        for k in ("div", "week"):
            pg.goto(f"http://127.0.0.1:{port}/share.html?card={k}")
            pg.wait_for_selector("body[data-ready]", timeout=20000)
            pg.wait_for_timeout(300)
            pg.screenshot(path=os.path.join(OUT, f"{k}.png"), clip={"x": 0, "y": 0, "width": 360, "height": 480})
            info[k] = pg.evaluate("document.body.dataset.date || ''")
        b.close()
    srv.shutdown()
    with open(os.path.join(OUT, "info.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False)
    print("分享图：", info)


if __name__ == "__main__":
    run()
