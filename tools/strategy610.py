# -*- coding: utf-8 -*-
"""
主力 第6~10大 多空固定10檔 策略(去重 + 滾動續抱 + 隔日開盤進)— 每日部位追蹤 + 回測 資料產生器
讀 data/stocks + data/fkline(退回 kline) + data/txf.json → 產出 data/strategy610.json
供 strategy.html 渲染(今日進場 / 目前部位 / 資金 / 今年走勢 / 歷史資料[全期走勢+逐年+績效])。
純讀 repo 內既有資料、不對外連線。

口徑:主力6-10 比率 = ((前十大−前五大交易人) − 2×(前十大−前五大特定法人)) / 全市場未沖銷。
選股池:股票期貨、規模 2.5億~100億。每日取比率最高10檔多、最低10檔空。
進出場(去重+滾動):某檔入榜→隔一個交易日以【開盤價】買進;持有3個交易日,期間內再度入榜即把出場日重設為
  「最後一次入榜日+3個交易日」(續抱、不重複買進);連續3日未入榜於第3日【收盤】賣出;賣出後再入榜隔日開盤重買。
價格每筆整筆同一來源:股期近月優先,缺漏退現股。成本忽略。
"""
import os, json, glob
from collections import defaultdict
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT  = os.path.join(DATA, "strategy610.json")
VMIN, VMAX, H = 2.5e8, 1e10, 3
MARGIN_RATE = 0.135

