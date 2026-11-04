# -*- coding: utf-8 -*-
"""盤後籌碼快報 — 繪圖 (由 tools/flash.py render 呼叫, 只讀 data/flash.json)。

版面比照 統一期貨「盤後籌碼快報」(853×1280 設計稿座標, 輸出 2 倍解析度),
品牌(logo / 公司名 / 地址 / 許可證字號)換成本站名稱與資料來源。
座標系: x 向右、y 向下, 單位 = 設計稿像素; 字級參數也用像素 (em 高)。
"""
import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Wedge, Polygon
from matplotlib.colors import LinearSegmentedColormap
import numpy as np

W, H = 853, 1280
SCALE = 2                      # 輸出 1706×2560
BG, CARD = "#eef1f6", "#ffffff"
NAVY, TXT, MUT, LINE = "#1d2f4e", "#1f2733", "#7a8594", "#e3e7ee"
UP, DN = "#d4353b", "#1e8a73"                # 台股慣例: 紅漲綠跌
UP_BG, DN_BG = "#fbe6e6", "#dff1ec"
ORANGE, SPARK = "#ef7d2d", "#e8743b"
SITE = "每日盤後資料"
WEEK = "一二三四五六日"

for _f in ("Noto Sans CJK TC", "Noto Sans CJK JP", "Noto Sans CJK SC"):
    try:
        matplotlib.font_manager.findfont(_f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [_f]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


class Canvas:
    def __init__(self):
        self.fig = plt.figure(figsize=(W / 100, H / 100), dpi=100 * SCALE)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, W)
        self.ax.set_ylim(H, 0)
        self.ax.axis("off")
        self.fig.patch.set_facecolor(BG)
        self.r = self.fig.canvas.get_renderer()

    # 字級 px(em) → pt: 1 設計稿 px = 1/100 inch = 0.72 pt
    def text(self, x, y, s, size, color=TXT, bold=False, ha="left", va="baseline", z=5):
        return self.ax.text(x, y, s, fontsize=size * 0.72, color=color, ha=ha, va=va,
                            fontweight="bold" if bold else "normal", zorder=z)

    def width(self, artist):
        return artist.get_window_extent(self.r).width / SCALE

    def tw(self, s, size, bold=False):
        t = self.text(-999, -999, s, size, bold=bold)
        w = self.width(t)
        t.remove()
        return w

    def rtext(self, xr, y, parts, gap=2):
        """右對齊的多段文字 parts=[(字串, size, color, bold), ...] (由左到右), 回傳最左 x"""
        x = xr
        for s, size, color, bold in reversed(parts):
            t = self.text(x, y, s, size, color, bold, ha="right")
            x -= self.width(t) + gap
        return x + gap

    def ltext(self, xl, y, parts, gap=2):
        x = xl
        for s, size, color, bold in parts:
            t = self.text(x, y, s, size, color, bold, ha="left")
            x += self.width(t) + gap
        return x

    def rrect(self, x, y, w, h, r=6, fc=CARD, ec="none", lw=0, z=1):
        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                         fc=fc, ec=ec, lw=lw, zorder=z, mutation_aspect=1))

    def rect(self, x, y, w, h, fc, z=2):
        self.ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec="none", zorder=z))

    def hline(self, x0, x1, y, color=LINE, lw=1.0):
        self.ax.plot([x0, x1], [y, y], color=color, lw=lw * SCALE * 0.72, zorder=3,
                     solid_capstyle="butt")

    def vline(self, x, y0, y1, color=LINE, lw=1.0):
        self.ax.plot([x, x], [y0, y1], color=color, lw=lw * SCALE * 0.72, zorder=3)

    def gradient(self, y, h):
        cm = LinearSegmentedColormap.from_list("g", ["#d7262d", "#e8452c", "#f39a2c"])
        self.ax.imshow(np.linspace(0, 1, 256)[None, :], cmap=cm, aspect="auto",
                       extent=(0, W, y + h, y), zorder=2)

    def spark(self, x, y, w, h, vals, color, fill):
        v = [a for a in vals if a is not None]
        if len(v) < 2:
            return
        lo, hi = min(v), max(v)
        if hi == lo:
            hi, lo = hi + 1, lo - 1
        xs = np.linspace(x, x + w, len(v))
        ys = [y + h - (a - lo) / (hi - lo) * h for a in v]
        self.ax.add_patch(Polygon(list(zip(xs, ys)) + [(x + w, y + h), (x, y + h)],
                                  closed=True, fc=fill, ec="none", zorder=3))
        self.ax.plot(xs, ys, color=color, lw=1.4 * SCALE * 0.72, zorder=4,
                     solid_joinstyle="round")
        self.ax.plot([xs[-1]], [ys[-1]], "o", color=color, ms=2.4 * SCALE * 0.72, zorder=5)

    def save(self, path):
        self.fig.savefig(path, dpi=100 * SCALE, facecolor=BG)
        plt.close(self.fig)


