#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回補個股現貨日K — 只抓股價 (上市 MI_INDEX + 上櫃 dailyQuotes), 不動大額交易人資料。

用法:
    python tools/backfill_kline.py --start 2017/07/10 --end 2025/07/08 --sleep 1.0

行為:
  - 只抓 stock_map.json 中有證券代號的標的 (股期對應之現股)
  - 逐日抓取全市場行情 (每日僅 2 個請求), 累積於記憶體, 結束時一次寫檔
  - 自動略過週末與無行情日; 同日重跑僅覆蓋當日
"""
import os, sys, time, argparse, datetime, importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("scrape", os.path.join(BASE, "scrape.py"))
scrape = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrape)


def daterange(a, b):
    d = datetime.datetime.strptime(a, "%Y/%m/%d").date()
    e = datetime.datetime.strptime(b, "%Y/%m/%d").date()
    if e < d:
        raise SystemExit("結束日期不可早於起始日期")
    while d <= e:
        yield d.strftime("%Y/%m/%d")
        d += datetime.timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()

    stock_map = scrape.load_json(os.path.join(scrape.DATA, "stock_map.json"), {})
    sids = sorted({v.get("sid") for v in stock_map.values() if v.get("sid")})
    print(f"標的數 (有證券代號): {len(sids)}")
    os.makedirs(scrape.KLINE, exist_ok=True)

    acc = {}          # sid -> {date: ohlcv}
    days, empty = 0, 0
    for d in daterange(a.start, a.end):
        wd = datetime.datetime.strptime(d, "%Y/%m/%d").date().weekday()
        if wd >= 5:
            continue
        kmap = scrape.fetch_kline_maps(d.replace("/", ""))
        if not kmap:
            empty += 1
            print(f"[略過] {d} 無行情(可能休市)")
            time.sleep(a.sleep); continue
        n = 0
        for sid in sids:
            if sid in kmap:
                acc.setdefault(sid, {})[d] = kmap[sid]; n += 1
        days += 1
        print(f"{d} 日K {n} 檔", flush=True)
        time.sleep(a.sleep)

    # 一次合併寫檔
    for sid, recs in acc.items():
        path = os.path.join(scrape.KLINE, f"{sid}.json")
        doc = scrape.load_json(path, {"sid": sid, "records": {}})
        doc["records"].update(recs)
        scrape.save_json(path, doc)
    print(f"完成: {days} 個交易日, {len(acc)} 檔寫入, 略過 {empty} 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
