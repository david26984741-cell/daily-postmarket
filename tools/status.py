#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily.yml 的「今天還需要跑嗎?」判斷 —— 給每小時的補位班次用, 不連網、只讀 repo 內檔案。

為什麼需要 (2026/11/10):GitHub 的排程是「盡力而為」, 11/09 15:35、21:35 兩個班次都沒有準時觸發,
晚了 4~15 小時才來;11/10 的 15:35 班次到 23 點都沒出現。只靠兩個固定班次, 運氣不好整天沒資料、沒信。
所以在 15:35~23:35 之間每小時多排一個補位班次, 但資料已經齊全就直接結束 (不抓、不 commit、不部署),
不會因為班次變多而重複抓取或重複寄信。

目標日期規則與 scrape.py 相同:台北 14:00 前觸發 → 前一個平日 (排程被延遲跨過午夜時)。
輸出 (GITHUB_OUTPUT 格式):
  target=YYYY/MM/DD
  done=true|false     true = 非交易日, 或該日資料已齊全 → 補位班次可以略過
  reason=...
"""
import os, sys, json, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

import scrape            # noqa: E402  (只用 now_taipei / is_trading_day, 不會連網)
import report            # noqa: E402  (data_gaps: 與信件標題「⚠缺」同一套判斷)


def target_date():
    now = scrape.now_taipei()
    d = now.date()
    if now.hour < 14:
        d -= datetime.timedelta(days=1)
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
    return d.strftime("%Y/%m/%d")


def main():
    t = target_date()
    ok, why = scrape.is_trading_day(t)
    if not ok:
        done, reason = True, f"{t} 非交易日 ({why})"
    else:
        try:
            rk = json.load(open(os.path.join(BASE, "data", "rank.json"), encoding="utf-8"))
            have = rk.get("date", "")
        except Exception:
            have = ""
        if have != t:
            done, reason = False, f"資料日期 {have or '無'} ≠ {t}"
        else:
            gaps = report.data_gaps()
            done = not gaps
            reason = f"{t} 資料齊全" if done else f"{t} 仍缺: {'、'.join(gaps)}"
    print(f"target={t}")
    print(f"done={'true' if done else 'false'}")
    print(f"reason={reason}")


if __name__ == "__main__":
    main()
