#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
資料稽核 — 回答三件事:
  1. 期交所官方標的清單有幾檔?與 data/stock_map.json 是否一致?(有無新掛牌被漏掉)
  2. 當日 largeTraderFut CSV 裡有哪些商品代碼「不在」個股清單中?(確認沒有個股被誤刪)
  3. data/stocks/*.json 每檔的歷史涵蓋:首筆日期、末筆日期、筆數。
     並列出「完整」(等於全期間交易日數) 與「不完整」(中途才掛牌或曾停牌) 的檔數與清單。

用法: python tools/audit.py [--date 2026/07/08]
"""
import os, sys, json, argparse, importlib.util
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("scrape", os.path.join(BASE, "scrape.py"))
scrape = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrape)


def probe_fkline_zip(date_slash):
    """探測期交所「每日行情 zip」的實際欄位格式。
    scrape.fetch_fkline_day 依賴此格式; 期交所若改版, 解析會靜靜地回 0 筆
    (2026/07 就發生過 — 每日排程的股期日K 從上線起就沒成功過)。
    印出:壓縮檔內檔名、標題列(含索引)、股期樣本列, 以及現行解析器實際命中幾筆。"""
    import io, zipfile
    ymd = date_slash.replace("/", "_")
    url = f"https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_{ymd}.zip"
    print(f"\n[Z] 每日行情 zip 格式探測  {date_slash}\n    {url}")
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": scrape.UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except Exception as e:
        print(f"    下載失敗: {e}")
        return
    print(f"    下載 {len(raw)//1024} KB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception as e:
        print(f"    不是有效的 zip: {e}  (前 80 bytes: {raw[:80]!r})")
        return
    print(f"    內含檔案: {zf.namelist()}")
    txt = zf.read(zf.namelist()[0]).decode("cp950", errors="replace")
    lines = [l for l in txt.splitlines() if l.strip()]
    print(f"    總行數: {len(lines)}")
    if not lines:
        return

    hdr = [c.strip() for c in lines[0].split(",")]
    print("    標題列:")
    for i, h in enumerate(hdr):
        print(f"       [{i:2}] {h}")

    # 現行解析器命中數 (期望: 股票期貨應有數百列)
    hit = scrape._fut_rows_pick(lines)
    print(f"    現行 _fut_rows_pick 命中: {len(hit)} 筆" + ("  ← 0 筆代表格式不符!" if not hit else ""))

    # 找出看起來像股票期貨的列 (任一欄位是 2~3 碼英數且像契約代號)
    print("    前 3 筆資料列 (逐欄):")
    for ln in lines[1:4]:
        cols = [c.strip() for c in ln.split(",")]
        print("       " + " | ".join(f"{i}:{c}" for i, c in enumerate(cols[:12])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="用來檢查 CSV 的日期 YYYY/MM/DD (預設: index.json 最新日)")
    ap.add_argument("--probe-zip", action="store_true",
                    help="只探測每日行情 zip 的欄位格式 (診斷股期日K抓取用)")
    a = ap.parse_args()

    if a.probe_zip:
        idx = scrape.load_json(os.path.join(scrape.DATA, "index.json"), {})
        ds = sorted(idx.get("dates", []))
        probe_fkline_zip(a.date or (ds[-1] if ds else ""))
        return 0

    idx = scrape.load_json(os.path.join(scrape.DATA, "index.json"), {})
    all_dates = sorted(idx.get("dates", []))
    date = a.date or (all_dates[-1] if all_dates else None)
    print(f"===== 資料稽核  (檢查日 {date}) =====\n")

    # ---- 1. 官方標的清單 vs 本地清單 ----
    local = scrape.load_json(os.path.join(scrape.DATA, "stock_map.json"), {})
    try:
        html = scrape.http_get(scrape.STOCK_LIST, timeout=40)
        official = scrape.parse_stock_list(html)
    except Exception as e:
        official = {}
        print(f"[警告] 無法取得官方清單: {e}")

    print(f"[1] 官方標的 {len(official)} 檔 / 本地清單 {len(local)} 檔")
    if official:
        only_off = sorted(set(official) - set(local))
        only_loc = sorted(set(local) - set(official))
        add = [c + "=" + official[c]["short"] for c in only_off]
        rm  = [c + "=" + local[c].get("short", c) for c in only_loc]
        print("    官方有、本地沒有 (需補): " + (", ".join(add) if add else "無"))
        print("    本地有、官方沒有 (已下架): " + (", ".join(rm) if rm else "無"))

    # ---- 2. CSV 中不屬於個股清單的代碼 ----
    if date:
        try:
            rows = scrape.fetch_taifex_csv("largeFut", date)
            codes = {}
            for r in rows[1:]:
                if len(r) >= 10:
                    codes[r[1]] = r[2]
            keys = official or local
            others = {c: n for c, n in codes.items() if c not in keys}
            print(f"\n[2] {date} CSV 共 {len(codes)} 種商品;其中非個股 {len(others)} 種:")
            for c, n in sorted(others.items()):
                print(f"    {c:<5} {n}")
        except Exception as e:
            print(f"\n[2] CSV 檢查失敗: {e}")

    # ---- 3. 每檔歷史涵蓋 ----
    print(f"\n[3] 個股歷史涵蓋 (資料庫共 {len(all_dates)} 個交易日: {all_dates[0] if all_dates else '-'} ~ {all_dates[-1] if all_dates else '-'})")
    full, partial = [], []
    if os.path.isdir(scrape.STOCKS):
        for fn in sorted(os.listdir(scrape.STOCKS)):
            if not fn.endswith(".json"):
                continue
            d = scrape.load_json(os.path.join(scrape.STOCKS, fn), {})
            ds = sorted(d.get("records", {}).keys())
            if not ds:
                continue
            item = (d.get("code"), d.get("name"), d.get("sid", ""), ds[0], ds[-1], len(ds))
            (full if len(ds) == len(all_dates) else partial).append(item)

    print(f"    完整 {len(full)} 檔 · 不完整 {len(partial)} 檔\n")
    if partial:
        print("    以下各檔歷史較短 (多為期間內才掛牌 / 曾暫停交易):")
        print(f"    {'代碼':<6}{'名稱':<20}{'證券代號':<10}{'首筆':<12}{'末筆':<12}{'筆數'}")
        for c, n, s, f, l, k in sorted(partial, key=lambda x: x[5]):
            print(f"    {c:<6}{n:<20}{s:<10}{f:<12}{l:<12}{k}")

    # 末筆不是最新交易日 → 可能已下市/停止交易
    if all_dates:
        stale = [p for p in partial if p[4] != all_dates[-1]]
        print(f"\n    其中『末筆不是最新交易日』(可能已下市或當日無資料) 共 {len(stale)} 檔:")
        for c, n, s, f, l, k in sorted(stale, key=lambda x: x[4]):
            print(f"    {c:<6}{n:<20}{s:<10}末筆 {l}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
