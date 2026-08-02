#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""選擇權籌碼 — OI 金額變化分布圖 (每日報告附圖)。

柱狀 = 該履約價「今日 OI 增減口數 × 今日結算價 × 50 元/點」= OI 金額變化。
CALL 在左(紅)、PUT 在右(綠);標籤 = 金額 (增減口數)。減少 = 負向柱。

四個關鍵數字 (價差 = 台指期收盤 − 加權指數收盤):
  K1 = CALL OI金額增加最大之履約價 + 價差 + 該履約價結算價
  K2 = 同上, 第二大
  K3 = PUT  OI金額增加最大之履約價 + 價差 − 該履約價結算價
  K4 = 同上, 第二大

用法:
  取樣測試: python tools/optchips.py --input rows.json --tx 43678 --taiex 43119.75 \
             --date 2026/07/31 --expiry 202608W1 --out .shots
  正式抓取: python tools/optchips.py --fetch --out .shots   (在 GitHub runner 執行)

rows.json 格式: [[履約價, ΔC口, C結算, C收盤, ΔP口, P結算, P收盤], ...]
"""
import os, json, argparse, urllib.request, urllib.parse, datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BG, PANEL, GRID, TXT, MUT = "#0f1620", "#131a24", "#243040", "#e6edf3", "#9aa7b4"
UP, DN = "#ff6b6b", "#4ade80"
UP_F, DN_F = "#6e3138", "#2a4d3c"     # 減少(淡色)
PT = 50                                # TXO 每點 50 元
MIN_AMT = 3e5                          # 圖面過濾: 兩邊 |OI金額變化| 皆 < 30萬 的履約價不畫 (雜訊)

for _f in ("Noto Sans CJK TC", "Noto Sans CJK JP", "Noto Sans CJK SC"):
    try:
        matplotlib.font_manager.findfont(_f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [_f]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


def f_e(v):
    a = abs(v)
    s = "+" if v > 0 else ("-" if v < 0 else "")
    if a >= 1e8:
        return f"{s}{a/1e8:.2f}億"
    if a >= 1e4:
        return f"{s}{a/1e4:.0f}萬"
    return f"{s}{a:.0f}"


# ------------------------------------------------------------------ 抓取 (runner 用)
UA = "Mozilla/5.0"


def _post(url, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("big5", errors="replace")


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_all():
    """回傳 (date_slash, expiry, rows, tx_close, taiex_close)。
    到期別 = 週三選(W)/週五選(F)/月選 中「最早到期且尚未到期」者。"""
    today = datetime.datetime.utcnow() + datetime.timedelta(hours=8)   # 台北
    start = today - datetime.timedelta(days=9)
    q = lambda d: d.strftime("%Y/%m/%d")

    txo = _post("https://www.taifex.com.tw/cht/3/optDataDown",
                {"down_type": "1", "commodity_id": "TXO",
                 "queryStartDate": q(start), "queryEndDate": q(today)})
    lines = [[c.strip() for c in l.split(",")] for l in txo.splitlines()[1:] if l.strip()]
    lines = [c for c in lines if len(c) > 20 and c[17] == "一般"]
    dates = sorted({c[0] for c in lines})
    if len(dates) < 2:
        raise RuntimeError("TXO 資料不足兩個交易日")
    d1, d0 = dates[-1], dates[-2]

    exps = {}
    for c in (x for x in lines if x[0] == d1):
        exps.setdefault(c[2], c[20])
    live = sorted(((e, x) for e, x in exps.items() if x > d1.replace("/", "")),
                  key=lambda t: t[1])
    if not live:
        raise RuntimeError("找不到未到期契約")
    expiry = live[0][0]

    def collect(day):
        m = {}
        num = lambda s: float(s) if s not in ("-", "") else None
        for c in lines:
            if c[0] != day or c[2] != expiry:
                continue
            k = float(c[3])
            cp = "C" if c[4] == "買權" else "P"
            m.setdefault(k, {})[cp] = {"s": num(c[10]) or 0, "c": num(c[8]),
                                       "oi": int(float(c[11] or 0))}
        return m

    t, p = collect(d1), collect(d0)
    rows = []
    for k in sorted(set(t) | set(p)):
        tc, tp = t.get(k, {}).get("C", {}), t.get(k, {}).get("P", {})
        pc, pp = p.get(k, {}).get("C", {}), p.get(k, {}).get("P", {})
        rows.append([k,
                     (tc.get("oi") or 0) - (pc.get("oi") or 0), tc.get("s") or 0, tc.get("c"),
                     (tp.get("oi") or 0) - (pp.get("oi") or 0), tp.get("s") or 0, tp.get("c")])

    tx = _post("https://www.taifex.com.tw/cht/3/futDataDown",
               {"down_type": "1", "commodity_id": "TX",
                "queryStartDate": d1, "queryEndDate": d1})
    hdr = [h.strip() for h in tx.splitlines()[0].split(",")]
    iC, iV, iS = hdr.index("收盤價"), hdr.index("成交量"), hdr.index("交易時段")
    best = None
    for l in tx.splitlines()[1:]:
        c = [x.strip() for x in l.split(",")]
        if len(c) <= max(iC, iV, iS) or c[1] != "TX" or not (c[2].isdigit() and len(c[2]) == 6):
            continue
        if c[iS] and c[iS] != "一般":
            continue
        v = int(float(c[iV] or 0))
        if best is None or v > best[0]:
            best = (v, float(c[iC]))

    ymd = d1.replace("/", "")
    j = _get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=IND&response=json")
    data = (j.get("tables") or [{}])[0].get("data") or j.get("data") or []
    taiex = next(float(r[1].replace(",", "")) for r in data if "發行量加權股價指數" in r[0])
    return d1, expiry, rows, best[1], taiex


# ------------------------------------------------------------------ 產圖
def render(date, expiry, rows, tx_close, taiex, out, fname="6_選擇權籌碼.png"):
    basis = tx_close - taiex
    calc = [{"k": k, "dC": dC, "Cs": Cs, "dP": dP, "Ps": Ps,
             "cAmt": dC * Cs * PT, "pAmt": dP * Ps * PT}
            for k, dC, Cs, Cc, dP, Ps, Pc in rows]

    # 關鍵數字: 以「OI 金額增加」由大到小 (只取正向增加)
    cTop3 = sorted((r for r in calc if r["cAmt"] > 0), key=lambda r: -r["cAmt"])[:3]
    pTop3 = sorted((r for r in calc if r["pAmt"] > 0), key=lambda r: -r["pAmt"])[:3]
    cTop, pTop = cTop3[:2], pTop3[:2]
    keys = []
    for i, r in enumerate(cTop):
        keys.append((f"CALL增額第{'一' if i==0 else '二'}", r["k"] + basis + r["Cs"], UP))
    for i, r in enumerate(pTop):
        keys.append((f"PUT增額第{'一' if i==0 else '二'}", r["k"] + basis - r["Ps"], DN))

    # 顯示範圍: 卡在「CALL 增額前三」與「PUT 增額前三」共六個履約價的最小~最大之間
    anchor = [r["k"] for r in cTop3 + pTop3] or [r["k"] for r in calc]
    kLo, kHi = min(anchor), max(anchor)
    vis = [r for r in calc if kLo <= r["k"] <= kHi
           and (abs(r["cAmt"]) >= MIN_AMT or abs(r["pAmt"]) >= MIN_AMT)]
    vis.sort(key=lambda r: r["k"])
    # 前兩名凸顯用
    cHL = {cTop[i]["k"]: i for i in range(len(cTop))}
    pHL = {pTop[i]["k"]: i for i in range(len(pTop))}
    n = len(vis)
    fig_h = max(8.0, n * 0.17 + 3.4)
    fig = plt.figure(figsize=(11.5, fig_h))
    fig.patch.set_facecolor(BG)
    hdr_h = 3.05                                         # 頂部資訊區高度(吋)
    gs = fig.add_gridspec(1, 2, left=.055, right=.975,
                          top=1 - hdr_h / fig_h, bottom=.035, wspace=.135)
    axL, axR = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    ys = list(range(n))
    maxAmt = max([abs(r["cAmt"]) for r in vis] + [abs(r["pAmt"]) for r in vis] + [1])

    for ax, side, col, faint, flip in ((axL, "c", UP, UP_F, True),
                                       (axR, "p", DN, DN_F, False)):
        ax.set_facecolor(PANEL)
        for s in ax.spines.values():
            s.set_color(GRID)
        ax.grid(True, axis="x", color=GRID, lw=.5, alpha=.6)
        ax.set_axisbelow(True)
        amts = [r[side + "Amt"] for r in vis]
        lots = [r["dC" if side == "c" else "dP"] for r in vis]
        HL = cHL if side == "c" else pHL
        hlc = ("#ff1f1f", "#ff5252") if side == "c" else ("#00e676", "#37d98a")
        cols, edges, lws = [], [], []
        for r, a in zip(vis, amts):
            rank = HL.get(r["k"]) if a > 0 else None
            if rank is not None:
                cols.append(hlc[rank]); edges.append("#ffd166"); lws.append(1.6)
            else:
                cols.append(col if a != 0 else "#00000000")
                edges.append("none"); lws.append(0)
        ax.barh(ys, amts, height=.68, color=cols, edgecolor=edges, linewidth=lws)
        maxNeg = max([-a for a in amts if a < 0] + [0])
        ax.axvline(0, color=MUT, lw=1, alpha=.7)
        ax.set_xlim(-(maxNeg + maxAmt * .32), maxAmt * 1.55)
        ax.set_ylim(n - .4, -.6)
        if flip:
            ax.invert_xaxis()                            # CALL 柱向左長
            ax.yaxis.tick_right()
            ax.tick_params(axis="y", colors=TXT, labelsize=9.5, pad=6)
            ax.set_yticks(ys)
            ax.set_yticklabels([f"{r['k']:.0f}" for r in vis])
        else:
            ax.set_yticks([])
        ax.set_xticks([])
        # 標籤: 金額 (Δ口) — 正值在柱端外側, 負值在負柱外側
        pad = maxAmt * .03
        for y, (a, l) in enumerate(zip(amts, lots)):
            if a == 0 and l == 0:
                continue
            x = a + (pad if a >= 0 else -pad)
            ha = ("right" if a >= 0 else "left") if flip else ("left" if a >= 0 else "right")
            rank = (cHL if side == "c" else pHL).get(vis[y]["k"]) if a > 0 else None
            ax.text(x, y, f"{f_e(a)} ({l:+d})", va="center", ha=ha,
                    fontsize=9.2 if rank is not None else 8.2,
                    fontweight="bold" if rank is not None else "normal",
                    color=("#ffd166" if rank is not None else (col if a > 0 else MUT)))
        ax.set_title("買權 CALL — OI 金額變化" if side == "c" else "賣權 PUT — OI 金額變化",
                     color=(UP if side == "c" else DN), fontsize=12, fontweight="bold",
                     loc="right" if flip else "left", pad=8)

    # ---- 頂部資訊 ----
    y0 = 1 - .28 / fig_h
    fig.text(.055, y0, f"台指選擇權 籌碼分布 — OI 金額變化", color=TXT,
             fontsize=16, fontweight="bold", va="top")
    fig.text(.055, y0 - .34 / fig_h,
             f"{date} [{expiry}] ・ 柱狀 = 增減口數 × 結算價 × 50元 ・ 括號 = 增減口數",
             color=MUT, fontsize=10.5, va="top")
    note = ("OI為未平倉,未平倉由1買1賣組成1口OI,所以OI契約價值增加越大的地方,代表很多人買、賣在這個履約價,\n"
            "買方僅需支付權利金,金額較小,比較多是散戶在賭單邊噴出。\n"
            "賣方需預放保證金,金額較大,可能比較多大戶在做收租,當指數來到它們可能會虧損的地方,"
            "指數就有可能會出現相對應的支撐及壓力。")
    fig.text(.055, y0 - .62 / fig_h, note, color=MUT, fontsize=9.5, va="top", linespacing=1.55)
    info = (f"加權指數 {taiex:,.2f}    台指期收盤 {tx_close:,.0f}    "
            f"價差(期−現) {basis:+,.2f}")
    fig.text(.055, y0 - 1.42 / fig_h, info, color=TXT, fontsize=12, va="top")

    # 四個關鍵數字並排 (不顯示公式)
    W = .235
    for i, (lab, val, col) in enumerate(keys):
        x = .055 + i * W
        fig.text(x, y0 - 1.82 / fig_h, lab, color=MUT, fontsize=10.5, va="top")
        fig.text(x, y0 - 2.12 / fig_h, f"{val:,.0f}", color=col,
                 fontsize=19, fontweight="bold", va="top")

    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, fname)
    fig.savefig(p, dpi=150, facecolor=BG)
    plt.close(fig)
    print("  →", p)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".shots")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--input")
    ap.add_argument("--tx", type=float)
    ap.add_argument("--taiex", type=float)
    ap.add_argument("--date")
    ap.add_argument("--expiry")
    a = ap.parse_args()
    if a.fetch:
        date, expiry, rows, tx, taiex = fetch_all()
    else:
        rows = json.load(open(a.input, encoding="utf-8"))
        date, expiry, tx, taiex = a.date, a.expiry, a.tx, a.taiex
    print(f"選擇權籌碼: {date} [{expiry}] 履約價 {len(rows)} 檔, TX {tx}, 加權 {taiex}")
    render(date, expiry, rows, tx, taiex, a.out)


if __name__ == "__main__":
    main()