def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def build():
    smap = load(os.path.join(DATA, "stock_map.json"))
    rows = []; names = {}; sidmap = {}; mini_of = {}
    for f in sorted(glob.glob(os.path.join(DATA, "stocks", "*.json"))):
        d = load(f); code = d.get("code"); nm = str(d.get("name", ""))
        if not code: continue
        sid = d.get("sid") or smap.get(code, {}).get("sid", "")
        mini = nm.startswith("小型"); names[code] = nm; sidmap[code] = sid; mini_of[code] = mini
        shares = 100 if mini else 2000
        for dt, recs in d["records"].items():
            t0 = next((x for x in recs if x.get("month") == "999999" and x.get("type") == "0"), None)
            t1 = next((x for x in recs if x.get("month") == "999999" and x.get("type") == "1"), None)
            if not t0: continue
            moi = t0.get("market_oi") or 0
            if not moi: continue
            a5 = t0["top5_buy"] - t0["top5_sell"]; a10 = t0["top10_buy"] - t0["top10_sell"]
            s5 = (t1["top5_buy"] - t1["top5_sell"]) if t1 else 0
            s10 = (t1["top10_buy"] - t1["top10_sell"]) if t1 else 0
            rows.append((code, dt, moi, a5, a10, s5, s10, shares))
    pos = pd.DataFrame(rows, columns=["code", "date", "moi", "a5", "a10", "s5", "s10", "shares"])
    # 價格 open/close
    fko = {}; fkc = {}; klo = {}; klc = {}
    for code in names:
        fp = os.path.join(DATA, "fkline", code + ".json")
        if os.path.exists(fp):
            for dt, v in load(fp).get("records", {}).items():
                if v and v[0] is not None and v[3] is not None:
                    fko[(code, dt)] = float(v[0]); fkc[(code, dt)] = float(v[3])
        kp = os.path.join(DATA, "kline", str(sidmap[code]) + ".json")
        if os.path.exists(kp):
            for dt, v in load(kp).get("records", {}).items():
                if v and v[0] is not None and v[3] is not None:
                    klo[(code, dt)] = float(v[0]); klc[(code, dt)] = float(v[3])
    def sig_px(c, dt):
        v = fkc.get((c, dt)); return v if v is not None else klc.get((c, dt))
    pos["price"] = [sig_px(c, d) for c, d in zip(pos.code, pos.date)]
    pos = pos.dropna(subset=["price"])
    pos["ratio"] = ((pos.a10 - pos.a5) - 2 * (pos.s10 - pos.s5)) / pos.moi
    pos["value"] = pos.moi * pos.price * pos.shares
    uni = pos[(pos.value >= VMIN) & (pos.value < VMAX)].copy()
    dates = sorted(pos.date.unique()); didx = {d: i for i, d in enumerate(dates)}; ND = len(dates)
    T = ND - 1  # 最新訊號日索引
    sigL = defaultdict(list); sigS = defaultdict(list); ratio_at = {}
    lastclose = {}; lastsrc = {}
    for d, g in uni.groupby("date"):
        o = g.sort_values("ratio", ascending=False); i = didx[d]
        for c in o.head(10).code: sigL[c].append(i)
        for c in o.tail(10).code: sigS[c].append(i)
        for c, rr in zip(g.code, g.ratio): ratio_at[(c, i)] = rr
    for c, g in pos.groupby("code"):
        g2 = g.dropna(subset=["price"])
        if len(g2): lastclose[c] = float(g2.price.iloc[-1]); lastsrc[c] = "股期" if (c, g2.date.iloc[-1]) in fkc else "現股"

    def trade_px(code, ed, xd):
        if (code, ed) in fko and (code, xd) in fkc: return fko[(code, ed)], fkc[(code, xd)], "股期"
        if (code, ed) in klo and (code, xd) in klc: return klo[(code, ed)], klc[(code, xd)], "現股"
        return None, None, None
    def cget(code, dt, src): return (fkc if src == "股期" else klc).get((code, dt))
    def oget(code, dt, src): return (fko if src == "股期" else klo).get((code, dt))

    # ---- 去重+滾動 引擎:產生 streak(部位),分類 已平倉/持有中/今日待進 ----
    dl = defaultdict(list); ds = defaultdict(list)   # 每日多/空 當日報酬(給淨值)
    held = []      # 目前持倉(已買進、未出場)
    todaynew = []  # 今日新入榜(隔日開盤買)
    for dr, sm in (("多", sigL), ("空", sigS)):
        for code, sigs in sm.items():
            sigs = sorted(sigs); k = 0
            while k < len(sigs):
                start = sigs[k]; last = sigs[k]; exit_t = last + H; j = k + 1
                while j < len(sigs) and sigs[j] < exit_t:
                    last = sigs[j]; exit_t = last + H; j += 1
                k = j
                ent = start + 1                       # 隔日開盤進
                xit_raw = last + H                    # 最後入榜+3 收盤出
                if ent >= ND:
                    # 今日(最新日)新入榜、尚未進場 → 待買
                    if start == T:
                        todaynew.append((code, dr, ratio_at.get((code, start), float("nan"))))
                    continue
                xit = min(xit_raw, ND - 1)
                # 淨值:當日報酬(進場日 開→收;其後 收→收)
                src = "股期" if ((code, dates[ent]) in fko and (code, dates[xit]) in fkc) else "現股"
                prev_c = None
                for m in range(ent, xit + 1):
                    d = dates[m]; c = cget(code, d, src)
                    if c is None: continue
                    if m == ent:
                        o = oget(code, d, src)
                        if not o: prev_c = c; continue
                        r = c / o - 1
                    else:
                        if not prev_c: prev_c = c; continue
                        r = c / prev_c - 1
                    prev_c = c
                    (dl if dr == "多" else ds)[d].append(r)
                # 持有中?(已買進 ent<=T 且尚未出場 xit_raw>T)
                if ent <= T and xit_raw > T:
                    held.append({"code": code, "dir": dr, "entry": dates[ent], "last": dates[last],
                                 "days": T - ent + 1})
    # ---- 淨值序列(全期 多空對沖)----
    recs = []
    for d in dates:
        L = dl.get(d); S = ds.get(d)
        if L and S: recs.append((d, float(np.mean(L) - np.mean(S))))
    eq = pd.DataFrame(recs, columns=["date", "r"]).set_index("date")
    r = eq.r; cum = (1 + r).cumprod()
    def stats(x):
        x = x.dropna()
        if len(x) < 20: return None
        c = (1 + x).cumprod(); cum_ = c.iloc[-1] - 1; ann = c.iloc[-1] ** (252 / len(x)) - 1
        vol = x.std() * np.sqrt(252); mdd = (c / c.cummax() - 1).min()
        return {"ann": round(float(ann * 100), 1), "cum": round(float(cum_ * 100), 1),
                "vol": round(float(vol * 100), 1), "sharpe": round(float(ann / vol), 2),
                "sharpe_cum": round(float(cum_ / (vol if vol else 1)), 2),
                "t": round(float(x.mean() / x.std() * np.sqrt(len(x))), 1),
                "mdd": round(float(mdd * 100), 1), "days": len(x)}
    full = stats(r); full["total"] = round(float((cum.iloc[-1] - 1) * 100), 0); full["period"] = f"{r.index[0]} ~ {r.index[-1]}"
    yrmask = pd.Index([d[:4] for d in r.index])
    _y = stats(r[yrmask == "2026"])
    # 今年以來:顯示【累積】報酬(年化會把5個月放大失真),Sharpe 用 累積/年化波動
    ytd = {"ret": _y["cum"], "sharpe": _y["sharpe_cum"], "t": _y["t"], "mdd": _y["mdd"], "vol": _y["vol"], "days": _y["days"]}
    yearly = []
    for y in sorted(set(yrmask)):
        s = stats(r[yrmask == y])
        if s: yearly.append({"year": y, "cum": s["cum"], "sharpe": s["sharpe_cum"], "t": s["t"], "mdd": s["mdd"], "days": s["days"]})
    # 全期/YTD 累積%(給圖)
    eqd = list(r.index); eqs = [round(float(v), 3) for v in (cum - 1) * 100]
    ytd_idx = [i for i, d in enumerate(eqd) if d >= "2026/01/02"]
    txf = load(os.path.join(DATA, "txf.json"))["records"]
    def txf_series(ds_):
        base = None; out = []
        for d in ds_:
            if d in txf:
                if base is None: base = txf[d]
                out.append(round((txf[d] / base - 1) * 100, 3))
            else:
                out.append(None)
        return out
    equity_full = {"dates": eqd, "strategy": eqs, "txf": txf_series(eqd)}
    yd = [eqd[i] for i in ytd_idx]
    yc = (1 + r[[eqd[i] for i in ytd_idx]]).cumprod() if ytd_idx else pd.Series(dtype=float)
    equity_ytd = {"dates": yd, "strategy": [round(float(v), 3) for v in (yc - 1) * 100], "txf": txf_series(yd)}

    # ---- 資金/口數(股期優先,有小型用小型)----
    has_mini = set(sidmap[c] for c in names if mini_of[c])
    def unit(code):
        um = (sidmap[code] in has_mini) or mini_of[code]
        return (100 if um else 2000), lastclose.get(code), um
    def basket(items):
        per = {}
        for code, dr, extra in items:
            sh, pr, um = unit(code)
            if pr: per[code] = pr * sh
        if not per: return [], 0.0
        base = max(per.values()); out = []; tot = 0.0
        for code, dr, extra in items:
            if code not in per: continue
            sh, pr, um = unit(code); lots = max(1, round(base / per[code])); notion = lots * per[code]; tot += notion
            row = {"code": code, "name": names[code], "dir": dr, "price": round(pr, 2),
                   "src": lastsrc.get(code, ""), "mini": um, "shares": sh, "lots": int(lots),
                   "notional": int(round(notion)), "margin": int(round(notion * MARGIN_RATE))}
            row.update(extra); out.append(row)
        out.sort(key=lambda x: (x["dir"] != "多", -x["notional"]))
        return out, tot
    tn_items = [(c, dr, {"ratio": round(float(rt), 4)}) for c, dr, rt in todaynew]
    today_rows, today_not = basket(tn_items)
    hb_items = [(h["code"], h["dir"], {"entry": h["entry"], "held": h["days"], "last": h["last"]}) for h in held]
    pos_rows, pos_not = basket(hb_items)

    out = {
        "updated": dates[T],
        "criteria": {
            "universe": "股票期貨 · 規模 2.5億~100億(市場未沖銷 × 股期價 × 每口股數)",
            "signal": "主力第6~10大淨部位比率 =（(前十大−前五大交易人) − 2×(前十大−前五大特定法人)) ÷ 全市場未沖銷",
            "rule": "每日比率最高10檔做多、最低10檔做空(固定各10檔)。去重+滾動:某檔入榜→隔日開盤買進,持有3個交易日;期間內再度入榜即續抱(出場日重設為末次入榜+3日、不重複買進);連續3日未入榜於第3日收盤賣出,之後再入榜隔日重買。",
            "price": "進場=隔日開盤價、出場=收盤價;股期近月優先,缺漏退現股。",
            "margin": f"保證金為估算(名目×{int(MARGIN_RATE*100)}%,股票期貨等級1)。成本(股期)極低忽略。",
        },
        "backtest": {"period": full["period"] + "(約9年)", "ann": full["ann"], "sharpe": full["sharpe"],
                     "t": full["t"], "mdd": full["mdd"], "total": full["total"], "vol": full["vol"],
                     "note": "多空對沖(金額中性)毛報酬,隔日開盤進、去重滾動續抱,未扣摩擦成本。"},
        "ytd": ytd,
        "today": {"rows": today_rows, "notional": int(round(today_not)), "margin": int(round(today_not * MARGIN_RATE))},
        "positions": {"rows": pos_rows, "notional": int(round(pos_not)), "margin": int(round(pos_not * MARGIN_RATE)), "n": len(pos_rows)},
        "equity_ytd": equity_ytd,
        "equity_full": equity_full,
        "yearly": yearly,
        "names": {c: {"name": names[c]} for c in names},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("updated", dates[T], "| 全期年化", full["ann"], "Sharpe", full["sharpe"], "t", full["t"], "MDD", full["mdd"], "total", full["total"])
    print("YTD", ytd)
    print("今日新進場", len(today_rows), "檔 | 名目", out["today"]["notional"], "保證金", out["today"]["margin"])
    print("目前部位", len(pos_rows), "檔 | 名目", out["positions"]["notional"], "保證金", out["positions"]["margin"])
    print("equity full pts", len(eqd), "| ytd pts", len(yd))

if __name__ == "__main__":
    build()
