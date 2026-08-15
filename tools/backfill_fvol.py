#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回補股票期貨「成交量」→ 補進 data/fkline/{code}.json 的第 5 欄。

背景: fkline 原本只存 [開,高,低,收]。scrape.py 的 _fut_rows_pick() 其實一直有解析出
成交量(用來挑「成交量最大的月契約」), 但寫檔時被丟掉了。本腳本把歷史成交量補回來,
供「股期成交金額 ÷ 現貨成交金額」這類代表性指標使用。

作法: 走 futDataDown 的 **每日全市場** 路徑 (POST, commodity_id=all),
一天一次請求就能拿回全市場約 2,100 列 —— 遠優於逐檔逐月查詢。
(與 tools/backfill_fkline.py 的差別: 那支是逐檔逐月, 適合補缺漏檔案;
 本支是逐日全市場, 適合大批補同一個欄位。)

用法:
    python tools/backfill_fvol.py --start 2017/01/01 --end 2026/08/14
    python tools/backfill_fvol.py --start 2023/01/01 --end 2023/12/31 --sleep 0.4
    python tools/backfill_fvol.py --start ... --end ... --redo    # 連已有成交量的日期也重抓

重點:
  * 每 --flush 天寫檔一次, 逾時被砍也不會整批丟失 (比照 backfill_kline 的做法)。
  * 只更新既有記錄的第 5 欄; 若某日某檔原本沒有記錄, 則整筆新增。
  * 交易日清單直接取自現有 fkline 的日期聯集, 不需另外維護行事曆。
"""

import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scrape


def load_all():
    """讀進所有 fkline 檔 -> {code: doc}。一次載入, 全程在記憶體更新, 定期 flush。"""
    docs = {}
    if not os.path.isdir(scrape.FKLINE):
        return docs
    for fn in sorted(os.listdir(scrape.FKLINE)):
        if not fn.endswith(".json"):
            continue
        code = fn[:-5]
        docs[code] = scrape.load_json(os.path.join(scrape.FKLINE, fn),
                                      {"code": code, "records": {}})
    return docs


def flush(docs, dirty):
    if not dirty:
        return 0
    for code in sorted(dirty):
        scrape.save_json(os.path.join(scrape.FKLINE, f"{code}.json"), docs[code])
    n = len(dirty)
    dirty.clear()
    return n


def trading_days(docs, start, end):
    """交易日 = 現有 fkline 記錄的日期聯集(落在區間內)"""
    days = set()
    for doc in docs.values():
        for d in doc.get("records", {}):
            if start <= d <= end:
                days.add(d)
    return sorted(days)


def has_vol(docs, day, sample=40):
    """該日是否大多數檔案已有成交量 -> 用於續跑時跳過"""
    seen = hit = 0
    for doc in docs.values():
        r = doc.get("records", {}).get(day)
        if r:
            seen += 1
            if len(r) > 4 and r[4] is not None:
                hit += 1
            if seen >= sample:
                break
    return seen > 0 and hit / seen >= 0.8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY/MM/DD")
    ap.add_argument("--end", required=True, help="YYYY/MM/DD")
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--flush", type=int, default=40, help="每 N 個交易日寫檔一次")
    ap.add_argument("--redo", action="store_true", help="已有成交量的日期也重抓")
    args = ap.parse_args()

    # 驗證日期格式(錯了要早點死, 不要跑到一半才發現)
    for s in (args.start, args.end):
        datetime.datetime.strptime(s, "%Y/%m/%d")

    docs = load_all()
    if not docs:
        scrape.log("找不到任何 data/fkline/*.json, 請先用 fkline.yml 回補日K")
        return 1

    days = trading_days(docs, args.start, args.end)
    todo = days if args.redo else [d for d in days if not has_vol(docs, d)]
    scrape.log(f"回補股期成交量: 區間內 {len(days)} 個交易日, 待處理 {len(todo)} 日"
               f" ({len(docs)} 檔契約)")
    if not todo:
        scrape.log("全部已有成交量, 無需回補")
        return 0

    dirty = set()
    ok = miss = 0
    t0 = time.time()
    for i, day in enumerate(todo, 1):
        try:
            got = scrape.fetch_fkline_day(day)
        except Exception as e:
            scrape.log(f"  {day}: 抓取失敗 {e}")
            got = {}
        if not got:
            miss += 1
        for code, bar in got.items():
            if len(bar) < 5:
                continue
            # 只更新「已存在的股期契約」。
            # 注意: fetch_fkline_day 回傳的是所有「3碼且結尾 F」的契約, 會含 TXF(台指期)、
            # BRF/GDF(商品期貨) —— 排除非股期是在呼叫端做的(比對當日大額交易人的股期代碼)。
            # 這裡若照單全收會生出 TX.json / BR.json 等垃圾檔, 故一律跳過未知代號。
            doc = docs.get(code)
            if doc is None:
                continue
            old = doc["records"].get(day)
            if old and len(old) >= 4:
                # 只補成交量, 不動既有 OHLC (避免近月換月造成歷史價格被改寫)
                if len(old) > 4 and old[4] == bar[4] and not args.redo:
                    continue
                doc["records"][day] = list(old[:4]) + [bar[4]]
            else:
                doc["records"][day] = bar
            dirty.add(code)
            ok += 1

        if i % args.flush == 0:
            n = flush(docs, dirty)
            el = time.time() - t0
            scrape.log(f"  進度 {i}/{len(todo)} ({day})  已寫 {n} 檔  "
                       f"累計補 {ok} 筆  無資料 {miss} 日  用時 {el/60:.1f} 分")
        time.sleep(args.sleep)

    flush(docs, dirty)
    scrape.log(f"完成: 補入 {ok} 筆成交量, {miss} 日無資料, 用時 {(time.time()-t0)/60:.1f} 分")
    return 0


if __name__ == "__main__":
    sys.exit(main())
