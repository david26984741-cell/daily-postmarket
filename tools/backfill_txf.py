#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回補台指期(TX)近月收盤價 → data/txf.json。
TAIFEX futDataDown 單次查詢限一個月內, 逐月抓取; 資料保留約三年。
用法: python tools/backfill_txf.py --start 2023/07/01 --end 2026/07/16
"""
import os, sys, time, datetime, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scrape


def month_ranges(start, end):
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        yield max(cur, start), min(end, nxt - datetime.timedelta(days=1))
        cur = nxt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY/MM/DD")
    ap.add_argument("--end", required=True, help="YYYY/MM/DD")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()
    s = datetime.datetime.strptime(args.start, "%Y/%m/%d").date()
    e = datetime.datetime.strptime(args.end, "%Y/%m/%d").date()

    path = os.path.join(scrape.DATA, "txf.json")
    doc = scrape.load_json(path, {"meta": {"source": "TAIFEX futDataDown · TX 近月月契約一般時段收盤"}, "records": {}})
    n0 = len(doc["records"])
    for a, b in month_ranges(s, e):
        try:
            got = scrape.fetch_txf_range(a.strftime("%Y/%m/%d"), b.strftime("%Y/%m/%d"))
            doc["records"].update(got)
            scrape.log(f"{a} ~ {b}: +{len(got)} 日")
        except Exception as ex:
            scrape.log(f"{a} ~ {b}: 失敗 {ex}")
        scrape.save_json(path, doc)          # 每月存檔一次, 防中斷丟失
        time.sleep(args.sleep)
    scrape.log(f"完成: 共 {len(doc['records'])} 日 (+{len(doc['records']) - n0})")


if __name__ == "__main__":
    main()