# ------------------------------------------------------------------ 格式
def c_of(v):
    return TXT if v is None or v == 0 else (UP if v > 0 else DN)


def fs(v, nd=2, comma=True):
    if v is None:
        return "—"
    return f"{v:+,.{nd}f}" if comma else f"{v:+.{nd}f}"


def arrow(diff, nd=0):
    if diff is None:
        return ("", TXT)
    if round(diff, nd) == 0:
        return ("─ 0", MUT)
    return (("▲ " if diff > 0 else "▼ ") + f"{abs(diff):,.{nd}f}", UP if diff > 0 else DN)


def section(cv, y, h, title, sub):
    cv.rrect(23, y, 807, h, r=8)
    cv.rect(39, y + 17, 3.5, 21, ORANGE, z=3)
    cv.text(53, y + 36, title, 22, TXT, bold=True)
    cv.text(53, y + 56, sub, 12.5, MUT)


# ------------------------------------------------------------------ 主繪圖
def render(doc, date_slash, out):
    days = doc.get("days") or {}
    keys = sorted(k for k in days if k <= date_slash)
    T = days.get(date_slash) or {}
    prev = [days[k] for k in keys if k < date_slash]

    def prev_has(field):
        for d in reversed(prev):
            if d.get(field) is not None:
                return d
        return {}

    def series(fn, n=10):
        out_ = []
        for k in keys[-n:]:
            try:
                out_.append(fn(days[k]))
            except Exception:
                out_.append(None)
        return out_

    dt = datetime.datetime.strptime(date_slash, "%Y/%m/%d")
    md = f"{dt.month}/{dt.day}"
    cv = Canvas()

    # ---------------- 頁首
    cv.rect(0, 0, W, 66, CARD, z=1)
    cv.ax.add_patch(plt.Circle((42, 37), 13, fc="#d7262d", ec="none", zorder=3))
    cv.text(42, 37.5, "盤", 13, "#ffffff", bold=True, ha="center", va="center", z=4)
    cv.text(62, 45, SITE, 17, NAVY, bold=True)
    cv.text(427, 49, "盤後籌碼快報", 34, NAVY, bold=True, ha="center")
    cv.rtext(828, 49, [(f"{dt.year}/{dt.month}/{dt.day}", 32, NAVY, False),
                       (" 週" + WEEK[dt.weekday()], 13, MUT, False)], gap=4)
    cv.gradient(65, 6)

    # ---------------- ① 加權指數與台指期
    y = 83
    amt = T.get("amt")
    section(cv, y, 152, "加權指數與台指期",
            f"{md} 收盤　成交金額 {amt:,.0f} 億" if amt else f"{md} 收盤")
    idx = T.get("idx") or {}
    tx = T.get("tx")
    cols = [("加權", idx.get("taiex"), 2, 53), ("上櫃", T.get("otc"), 2, 198),
            ("電子", idx.get("elec"), 2, 308), ("金融", idx.get("fin"), 2, 440),
            ("台指期（近）", tx, 0, 570)]
    for lab, v, nd, x in cols:
        cv.text(x, y + 88, lab, 18, TXT)
        if v and v[0] is not None:
            cv.text(x, y + 120, f"{v[0]:,.{nd}f}", 24.5, TXT)
            pct = v[1]
            cv.text(x, y + 142, (f"{pct:+.2f}%" if pct is not None else "—"), 17, c_of(pct))
        else:
            cv.text(x, y + 119, "—", 22, MUT)
    cv.text(800, y + 88, "期現價差", 18, TXT, ha="right")
    basis = (tx[0] - idx["taiex"][0]) if (tx and idx.get("taiex")) else None
    cv.text(800, y + 120, fs(basis), 24.5, TXT, ha="right")

    # ---------------- ② 三大法人現貨買賣超
    y = 247
    section(cv, y, 183, "三大法人現貨買賣超", "單位：億元　含近 5 / 10 日累積")
    # 依「交易日」排, 缺資料的日子留 {} → 連N/近N日遇到缺口就停, 不會跳過缺口拿更舊的日子湊數
    bseries = [(k, days[k].get("bfi") or {}) for k in keys]
    b = T.get("bfi") or {}
    colx = [53, 247, 442, 636]
    colr = [217, 411, 605, 800]
    for sx in (232, 426, 620):
        cv.vline(sx, y + 70, y + 172)
    for i, (key, lab) in enumerate([("foreign", "外資"), ("trust", "投信"), ("dealer", "自營商")]):
        x, xr = colx[i], colr[i]
        cv.text(x, y + 90, lab, 18.5, TXT, bold=True)
        v = b.get(key)
        if v is not None and bseries and bseries[-1][0] == date_slash:
            sgn = 1 if v > 0 else -1
            n = 0
            for _, r in reversed(bseries):
                if r.get(key) is not None and r[key] * sgn > 0:
                    n += 1
                else:
                    break
            tag = f"連{n}{'買' if sgn > 0 else '賣'}"
            tw = cv.tw(tag, 12.5, True)
            x0 = x + cv.tw(lab, 18.5, True) + 12
            cv.rrect(x0, y + 70, tw + 20, 26, r=3, fc=UP_BG if sgn > 0 else DN_BG, z=2)
            cv.text(x0 + 10 + tw / 2, y + 88.5, tag, 12.5, UP if sgn > 0 else DN, True, ha="center")
        cv.rtext(xr, y + 124, [(fs(v), 23, c_of(v), False), ("億元", 9.5, MUT, False)])
        for j, (n_, ly) in enumerate([(5, y + 152), (10, y + 172)]):
            cv.text(x, ly, f"近{n_}日", 13.5, MUT)
            vals = [r.get(key) for _, r in bseries[-n_:]]
            ok = len(vals) == n_ and None not in vals and bseries[-1][0] == date_slash
            sv = sum(vals) if ok else None
            cv.rtext(xr, ly, [(fs(sv, 0), 14.5, c_of(sv), False), ("億", 9, MUT, False)])
    x, xr = colx[3], colr[3]
    cv.text(x, y + 90, "三大法人合計", 18.5, TXT, bold=True)
    v = b.get("total")
    cv.rtext(xr, y + 124, [(fs(v), 23, c_of(v), False), ("億元", 9.5, MUT, False)])
    for lab, key, ly in (("自行買賣", "dealer_self", y + 152), ("避險", "dealer_hedge", y + 172)):
        cv.text(x, ly, lab, 13.5, MUT)
        cv.rtext(xr, ly, [(fs(b.get(key)), 14.5, TXT, False), ("億", 9, MUT, False)])

    # ---------------- ③ 三大法人期貨與選擇權未平倉
    y = 442
    section(cv, y, 205, "三大法人期貨與選擇權未平倉",
            "期貨合計 = 大台 + 小台/4 + 微台/20；選擇權為契約金額淨額")
    gr = [295, 462, 630, 797]
    gl = [130, 298, 466, 633]
    for i, lab in enumerate(["外資", "投信", "自營商", "三大法人合計"]):
        if i < 3:
            cv.text((gl[i] + gr[i]) / 2 + 12, y + 90, lab, 18.5, TXT, ha="center")
        else:
            cv.text(gr[i], y + 90, lab, 18.5, TXT, ha="right")
    cv.hline(53, 800, y + 98)
    for sx in gr[:3]:
        cv.vline(sx + 2, y + 100, y + 200)
    rows_y = [y + 132, y + 163, y + 194]
    cv.text(53, rows_y[0] - 1, "期貨合計", 14.5, TXT, bold=True)
    cv.text(53, rows_y[1] - 1, "選擇權買權", 14.5, TXT)
    cv.text(53, rows_y[2] - 1, "選擇權賣權", 14.5, TXT)
    f_now, f_prev = T.get("fut"), prev_has("fut").get("fut")
    o_now, o_prev = T.get("opt"), prev_has("opt").get("opt")
    idents = ["foreign", "trust", "dealer"]

    def tot(d, j=None):
        if not d:
            return None
        return sum(d[k] for k in idents) if j is None else sum(d[k][j] for k in idents)

    for i in range(4):
        k = idents[i] if i < 3 else None
        # 期貨
        fv = (f_now[k] if k else tot(f_now)) if f_now else None
        fp = (f_prev[k] if k else tot(f_prev)) if f_prev else None
        fv_r = round(fv) if fv is not None else None
        diff = (fv_r - round(fp)) if (fv is not None and fp is not None) else None
        a, ac = arrow(diff, 0)
        xl = cv.rtext(gr[i], rows_y[0], [(a, 14, ac, False)])
        cv.rtext(xl - 8, rows_y[0], [(f"{fv_r:+,}" if fv_r is not None else "—", 21, c_of(fv_r), False),
                                     ("口", 10, MUT, False)], gap=3)
        # 選擇權
        for j in (0, 1):
            ov = (o_now[k][j] if k else tot(o_now, j)) if o_now else None
            op = (o_prev[k][j] if k else tot(o_prev, j)) if o_prev else None
            d2 = (round(ov, 2) - round(op, 2)) if (ov is not None and op is not None) else None
            a, ac = arrow(d2, 2)
            cv.rtext(gr[i], rows_y[1 + j], [(a, 14, ac, False)])
            cv.rtext(gr[i] - 56, rows_y[1 + j],
                     [(fs(ov), 21, c_of(ov), False), ("億元", 9.5, MUT, False)], gap=6)

    # ---------------- ④ 大額交易人、散戶指標與選擇權結構
    y = 660
    section(cv, y, 284, "大額交易人、散戶指標與選擇權結構",
            "大額交易人 TX + MTX/4 + TMF/20 所有月份．數字為買方 - 賣方淨額")
    boxes_x = [53, 306, 559]
    bw, bh = 241, 96
    by = [y + 69, y + 175]

    def card(x, yy):
        cv.rrect(x, yy, bw, bh, r=5, fc=CARD, ec=LINE, lw=1.0 * SCALE * 0.72, z=2)

    L = T.get("large")
    Lp = prev_has("large").get("large")
    for i, lab in enumerate(["前五大交易人", "前十大交易人"]):
        x, yy = boxes_x[i], by[0]
        card(x, yy)
        cv.text(x + 15, yy + 27, lab, 15.5, TXT)
        v = L[i] if L else None
        cv.text(x + 15, yy + 63, f"{v:+,.0f}" if v is not None else "—", 26, c_of(v))
        d = (v - Lp[i]) if (v is not None and Lp) else None
        a, ac = arrow(d, 0)
        cv.text(x + 226, yy + 88, a, 15, ac, ha="right")
        sv = series(lambda r, i=i: r["large"][i])
        col = UP if (v or 0) >= 0 else DN
        cv.spark(x + 148, yy + 14, 78, 58, sv, col, "#f6dada" if col == UP else "#d6ede6")

    # PC ratio
    x, yy = boxes_x[2], by[0]
    card(x, yy)
    cv.text(x + 15, yy + 27, "PC ratio 未平倉比", 15.5, TXT)
    pc, pcp = T.get("pc"), prev_has("pc").get("pc")
    cv.text(x + 15, yy + 63, f"{pc[2]:.2f}%" if pc else "—", 26, TXT)
    if pc and pcp:
        cv.text(x + 15, yy + 88, f"昨日 {pcp[2]:.2f}", 12.5, MUT)
        d = pc[0] / pc[1] * 100 - pcp[0] / pcp[1] * 100
        a, ac = arrow(d, 2)
        cv.text(x + 82, yy + 88, a, 15, ac)
    if pc:
        put_sh = pc[0] / (pc[0] + pc[1])
        cx, cy, R = x + 184, yy + 64, 38
        split = 180 + put_sh * 180
        cv.ax.add_patch(Wedge((cx, cy), R, 180, split, width=11, fc=DN, ec="none", zorder=3))
        cv.ax.add_patch(Wedge((cx, cy), R, split, 360, width=11, fc=UP, ec="none", zorder=3))
        cv.text(cx, cy - 8, f"賣 {put_sh * 100:.0f}%", 11.5, DN, True, ha="center")
        cv.text(cx, cy + 20, f"買 {(1 - put_sh) * 100:.0f}%", 10.5, UP, ha="center")

    # 散戶指標 / VIX
    R_, Rp = T.get("retail"), prev_has("retail").get("retail")
    V_, Vp = T.get("vix"), prev_has("vix").get("vix")
    items = [("小台散戶指標", R_["mtx"] if R_ else None, Rp["mtx"] if Rp else None, "%",
              lambda r: r["retail"]["mtx"]),
             ("微台散戶指標", R_["tmf"] if R_ else None, Rp["tmf"] if Rp else None, "%",
              lambda r: r["retail"]["tmf"]),
             ("VIX 指標", V_, Vp, "", lambda r: r["vix"])]
    for i, (lab, v, p, unit, fn) in enumerate(items):
        x, yy = boxes_x[i], by[1]
        card(x, yy)
        cv.text(x + 15, yy + 27, lab, 15.5, TXT)
        cv.text(x + 15, yy + 63, f"{v:.2f}{unit}" if v is not None else "—", 26, TXT)
        if p is not None:
            cv.text(x + 15, yy + 88, f"昨日 {p:.2f}{unit}", 12.5, MUT)
        a, ac = arrow((v - p) if (v is not None and p is not None) else None, 2)
        cv.text(x + 226, yy + 88, a, 15, ac, ha="right")
        cv.spark(x + 148, yy + 14, 78, 58, series(fn), SPARK, "#fbe3d6")

    # ---------------- ⑤ 類股雷達
    y = 957
    section(cv, y, 231, "類股雷達｜資金占比",
            "上市普通股　色彩 = 成交占比較前 5 日均值變化；非資金淨流入")
    S = T.get("sec") or {}
    hist = [days[k]["sec"] for k in keys if k < date_slash and days[k].get("sec")][-5:]
    tx_ = [53, 243, 433, 623]
    ty_ = [y + 69, y + 148]
    tw_, th_ = 177, 72
    from flash import SECTORS
    for n_, (name, _) in enumerate(SECTORS):
        x, yy = tx_[n_ % 4], ty_[n_ // 4]
        cur = S.get(name)
        pp = None
        if cur and len(hist) == 5 and all(h.get(name) for h in hist):
            pp = cur[0] - sum(h[name][0] for h in hist) / 5
        up = (pp or 0) >= 0
        cv.rect(x, yy, tw_, th_, UP_BG if up else DN_BG, z=2)
        cv.rect(x, yy, 3, th_, UP if up else DN, z=3)
        cv.text(x + 15, yy + 21, name, 13.5, TXT, bold=True)
        cv.text(x + 15, yy + 48, f"{cur[0]:.1f}%" if cur else "—", 22.5, UP if up else DN)
        cv.text(x + 165, yy + 47, f"{pp:+.2f}pp" if pp is not None else "", 13, TXT, ha="right")
        cv.text(x + 15, yy + 65, "均漲跌", 10.5, MUT)
        avg = cur[1] if cur else None
        cv.text(x + 165, yy + 65, f"{avg:+.2f}%" if avg is not None else "—", 13, TXT, ha="right")

    # ---------------- 頁尾
    cv.gradient(1198, 6)
    cv.text(23, 1229, f"{SITE}｜資料來源：臺灣證券交易所、證券櫃檯買賣中心、臺灣期貨交易所", 11.5, TXT, bold=True)
    cv.text(23, 1250, "※以上資訊僅供參考，不保證完整性與正確性；資料以各交易所公告為準。", 9, MUT)
    cv.text(23, 1268, "本圖由程式依公開資料自動產生，不構成任何投資建議，投資人應獨立判斷並自負盈虧。", 9, MUT)

    cv.save(out)
    return out
