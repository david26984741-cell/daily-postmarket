#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日報告用截圖 — 負責「增減排行四宮格」四張。

  5_前十大_主力增減.png        前十大 · 主力      (原本就有的那張)
  6_第六到十大_主力增減.png     第六~十大 · 主力
  7_第六到十大_自然人增減.png   第六~十大 · 自然人
  8_第六到十大_特定法人增減.png 第六~十大 · 特定法人

每張都是 rank.html 的四宮格 (增加/減少 口數 + 增加/減少 金額),差別只在口徑。
版面完全相同, 所以 rank.html 在帶 URL 參數時會多渲染一行標題(.rank-cap),
否則信箱裡四張圖分不出誰是誰。

口徑由 rank.html 的**隱藏 URL 參數**驅動:`?rk=5|6|10&metric=main|t0|inst|nat|moi`。
網站工具列刻意不放「第六~十大」按鈕(使用者要求 UI 不變), rk=6 只有這條路徑到得了。

其餘四張(外資/自營選擇權、外資期現貨、大額交易人期貨)已改由 tools/charts.py
直接讀 data/*.json 自己畫, 不再截網頁 — 不受版面限制、也不必等部署。

作法:在 runner 本機起 http server 直接讀 repo 內的檔案 → headless Chromium 截圖,
不依賴 GitHub Pages 是否已部署完成 (快且不會截到舊版)。

注意:
  - 輸出目錄預設 .shots/ (已列入 .gitignore) — 本 repo 公開, 圖片一律不進版控。
  - 中文字型:runner 需先裝 fonts-noto-cjk, 否則全部變成豆腐方塊。
  - 只截 .rank-grid 這個元素, 不含頁首/說明/工具列。
  - 四張共用同一個瀏覽器實例, 只換網址 — 比開四次快很多。

用法: python tools/shots.py [--out .shots]
"""
import os, sys, time, argparse, threading, functools, http.server, socketserver

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEL = ".rank-grid"
# (檔名, rank.html 的查詢字串) — 檔名前綴決定信件裡的附圖順序
RANK_SHOTS = [
    ("5_前十大_主力增減",        "rk=10&metric=main"),
    ("6_第六到十大_主力增減",     "rk=6&metric=main"),
    ("7_第六到十大_自然人增減",   "rk=6&metric=nat"),
    ("8_第六到十大_特定法人增減", "rk=6&metric=inst"),
]


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

    done, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        # 寬度要夠, 四宮格才會是 2 欄 (rank.html 在 900px 以下會塌成 1 欄)
        page = browser.new_page(viewport={"width": 1500, "height": 1400},
                                device_scale_factor=2)   # 2x = 文字銳利
        for fname, qs in RANK_SHOTS:
            out = os.path.join(a.out, fname + ".png")
            url = f"{origin}/rank.html?{qs}"
            print(f"截圖 {fname} … {url}  (只截 {SEL})")
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_selector(f"{SEL} table tr", timeout=30000)
                # 標題是截圖模式才長出來的, 沒出現就代表 URL 參數沒被吃到 → 當作失敗
                page.wait_for_selector(".rank-cap:not([style*='display: none'])", timeout=10000)
                page.wait_for_timeout(500)
                page.locator(SEL).screenshot(path=out)
                print(f"  完成: {out}  ({os.path.getsize(out)//1024} KB)")
                done.append(fname)
            except Exception as e:      # 單張失敗不影響其他張(信件本來就容忍缺圖)
                print(f"  失敗: {fname} — {type(e).__name__}: {e}")
                failed.append(fname)
        browser.close()

    stop.set()
    print(f"\n完成 {len(done)}/{len(RANK_SHOTS)} 張" + (f";失敗: {', '.join(failed)}" if failed else ""))
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
