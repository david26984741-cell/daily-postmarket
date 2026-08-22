#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回補指數期貨近月日K(日盤 + 夜盤) → data/txk/<西元年>.json。

商品: scrape.TXK_PRODUCTS = TX 台指、TE 電子、TF 金融、XIF 非金電、M1F 中型100。

⚠ 夜盤的日期歸屬(回測對齊關鍵):
    期交所把「D-1 15:00 → D 05:00」這段盤後時段標為交易日 D。
    所以 records[D]["night"] 是 D 這根日盤「之前」的那一夜, 不是 D 收盤後的那一夜。
    完整實測依據寫在 scrape.fetch_txk_range 的 docstring。
    夜盤自 2017/05/16(標記日)起才有資料; 更早的日期 night 一律是 null, 屬正常。

資料範圍: futDataDown 至少回溯到 2010/01 (2026/08/22 實測, TX 開高低收齊全)。
          單次查詢限一個月內, 因此逐月抓取。

效率: 每個商品每月一次請求。TX 從 2010/01 到 2026/08 約 200 個月,
      五個商品共約 1,000 次請求, 以 --sleep 0.6 計約 20 分鐘跑完。

用法:
    python tools/backfill_txk.py --start 2010/01/01 --end 2026/08/21
    python tools/backfill_txk.py --start 2017/01/01 --end 2017/12/31 --products TX,TE
"""
import os, sys, time, datetime, argparse, importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("scrape", os.path.join(BASE, "scrape.py"))
scrape = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrape)

FLUSH_EVERY_MONTHS = 12       # 每 N 個(商品×月)存檔一次, 逾時被砍時不至於整批丟失


def month_ranges(start, end):
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        yield max(cur, start), min(end, nxt - datetime.timedelta(days=1))
        cur = nxt


def year_path(year):
    return os.path.join(scrape.TXK, f"{year}.json")


def load_year(year, cache):
    if year not in cache:
        cache[year] = scrape.load_json(year_path(year), {"meta": {
            "title": "指數期貨近月日K(含夜盤)",
            "source": "TAIFEX futDataDown · 一般時段成交量最大之月契約",
            "night_note": "night 為「D-1 15:00 → D 05:00」的盤後時段, 即該日日盤之前的那一夜; "
                          "非該日收盤後的夜盤。要取 D 收盤後的夜盤請看下一個交易日的 night。",
            "fields": "day/night = [開, 高, 低, 收, 成交量]; settle 僅日盤有",
        }, "records": {}})
    return cache[year]


def flush(cache):
    for year, doc in cache.items():
        scrape.save_json(year_path(year), doc)
    return len(cache)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="起始日期 YYYY/MM/DD")
    ap.add_argument("--end",   required=True, help="結束日期 YYYY/MM/DD")
    ap.add_argument("--products", default=",".join(scrape.TXK_PRODUCTS),
                    help="逗號分隔的商品代碼, 預設 " + ",".join(scrape.TXK_PRODUCTS))
    ap.add_argument("--sleep", type=float, default=0.6, help="每次請求間隔秒數")
    a = ap.parse_args()

    s = datetime.datetime.strptime(a.start, "%Y/%m/%d").date()
    e = datetime.datetime.strptime(a.end, "%Y/%m/%d").date()
    products = [p.strip() for p in a.products.split(",") if p.strip()]
    months = list(month_ranges(s, e))

    cache = {}
    t0 = time.time()
    days = nights = fails = 0
    since_flush = 0
    total = len(products) * len(months)
    step = 0

    for cid in products:
        got_for_product = 0
        for a0, b0 in months:
            step += 1
            try:
                res = scrape.fetch_txk_range(cid, a0.strftime("%Y/%m/%d"), b0.strftime("%Y/%m/%d"))
            except Exception as ex:
                fails += 1
                print(f"[失敗] {cid} {a0:%Y/%m}  {ex}")
                time.sleep(a.sleep)
                continue
            for d, rec in res.items():
                doc = load_year(d[:4], cache)
                doc["records"].setdefault(d, {})[cid] = rec
                days += 1
                got_for_product += 1
                if rec.get("night"):
                    nights += 1
            since_flush += 1
            if res:
                print(f"[{step}/{total}] {cid} {a0:%Y/%m}: {len(res)} 日")
            if since_flush >= FLUSH_EVERY_MONTHS:
                flush(cache); since_flush = 0
            time.sleep(a.sleep)
        print(f"--- {cid} 完成, 共 {got_for_product} 日 (累計耗時 {time.time()-t0:.0f} 秒) ---")

    flush(cache)
    print(f"\n=== 結束 === 寫入 {days} 筆(商品×日), 其中 {nights} 筆含夜盤, "
          f"失敗 {fails} 次, 共 {len(cache)} 個年度檔, 耗時 {time.time()-t0:.0f} 秒")
    return 1 if (fails and not days) else 0


if __name__ == "__main__":
    sys.exit(main())
