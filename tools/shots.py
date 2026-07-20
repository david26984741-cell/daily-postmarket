#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日報告用截圖 — 只負責「股期主力增減排行」一張。

  5_股期主力增減.png   rank.html 的四宮格區塊 (增加/減少 口數 + 金額)

其餘四張(外資/自營選擇權、外資期現貨、大額交易人期貨)已改由 tools/charts.py
直接讀 data/*.json 自己畫, 不再截網頁 — 不受版面限制、也不必等部署。

作法:在 runner 本機起 http server 直接讀 repo 內的檔案 → headless Chromium 截圖,
不依賴 GitHub Pages 是否已部署完成 (快且不會截到舊版)。

注意:
  - 輸出目錄預設 .shots/ (已列入 .gitignore) — 本 repo 公開, 圖片一律不進版控。
  - 中文字型:runner 需先裝 fonts-noto-cjk, 否則全部變成豆腐方塊。
  - 只截 .rank-grid 這個元素, 不含頁首/說明/工具列。

用法: python tools/shots.py [--out .shots]
"""
import os, sys, time, argparse, threading, functools, http.server, socketserver

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANK_SHOT = ("5_股期主力增減", "rank.html", ".rank-grid")


def serve(root, port_holder, stop):
    """背景起一個只讀的 http server (綁 127.0.0.1, 隨機埠)。"""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    handler.log_message = lambda *a, **k: None
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port_holder.append(httpd.server_address[1])
        while not stop.is_set():
            httpd.handle_request()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(BASE, ".shots"))
    a = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("需要 playwright:  pip install playwright && playwright install chromium")
        return 1

    os.makedirs(a.out, exist_ok=True)
    port_holder, stop = [], threading.Event()
    threading.Thread(target=serve, args=(BASE, port_holder, stop), daemon=True).start()
    for _ in range(50):
        if port_holder:
            break
        time.sleep(0.1)
    if not port_holder:
        print("本機 http server 啟動失敗")
        return 1
    origin = f"http://127.0.0.1:{port_holder[0]}"
    print(f"本機站台: {origin}")

    fname, path, sel = RANK_SHOT
    out = os.path.join(a.out, fname + ".png")
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        # 寬度要夠, 四宮格才會是 2 欄 (rank.html 在 900px 以下會塌成 1 欄)
        page = browser.new_page(viewport={"width": 1500, "height": 1400},
                                device_scale_factor=2)   # 2x = 文字銳利
        url = f"{origin}/{path}"
        print(f"截圖 {fname} … {url}  (只截 {sel})")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_selector(f"{sel} table tr", timeout=30000)
        page.wait_for_timeout(800)
        page.locator(sel).screenshot(path=out)
        browser.close()

    stop.set()
    print(f"完成: {out}  ({os.path.getsize(out)//1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
