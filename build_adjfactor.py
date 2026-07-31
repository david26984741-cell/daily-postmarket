#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
由除權息事件建立 backward 還原因子 (最新一日 = 1.0)

定義 (規格書 §3.2):
    k_event = 除權息參考價 / 除權息前收盤價              (必為 <= 1)
    f(t)    = Π k_event  , 對所有「除權息日 > t」的事件連乘
    P_adj(t) = P_raw(t) * f(t)
    r(t)     = P_adj(t) / P_adj(t-1) - 1

因此 f 是一條隨時間非遞減、最後一日為 1.0 的階梯函數。

輸入:
    data/exright/twse.json, data/exright/tpex.json
    data/kline/<sid>.json              {"sid":..., "records":{"YYYY/MM/DD":[o,h,l,c,v]}}
輸出:
    data/adjfactor/<sid>.json          {"sid":..., "convention":"backward, latest=1.0",
                                        "records":{"YYYY/MM/DD": factor}}
"""

import os, sys, json, argparse, datetime
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
EXRIGHT = os.path.join(DATA, "exright")
KLINE = os.path.join(DATA, "kline")
ADJ = os.path.join(DATA, "adjfactor")


def log(m):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {m}", flush=True)


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def load_events():
    """回傳 {sid: [(date, k), ...]} , k = ref/pre"""
    ev = defaultdict(list)
    n_raw = n_kept = 0
    for mk in ("twse", "tpex"):
        doc = load(os.path.join(EXRIGHT, f"{mk}.json"))
        if not doc:
            log(f"警告: 找不到 {mk}.json, 略過")
            continue
        if doc.get("failed_months"):
            log(f"警告: {mk}.json 標記有失敗月份 {doc['failed_months']} — 因子可能不完整")
        for r in doc.get("records", []):
            n_raw += 1
            pre, ref = r.get("pre_close"), r.get("ref_price")
            if not pre or not ref or pre <= 0 or ref <= 0:
                continue
            k = ref / pre
            # 理論上 k <= 1。少數含現金增資的案例 k 可能略大於 1, 予以保留但夾住上界,
            # 避免異常值把整條因子拉爆。
            if k <= 0 or k > 1.5:
                continue
            ev[r["sid"]].append((r["date"], min(k, 1.0)))
            n_kept += 1
    log(f"事件載入: 原始 {n_raw} 筆, 採用 {n_kept} 筆, 涵蓋 {len(ev)} 檔標的")
    for sid in ev:
        ev[sid].sort()
    return ev


def build_factor(dates, events):
    """dates: 已排序的交易日 list; events: [(date,k)] -> {date: factor}"""
    # f(t) = 所有「事件日 > t」的 k 連乘。由後往前累乘即可。
    fac = {}
    acc = 1.0
    ev = sorted(events, reverse=True)
    i = 0
    for d in reversed(dates):
        # 把所有事件日 > d 的 k 乘進來
        while i < len(ev) and ev[i][0] > d:
            acc *= ev[i][1]
            i += 1
        fac[d] = acc
    return fac


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid", help="只處理單一標的 (除錯用)")
    a = ap.parse_args()

    ev = load_events()
    if not os.path.isdir(KLINE):
        log(f"錯誤: 找不到 {KLINE}")
        return 1

    files = sorted(f for f in os.listdir(KLINE) if f.endswith(".json"))
    if a.sid:
        files = [f"{a.sid}.json"]

    n_out = n_with_ev = 0
    for fn in files:
        sid = fn[:-5]
        k = load(os.path.join(KLINE, fn))
        if not k:
            continue
        recs = k.get("records") or {}
        dates = sorted(recs.keys())
        if not dates:
            continue
        events = [(d, kk) for d, kk in ev.get(sid, []) if dates[0] < d <= dates[-1]]
        fac = build_factor(dates, events)
        save(os.path.join(ADJ, fn),
             {"sid": sid,
              "convention": "backward, latest=1.0",
              "n_events": len(events),
              "updated_at": datetime.date.today().isoformat(),
              "records": {d: round(fac[d], 8) for d in dates}})
        n_out += 1
        if events:
            n_with_ev += 1

    log(f"完成: 寫出 {n_out} 檔還原因子, 其中 {n_with_ev} 檔有除權息事件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
