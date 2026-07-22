#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日報告用圖表 — 直接讀 data/*.json 自己畫, 不截網頁。

版面 (每張圖):
  ┌ 標題 / 副標(期間·資料日期)          當日重點數值(右上) ┐
  │  主圖: 籌碼資料(左軸) + 台指期收盤(右軸, 統一放右邊)   │
  └ 近五日歷史趨勢表(含今日, 欄位比照網站)                 ┘

圖型規則: 數列有跨越 0 → 柱狀(紅正/綠負, 柱間留空);
          整段同號(例如外資期貨長期淨空) → 折線 + Y軸貼合資料範圍,
          否則柱狀會從 0 拉成一整片色塊, 把疊圖蓋掉也看不出變化。

用法: python tools/charts.py --out .shots [--days 60]
"""
import os, json, argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

BG, PANEL, GRID, TXT, MUT = "#0f1620", "#131a24", "#243040", "#e6edf3", "#9aa7b4"
UP, DN, TXFC = "#ff6b6b", "#4ade80", "#f0c85a"
E = 1e8          # 億
K2E = 1e5        # 千元 → 億元

for _f in ("Noto Sans CJK TC", "Noto Sans CJK JP", "Noto Sans CJK SC"):
    try:
        matplotlib.font_manager.findfont(_f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [_f]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


def load(n):
    p = os.path.join(DATA, n)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def sgn(v):
    return UP if (v or 0) > 0 else (DN if (v or 0) < 0 else TXT)


# signed=True → 帶 +/- (用於「較前一日」這種真正的變動量)
# signed=False → 不帶符號、只顯示絕對值 (用於「未平倉金額/淨部位」等當下水位;
#                方向改由顏色表達 sgn(): 紅=正/多方、綠=負/空方, 避免 + 被誤讀成「增加」)
def f_lot(v, signed=True):
    if v is None:
        return "—"
    return f"{v:+,.0f} 口" if signed else f"{abs(v):,.0f} 口"


def f_e(v, unit="億", signed=True):
    if v is None:
        return "—"
    return f"{v:+,.2f} {unit}" if signed else f"{abs(v):,.2f} {unit}"


# ------------------------------------------------------------------ 版面元件
def header(fig, title, sub, stats, y0=.965):
    """左上標題 / 右上當日重點(並排, 數值放大)。stats = [(標籤, 文字, 顏色), ...]"""
    fig.text(.075, y0, title, color=TXT, fontsize=16, fontweight="bold", va="top")
    fig.text(.075, y0 - .042, sub, color=MUT, fontsize=11, va="top")
    n = len(stats)
    W, RIGHT = .19, .90                        # 區塊寬度 / 最右錨點 (略往中間收, 不貼頁緣)
    for i, (lab, val, col) in enumerate(stats):
        xr = RIGHT - (n - 1 - i) * W
        fig.text(xr, y0, lab, color=MUT, fontsize=11.5, ha="right", va="top")
        fig.text(xr, y0 - .038, val, color=col, fontsize=20, fontweight="bold",
                 ha="right", va="top")


def style(ax, ylabel):
    ax.set_facecolor(PANEL)
    ax.grid(True, color=GRID, lw=.6, alpha=.7)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUT, labelsize=9)
    ax.set_ylabel(ylabel, color=MUT, fontsize=10)
    # 千分位; 億元類的小數保留兩位
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"))


def xaxis(ax, dates):
    n = len(dates)
    step = max(1, n // 8)
    idx = list(range(0, n, step))
    ax.set_xticks(idx)
    ax.set_xticklabels([dates[i][5:] for i in idx])
    ax.set_xlim(-0.8, n - 0.2)


def plot_series(ax, ys, label, kind="auto", invert=False):
    """kind=bar 強制柱狀 / line 強制折線 / auto: 跨 0 → 柱狀, 同號 → 折線(貼合範圍)。
    同號還畫柱狀會從 0 拉成一整片色塊, 把疊圖蓋掉也看不出變化, 故 auto 改折線。"""
    x = list(range(len(ys)))
    v = [0 if y is None else y for y in ys]
    if kind == "bar" or (kind == "auto" and min(v) < 0 < max(v)):
        pos, neg = (DN, UP) if invert else (UP, DN)   # invert: PUT 正值代表看空 → 綠
        ax.bar(x, v, width=.62, color=[pos if y >= 0 else neg for y in v], label=label)
        ax.axhline(0, color=MUT, lw=1, alpha=.6)
    else:
        ax.plot(x, v, color="#9fc3e8", lw=2.8, label=label)
        lo, hi = min(v), max(v)
        pad = (hi - lo) * .12 or 1
        ax.set_ylim(lo - pad, hi + pad)


def add_txf(ax, dates, txf):
    """台指期收盤一律放右軸。"""
    ys = [txf.get(d) for d in dates]
    if not any(v is not None for v in ys):
        return None
    a2 = ax.twinx()
    a2.plot(range(len(dates)), ys, color=TXFC, lw=3.2, label="台指期收盤(右軸)", zorder=5)
    a2.tick_params(colors=TXFC, labelsize=9)
    for s in a2.spines.values():
        s.set_color(GRID)
    lo = min(v for v in ys if v is not None); hi = max(v for v in ys if v is not None)
    pad = (hi - lo) * .12 or 1
    a2.set_ylim(lo - pad, hi + pad)
    a2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    return a2


def legend(ax, a2):
    h, l = ax.get_legend_handles_labels()
    if a2:
        h2, l2 = a2.get_legend_handles_labels()
        h += h2; l += l2
    lg = ax.legend(h, l, loc="upper left", fontsize=9, framealpha=.85,
                   facecolor=PANEL, edgecolor=GRID, ncol=2)
    for t in lg.get_texts():
        t.set_color(TXT)


def draw_table(ax, headers, rows):
    """近五日表 (含今日, 最新在上), 加上格線與表頭底色 — 比照網站歷史趨勢表。"""
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    n, m = len(headers), len(rows)
    rh = 1.0 / (m + 1)                          # 含表頭共 m+1 列, 等高
    xr = lambda i: (i + 1) / n - .010           # 各欄右緣 (第一欄靠左)

    ax.add_patch(plt.Rectangle((0, 1 - rh), 1, rh, color="#1a2330", zorder=0))  # 表頭底色
    for k in range(m + 2):                      # 橫向格線
        y = 1 - k * rh
        if 0 <= y <= 1:
            ax.plot([0, 1], [y, y], color=GRID, lw=1.1 if k <= 1 else .8, zorder=1)

    yc = 1 - rh / 2
    for i, h in enumerate(headers):
        ax.text(0 if i == 0 else xr(i), yc, h, color=MUT, fontsize=10.5,
                ha="left" if i == 0 else "right", va="center", zorder=2)
    for r, row in enumerate(rows):
        yc = 1 - rh * (r + 1) - rh / 2
        for i, (txt, col) in enumerate(row):
            ax.text(0 if i == 0 else xr(i), yc, txt, color=col,
                    fontsize=11 if i else 10.5,
                    ha="left" if i == 0 else "right", va="center",
                    fontweight="normal" if i == 0 else "bold", zorder=2)


def frame(title, sub, stats, dates, panels, txf, headers, rows, out, fname):
    """panels = [(ys, ylabel, 圖例標籤, 小標題, kind, invert), ...] — 1 或 2 圖共用一張。"""
    k = len(panels)
    fig = plt.figure(figsize=(11.5, 7.0 if k == 1 else 9.8))
    fig.patch.set_facecolor(BG)
    hr = [2.9, 1.0] if k == 1 else [2.15, 2.15, 1.05]
    top = .855 if k == 1 else .845
    gs = fig.add_gridspec(k + 1, 1, height_ratios=hr,
                          left=.075, right=.915, top=top, bottom=.05,
                          hspace=.30 if k == 1 else .34)
    for i, (ys, ylabel, lab, sub_t, kind, inv) in enumerate(panels):
        ax = fig.add_subplot(gs[i])
        style(ax, ylabel)
        if sub_t:
            ax.set_title(sub_t, color=TXT, fontsize=12, fontweight="bold", loc="left", pad=8)
        plot_series(ax, ys, lab, kind, inv)
        xaxis(ax, dates)
        legend(ax, add_txf(ax, dates, txf))
    header(fig, title, sub, stats, y0=.965)
    draw_table(fig.add_subplot(gs[k]), headers, rows)
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, fname)
    fig.savefig(p, dpi=150, facecolor=BG)
    plt.close(fig)
    print("  →", p)
    return p


# ------------------------------------------------------------------ 各張圖
def opt_charts(doc, txf, days, out, who, idx):
    recs = doc["records"]
    ds = sorted(recs)[-days:]
    last5 = sorted(recs)[-5:][::-1]              # 近五日, 含今日, 最新在上
    g = lambda d, k, f: (recs[d].get(k) or {}).get(f)
    cur, prev = ds[-1], (ds[-2] if len(ds) > 1 else None)

    def amt(d, k):
        v = g(d, k, "diff_oi_amt")
        return None if v is None else v / K2E

    stats = [("CALL 未平倉金額", f_e(amt(cur, "call"), signed=False), sgn(amt(cur, "call"))),
             ("PUT 未平倉金額", f_e(amt(cur, "put"), signed=False), sgn(amt(cur, "put")))]

    # 近五日表 — 欄位比照網站 (金額改億元較好讀)
    heads = ["日期", "CALL差額(口)", "PUT差額(口)", "CALL金額(億)", "PUT金額(億)"]
    rows = []
    for d in last5:
        cl, pl = g(d, "call", "diff_oi_lots"), g(d, "put", "diff_oi_lots")
        ca, pa = amt(d, "call"), amt(d, "put")
        rows.append([(d, MUT), (f"{cl:+,.0f}" if cl is not None else "—", sgn(cl)),
                     (f"{pl:+,.0f}" if pl is not None else "—", sgn(pl)),
                     (f"{ca:+,.2f}" if ca is not None else "—", sgn(ca)),
                     (f"{pa:+,.2f}" if pa is not None else "—", sgn(pa))])

    # 一張圖 = CALL 圖 + PUT 圖 + 共用的近五日表
    panels = [([amt(d, "call") for d in ds], "未平倉金額(億元)", "CALL 未平倉金額", "CALL 未平倉金額", "bar", False),
              ([amt(d, "put") for d in ds], "未平倉金額(億元)", "PUT 未平倉金額", "PUT 未平倉金額", "bar", True)]
    return frame(f"{who}選擇權 — CALL / PUT 未平倉金額",
                 f"近 {len(ds)} 個交易日 ・ 資料日期 {cur}",
                 stats, ds, panels, txf, heads, rows, out, f"{idx}_{who}選擇權.png")


def futspot_chart(doc, txf, days, out):
    recs = doc["records"]
    ds = sorted(recs)[-days:]
    last5 = sorted(recs)[-5:][::-1]
    net = lambda d: (recs[d].get("fut") or {}).get("net_oi_lots")
    spot = lambda d: (recs[d].get("spot") or {}).get("net_amt")
    cur, prev = ds[-1], (ds[-2] if len(ds) > 1 else None)
    dn = (net(cur) - net(prev)) if prev and net(prev) is not None and net(cur) is not None else None
    sp = spot(cur)
    stats = [("期貨多空淨額", f_lot(net(cur), signed=False), sgn(net(cur))),
             ("較前一日", f_lot(dn), sgn(dn)),                              # 變動 → 保留 +/-
             ("現貨買賣差額", f_e(None if sp is None else sp / E, signed=False), sgn(sp))]

    heads = ["日期", "期貨多空淨額(口)", "較前一日增減(口)", "現貨買賣差額(億)"]
    rows = []
    all_ds = sorted(recs)
    for d in last5:
        i = all_ds.index(d)
        p = all_ds[i - 1] if i > 0 else None
        n0, p0 = net(d), (net(p) if p else None)
        dd = (n0 - p0) if (n0 is not None and p0 is not None) else None
        s0 = spot(d)
        rows.append([(d, MUT), (f"{n0:+,.0f}" if n0 is not None else "—", sgn(n0)),
                     (f"{dd:+,.0f}" if dd is not None else "—", sgn(dd)),
                     (f"{s0/E:+,.2f}" if s0 is not None else "—", sgn(s0))])

    panels = [([net(d) for d in ds], "多空淨額(口)", "外資期貨多空淨額", None, "bar", False)]
    return frame("外資期貨 — 多空淨額", f"近 {len(ds)} 個交易日 ・ 資料日期 {cur}",
                 stats, ds, panels, txf, heads, rows, out, "3_外資期貨現貨.png")


def largefut_chart(doc, txf, days, out):
    recs = doc["records"]
    ds = sorted(recs)[-days:]
    last5 = sorted(recs)[-5:][::-1]

    def pick(d):
        rows = recs[d].get("rows") or []
        t1 = next((r for r in rows if r.get("month") == "999999" and r.get("type") == "1"), None)
        t0 = next((r for r in rows if r.get("month") == "999999" and r.get("type") == "0"), None)
        net = (t1["top10_buy"] - t1["top10_sell"]) if t1 else None
        return net, (t0 or {}).get("market_oi")

    cur, prev = ds[-1], (ds[-2] if len(ds) > 1 else None)
    n_cur = pick(cur)[0]
    n_prev = pick(prev)[0] if prev else None
    dn = (n_cur - n_prev) if (n_cur is not None and n_prev is not None) else None
    stats = [("未平倉淨部位", f_lot(n_cur, signed=False), sgn(n_cur)),
             ("較前一日", f_lot(dn), sgn(dn))]                              # 變動 → 保留 +/-

    heads = ["日期", "前十特定法人淨部位(口)", "全市場未沖銷(口)"]
    rows = []
    for d in last5:
        n0, mk = pick(d)
        rows.append([(d, MUT), (f"{n0:+,.0f}" if n0 is not None else "—", sgn(n0)),
                     (f"{mk:,.0f}" if mk is not None else "—", TXT)])

    panels = [([pick(d)[0] for d in ds], "淨部位(口)", "前十特定法人淨部位", None, "auto", False)]
    return frame("大額交易人期貨 — 前十大特定法人淨部位",
                 f"近 {len(ds)} 個交易日 ・ 資料日期 {cur}",
                 stats, ds, panels, txf, heads, rows, out, "4_大額交易人期貨.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".shots")
    ap.add_argument("--days", type=int, default=60)
    a = ap.parse_args()
    txf = ((load("txf.json") or {}).get("records") or {})
    print("產生圖表:")
    for f, who, i in (("options_foreign.json", "外資", 1), ("options_dealer.json", "自營", 2)):
        d = load(f)
        if d:
            opt_charts(d, txf, a.days, a.out, who, i)
    d = load("foreign_fut_spot.json")
    if d:
        futspot_chart(d, txf, a.days, a.out)
    d = load("large_fut_txf.json")
    if d:
        largefut_chart(d, txf, a.days, a.out)
    print("完成")


if __name__ == "__main__":
    main()
