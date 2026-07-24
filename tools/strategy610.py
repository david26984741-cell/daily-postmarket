# -*- coding: utf-8 -*-
"""
主力 第6~10大 多空固定10檔 H3 策略 — 每日部位追蹤器 資料產生器
讀 data/stocks + data/fkline(退回 kline) + data/txf.json → 產出 data/strategy610.json
供 strategy.html 渲染(今日進場/目前部位/口數資金/YTD走勢圖 vs 台指)。
不對外連線、不改動其它資料;純讀 repo 內既有檔案後寫出單一 JSON。

口徑(與網站/回測一致):
  a10=前十大交易人淨(type0), a5=前五大交易人淨, s10=前十大特定法人淨(type1), s5=前五大特定法人淨
  第6~10大: a610=a10-a5, s610=s10-s5
  主力6-10 比率 = (a610 - 2*s610) / market_oi
  規模 value = market_oi * 收盤價 * 每口股數(小型100/一般2000);甜蜜區 2.5億~100億
策略: 每日取比率最高10檔做多、最低10檔做空;固定各10檔;持有3天(H3, 三批重疊)。
價格基準: 股期近月(fkline)優先,缺漏退回現股(kline)。
"""
import os, json, glob, math
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT  = os.path.join(DATA, "strategy610.json")

YEAR_START = "2026/01/02"      # 抓今年年初到現在
VMIN, VMAX = 2.5e8, 1e10       # 規模甜蜜區(元)
H = 3                          # 持有天數
NLEG = 10                      # 多空各固定10檔
MARGIN_RATE = 0.135            # 股票期貨保證金 估算(等級1 約13.5%)

# ---- 回測績效(來自我們的系列研究,毛值;股期報價,2017~2026 全樣本)----
BACKTEST = {
    "period": "2017/07 ~ 2026/07(約9年)",
    "ann": 43.1, "sharpe": 2.43, "t": 6.2, "mdd": -16.5, "win": None,
    "note": "純多空、固定各10檔、H3;報酬為多空對沖(金額中性)毛報酬,未扣摩擦成本。"
}

