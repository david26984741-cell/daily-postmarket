#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日報告用圖表 — 直接讀 data/*.json 自己畫, 不截網頁。

為什麼不截網頁: 不受頁面排版限制(可把 CALL/PUT 疊同一張)、不必裝 Chromium、
不必等部署、網站改版也不會壞。

用法:
  python tools/charts.py --out .shots [--days 60]

輸出 (近三個月, 預設 60 個交易日):
  1_外資選擇權.png     CALL/PUT 未平倉金額(千元) 雙線 + 台指期收盤(右軸)
  2_自營選擇權.png     同上
  3_外資期貨現貨.png   外資期貨多空淨額(口) 柱狀 + 台指期收盤(右軸)
  4_大額交易人期貨.png 前十特定法人淨部位(口) + 台指期收盤(右軸)
"""
import os, json, argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

# ---- 配色 (對齊網站深色主題) ----
BG, PANEL, GRID, TXT, MUT = "#0f1620", "#131a24", "#243040", "#e6edf3", "#9aa7b4"
UP, DN, TXF = "#ff6b6b", "#4ade80", "#f0c85a"      # 紅漲/綠跌/台指期黃線

for f in ("Noto Sans CJK TC", "Noto Sans CJK JP", "Noto Sans CJK SC"):
    try:
        matplotlib.font_manager.findfont(f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [f]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


def load(name):
    p = os.path.join(DATA, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def tail_dates(records, n):
    return sorted(records.keys())[-n:]


def fmt_k(v, _=None):
    """千分位 + 萬/億 縮寫, 避免軸標籤過長。"""
    a = abs(v)
    if a >= 1e8:
        return f"{v/1e8:.1f}億"
    if a >= 1e4:
        return f"{v/1e4:.0f}萬"
    return f"{v:,.0f}"


def style(ax, title, sub=""):
    ax.set_facecolor(PANEL)
    ax.grid(True, color=GRID, lw=.6, alpha=.7)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUT, labelsize=9)
    ax.set_title(title + ("\n" + sub if sub else ""), color=TXT, fontsize=13,
                 fontweight="bold", loc="left", pad=12)


def xaxis(ax, dates):
    """日期軸: 最多 8 個刻度, 只顯示 月/日。"""
    n = len(dates)
    step = max(1, n // 8)
    idx = list(range(0, n, step))
    ax.set_xticks(idx)
    ax.set_xticklabels([dates[i][5:] for i in idx], rotation=0)
    ax.set_xlim(-0.5, n - 0.5)


def add_txf(ax, dates, txf):
    """右軸疊台指期近月收盤 — 籌碼要對照指數才看得出意義。"""
    if not txf:
        return None
    ys = [txf.get(d) for d in dates]
    if not any(v is not None for v in ys):
        return None
    ax2 = ax.twinx()
    ax2.plot(range(len(dates)), ys, color=TXF, lw=1.6, label="台指期收盤(右軸)")
    ax2.tick_params(colors=TXF, labelsize=9)
    for s in ax2.spines.values():
        s.set_color(GRID)
    lo = min(v for v in ys if v is not None); hi = max(v for v in ys if v is not None)
    pad = (hi - lo) * .12 or 1
    ax2.set_ylim(lo - pad, hi + pad)
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    return ax2


def net_area(ax, ys, label, line="#9fc3e8"):
    """淨部位折線 + 依正負填色 (紅=淨多 / 綠=淨空), 一眼看出多空方向。
    不用柱狀: 淨部位是「存量」且常長期同號, 柱狀會變成一整片色塊蓋住疊圖。"""
    x = list(range(len(ys)))
    v = [0 if y is None else y for y in ys]
    ax.plot(x, v, color=line, lw=2, label=label)
    # 只有「有跨越 0」才填色並標 0 線; 若整段同號(例如外資長期淨空),
    # 填到 0 會佔滿整張圖、把疊圖蓋掉, 此時改讓 Y 軸貼合資料範圍以看出變化。
    if min(v) < 0 < max(v):
        ax.fill_between(x, v, 0, where=[y >= 0 for y in v], color=UP, alpha=.20, interpolate=True)
        ax.fill_between(x, v, 0, where=[y <= 0 for y in v], color=DN, alpha=.20, interpolate=True)
        ax.axhline(0, color=MUT, lw=1, alpha=.6)
    else:
        lo, hi = min(v), max(v)
        pad = (hi - lo) * .12 or 1
        ax.set_ylim(lo - pad, hi + pad)


def legend(ax, ax2):
    h, l = ax.get_legend_handles_labels()
    if ax2:
        h2, l2 = ax2.get_legend_handles_labels()
        h += h2; l += l2
    lg = ax.legend(h, l, loc="upper left", fontsize=9, framealpha=.85,
                   facecolor=PANEL, edgecolor=GRID, ncol=3)
    for t in lg.get_texts():
        t.set_color(TXT)


def save(fig, out, name):
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, name)
    fig.savefig(p, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print("  →", p)
    return p


# ------------------------------------------------------------------ 各圖
def chart_options(doc, txfr, days, out, fname, who):
    """CALL/PUT 未平倉金額(千元) 疊同一張, 方便直接比對強弱。"""
    ds = tail_dates(doc["records"], days)
    # 原始單位為千元 → 換成億元 (1億元 = 10萬千元), 否則軸標會出現「80萬千元」難以換算
    g = lambda d, k: (doc["records"][d].get(k, {}).get("diff_oi_amt"))
    call = [None if g(d, "call") is None else g(d, "call") / 1e5 for d in ds]
    put = [None if g(d, "put") is None else g(d, "put") / 1e5 for d in ds]
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor(BG)
    x = range(len(ds))
    ax.plot(x, call, color=UP, lw=2, label="CALL 未平倉金額")
    ax.plot(x, put, color=DN, lw=2, label="PUT 未平倉金額")
    ax.axhline(0, color=MUT, lw=1, alpha=.6)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.1f}"))
    ax.set_ylabel("未平倉金額(億元)", color=MUT, fontsize=10)
    style(ax, f"{who}選擇權 — CALL / PUT 未平倉金額", f"近 {len(ds)} 個交易日 ・ 資料日期 {ds[-1]}")
    xaxis(ax, ds)
    legend(ax, add_txf(ax, ds, txfr))
    return save(fig, out, fname)


def chart_fut_spot(doc, txfr, days, out):
    """外資期貨多空淨額(口) 柱狀 — 紅淨多/綠淨空。"""
    ds = tail_dates(doc["records"], days)
    net = [doc["records"][d].get("fut", {}).get("net_oi_lots") for d in ds]
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor(BG)
    net_area(ax, net, "外資期貨多空淨額")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylabel("多空淨額(口)", color=MUT, fontsize=10)
    style(ax, "外資期貨 — 多空淨額", f"近 {len(ds)} 個交易日 ・ 資料日期 {ds[-1]}")
    xaxis(ax, ds)
    legend(ax, add_txf(ax, ds, txfr))
    return save(fig, out, "3_外資期貨現貨.png")


def chart_large_fut(doc, txfr, days, out):
    """前十大特定法人 淨部位(口) — 面積+線。"""
    ds = tail_dates(doc["records"], days)

    def net(rec):
        rows = rec.get("rows") or []
        f = lambda t: next((r for r in rows if r.get("month") == "999999" and r.get("type") == t), None)
        t1 = f("1")
        return (t1["top10_buy"] - t1["top10_sell"]) if t1 else None

    ys = [net(doc["records"][d]) for d in ds]
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor(BG)
    net_area(ax, ys, "前十大特定法人淨部位")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylabel("淨部位(口)", color=MUT, fontsize=10)
    style(ax, "大額交易人期貨 — 前十大特定法人淨部位", f"近 {len(ds)} 個交易日 ・ 資料日期 {ds[-1]}")
    xaxis(ax, ds)
    legend(ax, add_txf(ax, ds, txfr))
    return save(fig, out, "4_大額交易人期貨.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".shots")
    ap.add_argument("--days", type=int, default=60)   # 近三個月 ≈ 60 個交易日
    a = ap.parse_args()

    txf = load("txf.json")
    txfr = (txf or {}).get("records") or {}
    print("產生圖表:")
    for f, who, name in (("options_foreign.json", "外資", "1_外資選擇權.png"),
                         ("options_dealer.json", "自營", "2_自營選擇權.png")):
        d = load(f)
        if d:
            chart_options(d, txfr, a.days, a.out, name, who)
    d = load("foreign_fut_spot.json")
    if d:
        chart_fut_spot(d, txfr, a.days, a.out)
    d = load("large_fut_txf.json")
    if d:
        chart_large_fut(d, txfr, a.days, a.out)
    print("完成")


if __name__ == "__main__":
    main()
