#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日報告用截圖 — 產生 5 張 PNG,供 tools/report.py 以 email 附件寄出。

  1_外資選擇權.png      近5日表格 + 近六個月趨勢圖
  2_自營選擇權.png      同上
  3_外資期貨現貨.png    同上
  4_大額交易人期貨.png  同上
  5_股期主力增減.png    rank.html 整頁 (預設即 前十大 + 主力)

作法:在 runner 本機起 http server 直接讀 repo 內的檔案 → headless Chromium 截圖。
不依賴 GitHub Pages 是否已部署完成 (快且不會截到舊版)。

注意:
  - 輸出目錄預設 .shots/ (已列入 .gitignore) — 本 repo 公開, 圖片一律不進版控。
  - 中文字型:runner 需先裝 fonts-noto-cjk, 否則全部變成豆腐方塊。
  - 圖表用 detail.html 的 ?days=N 參數直接以 N 筆起繪, 不先畫全歷史再縮放 (快很多)。

用法: python tools/shots.py [--out .shots] [--days 120] [--rows 5]
"""
import os, sys, time, argparse, threading, functools, http.server, socketserver

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 近六個月 ≈ 120 個交易日 (一個月約 20 個交易日)
DEFAULT_DAYS = 120
DEFAULT_ROWS = 5

# (檔名, 頁面, 說明) — 前四張走 detail.html, 第五張是 rank.html 整頁
SHOTS = [
    ("1_外資選擇權",     "detail.html?cat=options_foreign",  "外資選擇權"),
    ("2_自營選擇權",     "detail.html?cat=options_dealer",   "自營選擇權"),
    ("3_外資期貨現貨",   "detail.html?cat=foreign_fut_spot", "外資期貨、現貨"),
    ("4_大額交易人期貨", "detail.html?cat=large_fut_txf",    "大額交易人期貨"),
]
RANK_SHOT = ("5_股期主力增減", "rank.html", "股票期貨 前十大主力增減")

# 截圖時要隱藏的區塊 (導覽、麵包屑、日期選擇器、當日明細卡片、頁尾)
HIDE = ["nav.main", ".crumbs", ".toolbar", "#detail", "footer"]


def serve(root, port_holder, stop):
    """在背景起一個只讀的 http server (綁 127.0.0.1, 隨機埠)。"""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    handler.log_message = lambda *a, **k: None          # 靜音, 不洗版 workflow log
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port_holder.append(httpd.server_address[1])
        while not stop.is_set():
            httpd.handle_request()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(BASE, ".shots"))
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    a = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("需要 playwright:  pip install playwright && playwright install chromium")
        return 1

    os.makedirs(a.out, exist_ok=True)

    port_holder, stop = [], threading.Event()
    t = threading.Thread(target=serve, args=(BASE, port_holder, stop), daemon=True)
    t.start()
    for _ in range(50):                                  # 等 server 拿到埠號
        if port_holder:
            break
        time.sleep(0.1)
    if not port_holder:
        print("本機 http server 啟動失敗")
        return 1
    origin = f"http://127.0.0.1:{port_holder[0]}"
    print(f"本機站台: {origin}")

    made = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": 1500, "height": 1400},
                                device_scale_factor=2)   # 2x = 文字銳利, email 放大也清楚

        # ---- 前四張: 分類明細 (近5日表格 + 近六個月趨勢圖) ----
        for fname, path, title in SHOTS:
            url = f"{origin}/{path}&days={a.days}"
            print(f"截圖 {fname} … {url}")
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_selector("#history canvas", timeout=30000)
            page.wait_for_selector("#history tbody tr", timeout=30000)
            page.wait_for_timeout(1200)                  # 等 Chart.js 畫完

            page.evaluate(
                """({hide, rows}) => {
                    document.querySelectorAll('#history tbody tr')
                        .forEach((tr, i) => { if (i >= rows) tr.remove(); });
                    hide.forEach(s => document.querySelectorAll(s)
                        .forEach(e => e.style.display = 'none'));
                }""",
                {"hide": HIDE, "rows": a.rows})
            page.wait_for_timeout(400)

            # 內容區是第 2 個 .wrap (第 1 個屬於頁首)
            target = page.locator(".wrap").nth(1)
            out = os.path.join(a.out, fname + ".png")
            target.screenshot(path=out)
            made.append(out)

        # ---- 第五張: 增減排行整頁 (預設已是 前十大 + 主力) ----
        fname, path, title = RANK_SHOT
        url = f"{origin}/{path}"
        print(f"截圖 {fname} … {url}")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_selector("#upLots table, #upLots tr", timeout=30000)
        page.wait_for_timeout(1000)
        out = os.path.join(a.out, fname + ".png")
        page.screenshot(path=out, full_page=True)
        made.append(out)

        browser.close()

    stop.set()
    print(f"\n完成 {len(made)} 張:")
    for m in made:
        print(f"  {m}  ({os.path.getsize(m)//1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
