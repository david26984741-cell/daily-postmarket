#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回補股票期貨近月日K → data/fkline/{code}.json。
futDataDown 需逐檔(代號+F)逐月查詢; 依 stock_map.json 全部代號跑。
用法: python tools/backfill_fkline.py --start 2024/01/01 --end 2026/07/17 [--sleep 0.3] [--codes CD,QF]
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
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--codes", default="", help="逗號分隔, 留空=全部")
    args = ap.parse_args()
    s = datetime.datetime.strptime(args.start, "%Y/%m/%d").date()
    e = datetime.datetime.strptime(args.end, "%Y/%m/%d").date()

    smap = scrape.load_json(os.path.join(scrape.DATA, "stock_map.json"), {})
    codes = [c.strip().upper() for c in args.codes.split(",") if c.strip()] or sorted(smap.keys())
    months = list(month_ranges(s, e))
    scrape.log(f"回補股期日K: {len(codes)} 檔 × {len(months)} 個月")

    for ci, code in enumerate(codes, 1):
        path = os.path.join(scrape.FKLINE, f"{code}.json")
        doc = scrape.load_json(path, {"code": code, "records": {}})
        n0 = len(doc["records"])
        for a, b in months:
            try:
                got = scrape.fetch_fkline_range(code, a.strftime("%Y/%m/%d"), b.strftime("%Y/%m/%d"))
                doc["records"].update(got)
            except Exception as ex:
                scrape.log(f"  {code} {a}~{b}: 失敗 {ex}")
            time.sleep(args.sleep)
        os.makedirs(scrape.FKLINE, exist_ok=True)
        scrape.save_json(path, doc)
        scrape.log(f"[{ci}/{len(codes)}] {code}: {len(doc['records'])} 日 (+{len(doc['records']) - n0})")
    scrape.log("完成")


if __name__ == "__main__":
    main()
