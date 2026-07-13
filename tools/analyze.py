#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
籌碼變化 → 未來報酬 研究腳本

流程:
  1. 讀取 data/stocks/*.json (大額交易人淨部位) 與 data/kline/*.json (現股收盤價)
  2. 以「現股 (sid)」為單位合併本尊與小型契約 (小型每口 100 股 = 0.05 個標準口)
  3. 建立特徵 (以 60 日滾動波動標準化) 與 T+1..T+20 前瞻報酬
  4. 三層檢驗: 每日橫斷面 IC → 五分位分組 → 逐年 walk-forward 梯度提升樹
  5. 預先固定的六條規則做歷史驗證 (全樣本 + 2024 後樣本外), 並輸出今日訊號
  6. 結果寫入 data/analysis.json, 由 analysis.html 呈現

誠實原則: 規則預先固定、模型嚴格只用過去資料、報告如實呈現強弱。
"""
import os, json, datetime
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
HORIZONS = [1, 2, 3, 4, 5, 10, 15, 20]
MIN_OI = 1000          # 流動性門檻: 本尊契約全市場未沖銷 >= 1000 口
MIN_CS = 30            # 每日橫斷面最少檔數
OOS_START = "2024/01/01"   # 規則的樣本外起點


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def log(msg):
    print(f"[{datetime.datetime.utcnow()+datetime.timedelta(hours=8):%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 資料
def build_panel():
    smap = load_json(os.path.join(DATA, "stock_map.json"))
    rows, disp = [], {}
    sdir = os.path.join(DATA, "stocks")
    for fn in sorted(os.listdir(sdir)):
        if not fn.endswith(".json"):
            continue
        doc = load_json(os.path.join(sdir, fn))
        code = doc.get("code")
        sid = doc.get("sid") or smap.get(code, {}).get("sid", "")
        name = str(doc.get("name", ""))
        if not sid:
            continue
        mini = name.startswith("小型")
        w = 0.05 if mini else 1.0
        if not mini:
            disp[sid] = {"code": code, "name": name.replace("期貨", "")}
        for d, rr in doc.get("records", {}).items():
            t0 = next((x for x in rr if x.get("month") == "999999" and x.get("type") == "0"), None)
            if not t0:
                continue
            t1 = next((x for x in rr if x.get("month") == "999999" and x.get("type") == "1"), None)
            main = (t0["top10_buy"] - t0["top10_sell"]) * w
            inst = ((t1["top10_buy"] - t1["top10_sell"]) if t1 else 0) * w
            rows.append((sid, d, main, inst, (t0.get("market_oi") or 0) * w,
                         0 if mini else (t0.get("market_oi") or 0)))
    df = pd.DataFrame(rows, columns=["sid", "date", "main", "inst", "moi_eff", "moi_reg"])
    df = df.groupby(["sid", "date"], as_index=False).sum()
    # 口徑與網站/XQ一致: rows 的 main 欄其實是前十大合計(t0);
    # 自然人 = t0 − 法人, 主力 = 自然人 − 法人
    df["nat"] = df["main"] - df["inst"]
    df["main"] = df["nat"] - df["inst"]
    log(f"部位面板: {len(df)} 列, {df.sid.nunique()} 檔")

    kl = []
    kdir = os.path.join(DATA, "kline")
    for fn in sorted(os.listdir(kdir)):
        if not fn.endswith(".json"):
            continue
        kd = load_json(os.path.join(kdir, fn))
        sid = kd.get("sid")
        for d, v in kd.get("records", {}).items():
            if v and v[3] is not None:
                kl.append((sid, d, float(v[3]), float(v[4] or 0)))
    kdf = pd.DataFrame(kl, columns=["sid", "date", "close", "vol"])
    log(f"日K面板: {len(kdf)} 列, {kdf.sid.nunique()} 檔")

    df = df.merge(kdf, on=["sid", "date"], how="inner")
    df = df.sort_values(["sid", "date"]).reset_index(drop=True)
    log(f"合併後: {len(df)} 列")
    return df, disp


def add_features(df):
    g = lambda c: df.groupby("sid", group_keys=False)[c]
    df["d_main"] = g("main").diff()
    df["d_inst"] = g("inst").diff()
    df["d_nat"] = g("nat").diff()
    for c in ["d_main", "d_inst", "d_nat"]:
        sd = g(c).transform(lambda s: s.rolling(60, min_periods=20).std())
        df[c + "_z"] = df[c] / sd.replace(0, np.nan)
    sd = g("d_main").transform(lambda s: s.rolling(60, min_periods=20).std())
    df["d_main5_z"] = g("d_main").transform(lambda s: s.rolling(5).sum()) / (sd.replace(0, np.nan) * np.sqrt(5))
    df["main_oi"] = df["main"] / df["moi_eff"].replace(0, np.nan)

    def _streak(s):
        sgn = np.sign(s.fillna(0))
        run = (sgn != sgn.shift()).cumsum()
        cnt = sgn.groupby(run).cumcount() + 1
        return sgn * cnt
    df["streak"] = df.groupby("sid", group_keys=False)["d_main"].apply(_streak)

    df["ret5"] = g("close").pct_change(5)
    vm = g("vol").transform(lambda s: s.rolling(60, min_periods=20).mean())
    vs = g("vol").transform(lambda s: s.rolling(60, min_periods=20).std())
    df["vol_z"] = (df["vol"] - vm) / vs.replace(0, np.nan)
    for k in HORIZONS:
        df[f"fwd{k}"] = g("close").shift(-k) / df["close"] - 1
    return df


# ---------------------------------------------------------------- 檢驗
FEATS = ["d_main_z", "d_inst_z", "d_nat_z", "d_main5_z", "streak", "main_oi", "vol_z", "ret5"]


def ic_table(df):
    out = {}
    for f in FEATS:
        out[f] = {}
        for k in HORIZONS:
            sub = df.dropna(subset=[f, f"fwd{k}"])
            daily = (sub.groupby("date")
                        .apply(lambda x: x[f].rank().corr(x[f"fwd{k}"].rank()) if len(x) >= MIN_CS else np.nan)
                        .dropna())
            if len(daily) < 30:
                out[f][f"T+{k}"] = None
                continue
            out[f][f"T+{k}"] = {"ic": round(float(daily.mean()), 4),
                                "t": round(float(daily.mean() / daily.std() * np.sqrt(len(daily))), 2),
                                "days": int(len(daily))}
    return out


def quintile_table(df, f="d_main_z"):
    res = {}
    sub = df.dropna(subset=[f]).copy()
    def _q(s):
        if s.notna().sum() < 50:
            return pd.Series(np.nan, index=s.index)
        try:
            return pd.qcut(s, 5, labels=False, duplicates="drop")
        except ValueError:
            return pd.Series(np.nan, index=s.index)
    sub["q"] = sub.groupby("date")[f].transform(_q)
    for k in HORIZONS:
        s2 = sub.dropna(subset=[f"fwd{k}", "q"])
        qa = s2.groupby("q")[f"fwd{k}"].mean()
        daily = (s2.groupby("date")
                   .apply(lambda x: x.loc[x.q == 4, f"fwd{k}"].mean() - x.loc[x.q == 0, f"fwd{k}"].mean())
                   .dropna())
        res[f"T+{k}"] = {"q_avg_bp": [round(float(v) * 1e4, 1) for v in qa.tolist()],
                         "spread_bp": round(float(daily.mean()) * 1e4, 1),
                         "t": round(float(daily.mean() / daily.std() * np.sqrt(len(daily))), 2)}
    return res


def walk_forward(df):
    """逐年 walk-forward: 只用當年以前的資料訓練, 預測當年; 回報預測值的每日 rank IC。"""
    try:
        from lightgbm import LGBMRegressor
        mk = lambda: LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31,
                                   subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1)
        lib = "lightgbm"
    except Exception:
        from sklearn.ensemble import HistGradientBoostingRegressor
        mk = lambda: HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=42)
        lib = "sklearn-HGB"
    out = {"lib": lib, "horizons": {}}
    df = df.copy()
    df["year"] = df["date"].str[:4].astype(int)
    years = sorted(df["year"].unique())
    test_years = [y for y in years if y >= 2021]
    imp_acc = {}
    for k in HORIZONS:
        ics = []
        for y in test_years:
            tr = df[(df.year < y)].dropna(subset=FEATS + [f"fwd{k}"])
            te = df[(df.year == y)].dropna(subset=FEATS + [f"fwd{k}"])
            if len(tr) < 5000 or len(te) < 500:
                continue
            m = mk()
            m.fit(tr[FEATS], tr[f"fwd{k}"])
            te = te.copy()
            te["pred"] = m.predict(te[FEATS])
            daily = (te.groupby("date")
                       .apply(lambda x: x["pred"].rank().corr(x[f"fwd{k}"].rank()) if len(x) >= MIN_CS else np.nan)
                       .dropna())
            if len(daily):
                ics.append(daily)
            if hasattr(m, "feature_importances_"):
                imp = dict(zip(FEATS, m.feature_importances_.tolist()))
                for f2, v in imp.items():
                    imp_acc[f2] = imp_acc.get(f2, 0) + float(v)
        if ics:
            allic = pd.concat(ics)
            out["horizons"][f"T+{k}"] = {"ic": round(float(allic.mean()), 4),
                                         "t": round(float(allic.mean() / allic.std() * np.sqrt(len(allic))), 2),
                                         "days": int(len(allic))}
        else:
            out["horizons"][f"T+{k}"] = None
    tot = sum(imp_acc.values()) or 1
    out["importance"] = {f2: round(v / tot, 3) for f2, v in sorted(imp_acc.items(), key=lambda x: -x[1])}
    return out


RULES = [
    ("R1 主力大幅增倉",   lambda d: d["d_main_z"] >= 2),
    ("R2 主力連3日增倉且5日累積顯著", lambda d: (d["streak"] >= 3) & (d["d_main5_z"] >= 1.5)),
    ("R3 法人大幅增倉",   lambda d: d["d_inst_z"] >= 2),
    ("R4 主力大幅減倉",   lambda d: d["d_main_z"] <= -2),
    ("R5 主力連3日減倉且5日累積顯著", lambda d: (d["streak"] <= -3) & (d["d_main5_z"] <= -1.5)),
    ("R6 法人大幅減倉",   lambda d: d["d_inst_z"] <= -2),
]


def rule_stats(df):
    out = []
    base = {}
    for k in HORIZONS:
        base[f"T+{k}"] = round(float(df[f"fwd{k}"].mean()) * 1e4, 1)
    for name, cond in RULES:
        mask = cond(df).fillna(False)
        row = {"name": name, "n": int(mask.sum()), "windows": {}}
        for win, sub in (("全樣本", df[mask]), (f"{OOS_START[:4]}後", df[mask & (df["date"] >= OOS_START)])):
            w = {}
            for k in HORIZONS:
                s = sub[f"fwd{k}"].dropna()
                if len(s) < 30:
                    w[f"T+{k}"] = None
                    continue
                w[f"T+{k}"] = {"avg_bp": round(float(s.mean()) * 1e4, 1),
                               "hit": round(float((s > 0).mean()) * 100, 1),
                               "n": int(len(s))}
            row["windows"][win] = w
        out.append(row)
    return {"baseline_bp": base, "rules": out}


def today_signals(df, disp):
    latest = df["date"].max()
    cur = df[df["date"] == latest]
    sig = []
    for name, cond in RULES:
        m = cond(cur).fillna(False)
        for _, r in cur[m].iterrows():
            d = disp.get(r["sid"], {})
            sig.append({"rule": name, "sid": r["sid"], "code": d.get("code", ""),
                        "name": d.get("name", r["sid"]),
                        "d_main_z": round(float(r["d_main_z"]), 2) if pd.notna(r["d_main_z"]) else None,
                        "streak": int(r["streak"]) if pd.notna(r["streak"]) else None})
    return {"date": latest, "list": sig}


def main():
    log("載入資料…")
    df, disp = build_panel()
    df = add_features(df)
    uni = df[df["moi_reg"] >= MIN_OI].copy()
    log(f"通過流動性門檻: {len(uni)} 列, {uni.sid.nunique()} 檔, {uni.date.nunique()} 日")

    log("計算 IC…")
    ic = ic_table(uni)
    log("五分位…")
    q_main = quintile_table(uni, "d_main_z")
    q_inst = quintile_table(uni, "d_inst_z")
    log("walk-forward 模型…")
    wf = walk_forward(uni)
    log("規則驗證…")
    rs = rule_stats(uni)
    sig = today_signals(uni, disp)

    out = {"generated_at": (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).isoformat(timespec="seconds") + "+08:00",
           "universe": {"rows": int(len(uni)), "stocks": int(uni.sid.nunique()),
                        "dates": int(uni.date.nunique()),
                        "from": uni.date.min(), "to": uni.date.max(), "min_oi": MIN_OI},
           "ic": ic, "quintile_main": q_main, "quintile_inst": q_inst,
           "walk_forward": wf, "rules": rs, "signals": sig}
    with open(os.path.join(DATA, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log("完成 → data/analysis.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
