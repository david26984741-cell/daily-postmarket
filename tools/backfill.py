#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回補歷史資料 — 指定日期區間, 逐日抓取並寫入 data/。

用法:
    python tools/backfill.py --start 2026/06/24 --end 2026/07/07
    python tools/backfill.py --start 2026/04/01 --end 2026/07/07 --force

行為:
  - 自動略過 週末 與 data/holidays.txt 列出的休市日
  - 抓取前先確認期交所該日確實有資料; 沒有(可能休市)就略過, 不寫入假資料
  - 預設略過 data/index.json 已存在的日期; 加 --force 可強制重抓覆蓋當日
  - 每個日期之間間隔數秒, 避免對來源造成負擔
  - 以「日期」為鍵 append, 不會動到其它日期的既有資料

注意:
  證交所「外資現貨買賣差額」只提供當日最新資料, 回補舊日期時該欄位可能為空(屬正常)。
  期交所的部分(外資/自營選擇權、大額交易人期貨/選擇權、個股期貨)都能正常回補。
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
    ap.add_argument("--start", required=True, help="起始日期 YYYY/MM/DD")
    ap.add_argument("--end",   required=True, help="結束日期 YYYY/MM/DD")
    ap.add_argument("--force", action="store_true", help="已存在的日期也重抓")
    ap.add_argument("--sleep", type=float, default=2.0, help="每日之間間隔秒數")
    a = ap.parse_args()

    idx = scrape.load_json(os.path.join(scrape.DATA, "index.json"), {"dates": []})
    have = set(idx.get("dates", []))

    done, skipped, failed = [], [], []

    for d in daterange(a.start, a.end):
        ok, why = scrape.is_trading_day(d)
        if not ok:
            skipped.append((d, why)); print(f"[略過] {d}  {why}"); continue

        if (not a.force) and d in have:
            skipped.append((d, "已存在")); print(f"[略過] {d}  已有資料"); continue

        # 抓取前先確認期交所該日確實有資料 (避免把休市日寫成「未更新」)
        try:
            rows = scrape.fetch_taifex_csv("callsAndPuts", d)
            if not scrape.csv_date_ok(rows, d):
                skipped.append((d, "來源無該日資料(可能休市)"))
                print(f"[略過] {d}  來源無該日資料(可能休市)")
                time.sleep(a.sleep); continue
        except Exception as e:
            failed.append((d, f"預檢失敗 {e}")); print(f"[失敗] {d}  預檢失敗 {e}")
            time.sleep(a.sleep); continue

        print(f"===== 回補 {d} =====")
        try:
            scrape.run(d, no_retry=True)
            done.append(d)
        except Exception as e:
            failed.append((d, str(e))); print(f"[失敗] {d}  {e}")

        time.sleep(a.sleep)

    print("\n=============== 回補結果 ===============")
    print(f"成功 {len(done)} 天" + (": " + ", ".join(done) if done else ""))
    print(f"略過 {len(skipped)} 天")
    for d, w in skipped:
        print(f"   - {d}  ({w})")
    if failed:
        print(f"失敗 {len(failed)} 天:")
        for d, w in failed:
            print(f"   - {d}  ({w})")
    else:
        print("失敗 0 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
