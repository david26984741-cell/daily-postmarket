#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指數預測力研究: 各分頁(選擇權/外資期貨/大額交易人)資料 對 台指期未來報酬 的預測性。

目標序列: data/txf.json (台指期近月結算價, 約3年)。
特徵來源: options_foreign / options_dealer / foreign_fut_spot / large_opt / large_fut_txf。
方法: 對每個特徵取「水準z」與「單日變化z」(60日滾動標準化),
      與 T+1/2/3/5/10/20 前瞻報酬做 Spearman 相關 (整段時序, 非橫斷面);
      另做五分位平均報酬與簡單方向規則回測。
注意: 時序單一序列且前瞻報酬重疊, t 值僅供參考, 樣本僅約3年。
輸出: data/analysis_index.json
"""
import os, sys, json, datetime

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

def load(f):
    with open(os.path.join(DATA, f), encoding="utf-8") as fh:
        return json.load(fh)

def log(m): print(m, flush=True)

HORIZONS = [1, 2, 3, 5, 10, 20]

def pick_row(rows, month, typ):
    for x in rows or []:
        if x.get("month") == month and x.get("type") == typ:
            return x
    return None

def build_features():
    """回傳 DataFrame(index=date), 各特徵欄。"""
    cols = {}

    # --- 台指期結算價 (目標) ---
    txf = load("txf.json")["records"]
    px = pd.Series(txf, dtype=float).sort_index()
    cols["_px"] = px

    # --- 外資/自營選擇權: CALL/PUT 未平倉金額差 與 C-P ---
    for key, tag in [("options_foreign.json", "外資選"), ("options_dealer.json", "自營選")]:
        rec = load(key)["records"]
        c_amt, p_amt = {}, {}
        for d, r in rec.items():
            if r.get("call"): c_amt[d] = r["call"].get("diff_oi_amt")
            if r.get("put"):  p_amt[d] = r["put"].get("diff_oi_amt")
        cols[f"{tag}·CALL金額"] = pd.Series(c_amt, dtype=float)
        cols[f"{tag}·PUT金額"] = pd.Series(p_amt, dtype=float)
        cols[f"{tag}·C−P金額"] = cols[f"{tag}·CALL金額"] - cols[f"{tag}·PUT金額"]

    # --- 外資期貨淨未平倉(口) 與 外資現貨買賣差 ---
    rec = load("foreign_fut_spot.json")["records"]
    fut, spot = {}, {}
    for d, r in rec.items():
        if r.get("fut"):  fut[d] = r["fut"].get("net_oi_lots")
        if r.get("spot"): spot[d] = r["spot"].get("net_amt")
    cols["外資期貨·淨未平倉"] = pd.Series(fut, dtype=float)
    s = pd.Series(spot, dtype=float)
    if s.dropna().shape[0] >= 100:
        cols["外資現貨·買賣差"] = s

    # --- 大額交易人選擇權: 前十特定法人 CALL淨/PUT淨/C−P (所有契約) ---
    rec = load("large_opt.json")["records"]
    cN, pN = {}, {}
    for d, r in rec.items():
        c1 = pick_row(r.get("call"), "999999", "1")
        p1 = pick_row(r.get("put"), "999999", "1")
        if c1: cN[d] = c1["top10_buy"] - c1["top10_sell"]
        if p1: pN[d] = p1["top10_buy"] - p1["top10_sell"]
    cols["大額選·法人CALL淨"] = pd.Series(cN, dtype=float)
    cols["大額選·法人PUT淨"] = pd.Series(pN, dtype=float)
    cols["大額選·法人C−P"] = cols["大額選·法人CALL淨"] - cols["大額選·法人PUT淨"]

    # --- 大額交易人期貨: 法人 / 自然人 / 主力 (口徑與網站一致) ---
    rec = load("large_fut_txf.json")["records"]
    t0s, t1s = {}, {}
    for d, r in rec.items():
        rows = r.get("rows") or []
        a0 = pick_row(rows, "999999", "0")
        a1 = pick_row(rows, "999999", "1")
        if a0: t0s[d] = a0["top10_buy"] - a0["top10_sell"]
        if a1: t1s[d] = a1["top10_buy"] - a1["top10_sell"]
    t0 = pd.Series(t0s, dtype=float); t1 = pd.Series(t1s, dtype=float)
    cols["大額期·法人淨"] = t1
    cols["大額期·自然人淨"] = t0 - t1
    cols["大額期·主力淨"] = (t0 - t1) - t1

    df = pd.DataFrame(cols).sort_index()
    df = df[df["_px"].notna()]
    return df

def zscore(s, win=60, minp=20):
    m = s.rolling(win, min_periods=minp).mean()
    sd = s.rolling(win, min_periods=minp).std()
    return (s - m) / sd.replace(0, np.nan)

def spearman(a, b):
    x = pd.concat([a, b], axis=1).dropna()
    n = len(x)
    if n < 40:
        return None, None, n
    rho = x.iloc[:, 0].rank().corr(x.iloc[:, 1].rank())
    if pd.isna(rho) or abs(rho) >= 1:
        return None, None, n
    t = rho * np.sqrt((n - 2) / (1 - rho * rho))
    return round(float(rho), 4), round(float(t), 2), n

def main():
    df = build_features()
    px = df.pop("_px")
    fwd = {k: (px.shift(-k) / px - 1) for k in HORIZONS}
    log(f"樣本: {len(df)} 日, {df.shape[1]} 個特徵, {px.index.min()} ~ {px.index.max()}")

    out_feats = {}
    for col in df.columns:
        f = df[col]
        preds = {"水準z": zscore(f), "變化z": zscore(f.diff())}
        entry = {}
        for pname, p in preds.items():
            hs = {}
            for k in HORIZONS:
                rho, t, n = spearman(p, fwd[k])
                hs[f"T+{k}"] = {"rho": rho, "t": t, "n": n}
            entry[pname] = hs
        # 五分位 (變化z → T+5 / T+20 平均報酬 bp)
        q = {}
        chg = preds["變化z"]
        for k in [5, 20]:
            x = pd.concat([chg, fwd[k]], axis=1).dropna()
            if len(x) >= 100:
                x.columns = ["f", "r"]
                x["q"] = pd.qcut(x["f"], 5, labels=False, duplicates="drop")
                q[f"T+{k}"] = [round(float(v) * 1e4, 1) for v in x.groupby("q")["r"].mean()]
        entry["五分位bp"] = q
        out_feats[col] = entry

    # 簡單方向規則: 水準>0 做多 vs <0 做多 的隔日平均報酬 (bp)
    rules = {}
    base1 = float(fwd[1].mean()) * 1e4
    for col in ["外資期貨·淨未平倉", "大額期·主力淨", "大額期·法人淨",
                "外資選·C−P金額", "自營選·C−P金額", "大額選·法人C−P"]:
        if col not in df.columns:
            continue
        f = df[col]
        x = pd.concat([f, fwd[1]], axis=1).dropna(); x.columns = ["f", "r"]
        pos = x[x["f"] > 0]["r"]; neg = x[x["f"] < 0]["r"]
        rules[col] = {"為正時隔日bp": round(float(pos.mean()) * 1e4, 1) if len(pos) > 30 else None,
                      "n正": int(len(pos)),
                      "為負時隔日bp": round(float(neg.mean()) * 1e4, 1) if len(neg) > 30 else None,
                      "n負": int(len(neg))}

    out = {
        "generated_at": (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "target": "台指期近月結算價 前瞻報酬",
        "sample": {"days": int(len(df)), "from": str(px.index.min()), "to": str(px.index.max())},
        "baseline_bp": {f"T+{k}": round(float(fwd[k].mean()) * 1e4, 1) for k in HORIZONS},
        "features": out_feats,
        "rules_nextday": {"基準隔日bp": round(base1, 1), "rules": rules},
        "notes": "單一時序+重疊前瞻報酬, t 值偏樂觀僅供參考; 樣本約3年(資料保留限制); |t|>2 視為值得關注, 仍需更長樣本驗證。",
    }
    with open(os.path.join(DATA, "analysis_index.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log("已輸出 data/analysis_index.json")

if __name__ == "__main__":
    main()
