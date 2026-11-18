"""小红书分享图：用 share.html 渲染两张 3:4 竖图（1080×1440），放在 data/share/。
div.png / div2.png 红利每日两张（今天买不买、近半个月怎么买）；week.png / wsum.png / wdiv.png / wrot.png 每周四张（本周这么做、周记总结、红利本周日记、创业板科创板离买点多远）。
info.json 里还有配套文案 cap_div / cap_week。网页上的“生成分享图”按钮打开图，长按保存，下面一键复制文案。"""
import functools
import http.server
import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "share")


def run(only=None):
    out = os.path.join(OUT, "live") if only else OUT     # 快速版单独放，不和完整更新抢同一个文件
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    os.makedirs(out, exist_ok=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    h = functools.partial(Quiet, directory=ROOT)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    info = {}
    if only:                                  # 盘中估算只重画每日图，其余沿用
        try:
            with open(os.path.join(out, "info.json"), encoding="utf-8") as fh:
                info = json.load(fh)
        except Exception:  # noqa: BLE001
            info = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 360, "height": 480}, device_scale_factor=3)
        for k in (only or ("div", "div2", "week", "wsum", "wdiv", "wrot")):
            pg.goto(f"http://127.0.0.1:{port}/share.html?card={k}")
            pg.wait_for_selector("body[data-ready]", timeout=20000)
            pg.wait_for_timeout(300)
            pg.screenshot(path=os.path.join(out, f"{k}.png"), clip={"x": 0, "y": 0, "width": 360, "height": 480})
            info[k] = pg.evaluate("document.body.dataset.date || ''")
            if k == "div":
                info["div_live"] = pg.evaluate("document.body.dataset.live || ''")   # 盘中估算的时间，正式版为空
            if k not in ("div", "week"):                                   # 周记 3 张图共用一段文案
                continue
            pg.goto(f"http://127.0.0.1:{port}/share.html?card=cap_{k}")      # 配套小红书文案
            pg.wait_for_selector("body[data-ready]", timeout=20000)
            info["cap_" + k] = pg.eval_on_selector("#cap", "e => e.textContent")
        b.close()
    srv.shutdown()
    with open(os.path.join(out, "info.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False)
    print("分享图：", info)


if __name__ == "__main__":
    import sys
    run(("div", "div2") if "--live" in sys.argv else None)
