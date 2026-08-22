#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回補大額交易人「指數/商品期貨」→ data/large_fut_index/<西元年>.json。

涵蓋: 台指期(TX)、電子(TE)、金融(TF)、非金電(XIF)、中型100(M1F)、
      櫃買(GTF)、黃金(GDF)、布蘭特原油(BRF) 等所有非個股契約。
收錄規則與 scrape.py cat5b 相同 —— cat6 個股期貨判斷式的嚴格補集。

為什麼不直接用 tools/backfill.py:
  backfill.py 會跑完整的 scrape.run(), 每個交易日要打 6 次來源(其中證交所現貨
  對舊日期固定空轉 15 秒), 而且會重寫 388 個個股檔。
  本表只需要 largeTraderFut 這一次請求, 且只寫一個年度檔:
    - 每個交易日約 2 秒, 而非約 27 秒 (5,400 個交易日 = 3 小時 vs 40 小時)
    - git 只需記錄一個年度檔的改動, 而不是整批個股檔

資料範圍: 期交所本表自 2004/07/01 起提供 (2026/08/22 實測, 2004/06/30 及更早皆回空)。
          股票期貨 2010/01 才掛牌, 在此之前只有指數與商品契約。

用法:
    python tools/backfill_index_fut.py --start 2004/07/01 --end 2026/08/21
    python tools/backfill_index_fut.py --start 2015/01/01 --end 2015/12/31 --force
"""
import os, sys, time, argparse, datetime, importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("scrape", os.path.join(BASE, "scrape.py"))
scrape = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrape)

NON_STOCK_2CHAR = {"TX", "TE", "TF"}
FLUSH_EVERY = 60          # 每 N 個交易日存檔一次, 避免逾時被砍時丟失整批


def daterange(a, b):
    d = datetime.datetime.strptime(a, "%Y/%m/%d").date()
    e = datetime.datetime.strptime(b, "%Y/%m/%d").date()
    if e < d:
        raise SystemExit("結束日期不可早於起始日期")
    while d <= e:
        yield d.strftime("%Y/%m/%d")
        d += datetime.timedelta(days=1)


def year_path(year):
    return os.path.join(scrape.DATA, "large_fut_index", f"{year}.json")


def load_year(year, cache):
    """年度檔在記憶體中快取, 避免每天重複讀寫 2 MB 的檔案。"""
    if year not in cache:
        cache[year] = scrape.load_json(
            year_path(year),
            {"meta": {"title": "大額交易人指數期貨",
                      "source": "台指期/電子/金融/非金電/中型100 等非個股契約 當月+所有契約"},
             "records": {}})
    return cache[year]


def flush(cache):
    for year, doc in cache.items():
        scrape.save_json(year_path(year), doc)
    return len(cache)


def pick_index_rows(rows):
    """從 largeTraderFut 的列中取出所有「非個股」契約。
    條件寫成 scrape.py cat6 判斷式的嚴格補集, 兩邊互為反面, 不會重複也不會遺漏。"""
    out = {}
    for code, g in scrape.parse_large_fut(rows).items():
        name = g["name"] or ""
        if len(code) == 2 and code not in NON_STOCK_2CHAR and "(" not in name:
            continue                      # 個股/ETF 期貨 — 由 scrape.py cat6 寫入 data/stocks/
        out[code] = {"name": name, "rows": g["rows"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="起始日期 YYYY/MM/DD")
    ap.add_argument("--end",   required=True, help="結束日期 YYYY/MM/DD")
    ap.add_argument("--force", action="store_true", help="已有資料的日期也重抓覆蓋")
    ap.add_argument("--sleep", type=float, default=0.5, help="每日之間間隔秒數")
    a = ap.parse_args()

    cache = {}
    done = skipped = failed = 0
    since_flush = 0
    t0 = time.time()

    for d in daterange(a.start, a.end):
        trading, why = scrape.is_trading_day(d)
        if not trading:
            continue                       # 週末 / holidays.txt, 不計入統計也不印

        doc = load_year(d[:4], cache)
        if (not a.force) and d in doc["records"]:
            skipped += 1
            continue

        try:
            rows = scrape.fetch_taifex_csv("largeFut", d)
            if not scrape.csv_date_ok(rows, d):
                skipped += 1
                print(f"[略過] {d}  來源無該日資料(休市或尚未提供)")
                time.sleep(a.sleep)
                continue
            idx = pick_index_rows(rows)
            if not idx:
                skipped += 1
                print(f"[略過] {d}  無非個股契約")
                time.sleep(a.sleep)
                continue
            doc["records"][d] = idx
            done += 1
            since_flush += 1
            codes = "、".join(sorted(idx))
            print(f"[完成] {d}  {len(idx)} 契約  {codes}")
        except Exception as e:
            failed += 1
            print(f"[失敗] {d}  {e}")

        if since_flush >= FLUSH_EVERY:
            n = flush(cache)
            since_flush = 0
            print(f"  -- 已存檔 {n} 個年度檔 (累計完成 {done} 日, 耗時 {time.time()-t0:.0f} 秒)")

        time.sleep(a.sleep)

    flush(cache)
    print(f"\n=== 結束 === 完成 {done} 日, 略過 {skipped} 日, 失敗 {failed} 日, "
          f"共 {len(cache)} 個年度檔, 耗時 {time.time()-t0:.0f} 秒")
    return 1 if (failed and not done) else 0


if __name__ == "__main__":
    sys.exit(main())