def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def build():
    # ---------- 部位資料(大額交易人)----------
    rows = []
    names = {}
    for f in sorted(glob.glob(os.path.join(DATA, "stocks", "*.json"))):
        d = load(f)
        code = d.get("code"); name = str(d.get("name", "")); sid = d.get("sid")
        if not code:
            continue
        mini = name.startswith("小型")
        shares = 100 if mini else 2000
        names[code] = {"name": name, "sid": sid, "mini": mini, "shares": shares}
        for dt, recs in d["records"].items():
            if dt < "2025/12/01":          # 只需近端(算YTD報酬留一點前置)
                continue
            t0 = next((x for x in recs if x.get("month") == "999999" and x.get("type") == "0"), None)
            t1 = next((x for x in recs if x.get("month") == "999999" and x.get("type") == "1"), None)
            if not t0:
                continue
            moi = t0.get("market_oi") or 0
            if not moi:
                continue
            a5 = t0["top5_buy"] - t0["top5_sell"]; a10 = t0["top10_buy"] - t0["top10_sell"]
            s5 = (t1["top5_buy"] - t1["top5_sell"]) if t1 else 0
            s10 = (t1["top10_buy"] - t1["top10_sell"]) if t1 else 0
            rows.append((code, dt, moi, a5, a10, s5, s10, shares))
    pos = pd.DataFrame(rows, columns=["code", "date", "moi", "a5", "a10", "s5", "s10", "shares"])

    # ---------- 價格(股期優先,退回現股)----------
    px = []
    for code in names:
        fp = os.path.join(DATA, "fkline", code + ".json")
        rec = {}
        if os.path.exists(fp):
            for dt, v in load(fp).get("records", {}).items():
                if v and v[3] is not None:
                    rec[dt] = (float(v[3]), "股期")
        sid = names[code]["sid"]
        kp = os.path.join(DATA, "kline", str(sid) + ".json")
        if os.path.exists(kp):
            for dt, v in load(kp).get("records", {}).items():
                if dt not in rec and v and v[3] is not None:
                    rec[dt] = (float(v[3]), "股價")
        for dt, (c, src) in rec.items():
            if dt >= "2025/12/01":
                px.append((code, dt, c, src))
    price = pd.DataFrame(px, columns=["code", "date", "close", "psrc"])

    df = pos.merge(price, on=["code", "date"], how="inner").sort_values(["code", "date"])
    df["ratio"] = ((df.a10 - df.a5) - 2 * (df.s10 - df.s5)) / df.moi
    df["value"] = df.moi * df.close * df.shares
    df["ret1"] = df.groupby("code")["close"].pct_change()
    # 股期/現股基差:前後兩天不同來源會製造假跳空 → 跨來源當天報酬不計
    prevsrc = df.groupby("code")["psrc"].shift()
    df.loc[df.psrc != prevsrc, "ret1"] = np.nan

    # ---------- 每日訊號(在甜蜜區內,依比率排名)----------
    uni = df[(df.value >= VMIN) & (df.value < VMAX)].copy()
    dates = sorted(uni.date.unique())
    sig = {}   # date -> (long codes[], short codes[], ratio map)
    for d, g in uni.groupby("date"):
        o = g.sort_values("ratio", ascending=False)
        L = list(o.head(NLEG).code); S = list(o.tail(NLEG).code)
        rmap = dict(zip(g.code, g.ratio))
        sig[d] = (L, S, rmap)

    # 報酬對照表(當日各碼 ret1)
    retmap = {d: dict(zip(g.code, g.ret1)) for d, g in df.groupby("date")}
    # 最新股期價 & 來源(給今日/部位/口數用)
    last_close = {}; last_src = {}
    for code, g in df.groupby("code"):
        g2 = g.dropna(subset=["close"])
        if len(g2):
            last_close[code] = float(g2.close.iloc[-1]); last_src[code] = g2.psrc.iloc[-1]

    # ---------- YTD 每日策略報酬(H3 三批重疊, 多空對沖)----------
    ytd = [d for d in dates if d >= YEAR_START]
    didx = {d: i for i, d in enumerate(dates)}
    eq_dates, eq_strat, drets = [], [], []
    cum = 1.0
    for d in ytd:
        i = didx[d]
        actL, actS = [], []
        for k in (1, 2, 3):                       # 前1~3個訊號日進場、於今日仍在持有
            j = i - k
            if j >= 0:
                actL += sig[dates[j]][0]; actS += sig[dates[j]][1]
        rm = retmap.get(d, {})
        lr = [rm[c] for c in actL if c in rm and rm[c] == rm[c]]
        sr = [rm[c] for c in actS if c in rm and rm[c] == rm[c]]
        r = 0.0
        if lr and sr:
            r = float(np.mean(lr) - np.mean(sr))
            cum *= (1 + r)
        drets.append(r)
        eq_dates.append(d); eq_strat.append(round((cum - 1) * 100, 3))
    dr = np.array(drets)
    ytd_summary = {
        "ret": round((cum - 1) * 100, 1),
        "vol": round(float(dr.std() * np.sqrt(252) * 100), 1) if len(dr) > 1 else None,
        "sharpe": round(float(dr.mean() / dr.std() * np.sqrt(252)), 2) if dr.std() > 0 else None,
        "days": len(dr),
    }

    # ---------- 台指期 YTD 累積 ----------
    txf = load(os.path.join(DATA, "txf.json"))["records"]
    base_txf = None; eq_txf = []
    for d in eq_dates:
        if d in txf:
            if base_txf is None:
                base_txf = txf[d]
            eq_txf.append(round((txf[d] / base_txf - 1) * 100, 3))
        else:
            eq_txf.append(eq_txf[-1] if eq_txf else 0.0)

    # ---------- 目前部位 / 今日進場 / 口數資金 ----------
    latest = dates[-1]
    has_mini = set()   # sid 有小型可交易
    for c, m in names.items():
        if m["mini"]:
            has_mini.add(m["sid"])

    def unit_size(code):
        """單口可交易規模:若該標的有小型則用小型(100股),否則一般(2000股)。"""
        m = names[code]; use_mini = (m["sid"] in has_mini) or m["mini"]
        sh = 100 if use_mini else 2000
        pr = last_close.get(code)
        return sh, pr, use_mini

    def size_basket(items):
        """items: list of (code, dir, count). 以『每口名目盡量相等』求各檔最少口數。"""
        rowsout = []; per_lot = {}
        for code, dr, cnt in items:
            sh, pr, um = unit_size(code)
            if pr is None:
                continue
            per_lot[code] = pr * sh
        if not per_lot:
            return [], 0.0, 0.0
        base = max(per_lot.values())          # 以最貴的單口為基準=每單位1口
        tot_notional = 0.0
        for code, dr, cnt in items:
            if code not in per_lot:
                continue
            sh, pr, um = unit_size(code)
            lots_unit = max(1, round(base / per_lot[code]))
            lots = lots_unit * cnt            # 被選 cnt 次 => cnt 個單位
            notion = lots * per_lot[code]
            tot_notional += notion
            rowsout.append({
                "code": code, "name": names[code]["name"], "dir": dr, "count": cnt,
                "price": round(pr, 2), "src": last_src.get(code, ""),
                "mini": um, "shares": sh, "lots": int(lots),
                "notional": int(round(notion)), "margin": int(round(notion * MARGIN_RATE)),
            })
        rowsout.sort(key=lambda x: (x["dir"] != "多", -x["notional"]))
        return rowsout, tot_notional, tot_notional * MARGIN_RATE

    # 今日進場(latest 訊號的多空各10檔, 每檔算 1 單位)
    Lt, St, rmt = sig[latest]
    today_items = [(c, "多", 1) for c in Lt] + [(c, "空", 1) for c in St]
    today_rows, today_notional, today_margin = size_basket(today_items)
    for r in today_rows:
        r["ratio"] = round(float(rmt.get(r["code"], float("nan"))), 4)

    # 目前部位(H3: latest 及前2個訊號日的聯集, count=被選次數)
    win = [dates[i] for i in range(len(dates) - H, len(dates)) if i >= 0]
    cL, cS = {}, {}
    for d in win:
        for c in sig[d][0]:
            cL[c] = cL.get(c, 0) + 1
        for c in sig[d][1]:
            cS[c] = cS.get(c, 0) + 1
    pos_items = [(c, "多", n) for c, n in cL.items()] + [(c, "空", n) for c, n in cS.items()]
    pos_rows, pos_notional, pos_margin = size_basket(pos_items)

    # ---------- 過往(每個交易日的訊號+部位, 供下拉選單)----------
    history = {}
    for idx, d in enumerate(ytd):
        i = didx[d]
        L, S, rm = sig[d]
        # 該日部位(當日+前2訊號日)
        w = [dates[k] for k in range(i - H + 1, i + 1) if k >= 0]
        hcL, hcS = {}, {}
        for wd in w:
            for c in sig[wd][0]:
                hcL[c] = hcL.get(c, 0) + 1
            for c in sig[wd][1]:
                hcS[c] = hcS.get(c, 0) + 1
        history[d] = {
            "L": [[c, round(float(rm[c]), 4)] for c in L],
            "S": [[c, round(float(rm[c]), 4)] for c in S],
            "posL": sorted(hcL.items(), key=lambda x: -x[1]),
            "posS": sorted(hcS.items(), key=lambda x: -x[1]),
        }

    name_map = {c: {"name": names[c]["name"], "mini": (names[c]["sid"] in has_mini) or names[c]["mini"]}
                for c in names}

    out = {
        "updated": latest,
        "criteria": {
            "universe": "股票期貨 · 規模 2.5億~100億(市場未沖銷×股期價×每口股數)",
            "signal": "主力第6~10大淨部位比率 =（(前十大−前五大交易人) − 2×(前十大−前五大特定法人)) ÷ 全市場未沖銷",
            "rule": "每日比率最高10檔做多、最低10檔做空(固定各10檔),持有3天(H3,三批重疊)。",
            "price": "股期近月報價優先,缺漏退回現股收盤。",
            "margin": f"保證金為估算(名目×{int(MARGIN_RATE*100)}%,股票期貨等級1)。",
        },
        "backtest": BACKTEST,
        "today": {"date": latest, "rows": today_rows,
                  "notional": int(round(today_notional)), "margin": int(round(today_margin))},
        "positions": {"rows": pos_rows, "notional": int(round(pos_notional)),
                      "margin": int(round(pos_margin)),
                      "n": len(pos_rows), "window": win},
        "equity": {"dates": eq_dates, "strategy": eq_strat, "txf": eq_txf},
        "ytd": ytd_summary,
        "history": history,
        "names": name_map,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", OUT)
    print("updated", latest, "| ytd days", len(eq_dates),
          "| strat cum%", eq_strat[-1] if eq_strat else None,
          "| txf cum%", eq_txf[-1] if eq_txf else None)
    print("today long", [r["code"] for r in today_rows if r["dir"] == "多"])
    print("today short", [r["code"] for r in today_rows if r["dir"] == "空"])
    print("positions", len(pos_rows), "| 名目", out["positions"]["notional"],
          "| 保證金", out["positions"]["margin"])

if __name__ == "__main__":
    build()
