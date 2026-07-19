#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日股票期貨篩選報告 → Email。

篩選公式與 screener.html 完全一致(同讀 data/rank.json),確保信件名單
跟網站篩選器按下去看到的結果相同。

環境變數:
  MAIL_USER  寄件 Gmail 帳號
  MAIL_PASS  Gmail 應用程式密碼 (16碼)
  MAIL_TO    收件者, 逗號分隔可多筆
  DRY_RUN=1  只印出結果不寄信 (本地驗證用)

注意: 本站 repo 為公開, 報告內容一律不寫入檔案/不 commit, 僅在記憶體處理後寄出。
"""
import os, sys, json, smtplib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
SITE = "https://david26984741-cell.github.io/daily-postmarket"
E = 1e8   # 億

# ---------------------------------------------------------------- 篩選設定
# 對應 screener.html 的 ①~⑤; 要改條件只動這一區即可。
RK        = 10        # ① 大額交易人: 10=前十大 / 5=前五大
SCALE_ON  = True      # ② 股票期貨規模區間 (億)
SCALE_LO  = 2.5
SCALE_HI  = 500
HOLD_ON   = True      # ③ 當日【口徑】持有
HOLD_MET  = "nat"     # t0=交易人合計 / main=主力 / nat=自然人 / inst=法人
HOLD_UNIT = "ratio"   # ratio=比率(%) / amt=規模(億)
HOLD_OP   = ">"       # > 或 <
HOLD_VAL  = 20
HOLD_ABS  = False     # 是否取絕對值
CHG_ON    = False     # ④ 當日【口徑】變化 (目前不啟用)
CHG_MET   = "main"
CHG_UNIT  = "amt"
CHG_OP    = ">"
CHG_VAL   = 0.5
CHG_ABS   = True
DAYS_ON   = True      # ⑤ 近X日漲跌
DAYS_N    = 20
DAYS_DIR  = "up"      # up=上漲 / down=下跌
SORT_KEY  = "hold"    # 排序: name/px/chg/scale/hold/dchg/chgN
SORT_DESC = True

MET = {"t0": "交易人合計", "main": "主力", "nat": "自然人", "inst": "法人"}


# ---------------------------------------------------------------- 公式 (對齊 screener.html)
def vals(r, has5):
    if RK == 5 and has5:
        return r.get("main5"), r.get("main5_prev"), r.get("inst5"), r.get("inst5_prev")
    return r.get("main"), r.get("main_prev"), r.get("inst"), r.get("inst_prev")


def lots(r, m, has5):
    t0, t0p, t1, t1p = vals(r, has5)
    def cv(a, b):
        if m == "t0":
            return a
        if m == "inst":
            return b
        if a is None or b is None:
            return None
        return a - b if m == "nat" else a - 2 * b     # nat=t0−t1, main=t0−2×t1
    return cv(t0, t1), cv(t0p, t1p)


def px(r):
    return r["fprice"] if r.get("fprice") is not None else r.get("price")


def pxp(r):
    if r.get("fprice") is not None:
        return r["fprice_prev"] if r.get("fprice_prev") is not None else r.get("price_prev")
    return r.get("price_prev")


def passes(v, op, target):
    return v > target if op == ">" else v < target


def compute(rank):
    rows = rank.get("rows", [])
    has5 = any(x.get("main5") is not None for x in rows)
    out = []
    for r in rows:
        p = px(r)
        if p is None:
            continue
        pp = pxp(r)
        chg_pct = (p - pp) / pp * 100 if pp else None
        moi = r.get("moi")
        scale = moi * p * r["shares"] if moi is not None else None

        h_cur, _ = lots(r, HOLD_MET, has5)
        hold = None
        if h_cur is not None:
            hold = (h_cur / moi * 100) if (HOLD_UNIT == "ratio" and moi) else h_cur * p * r["shares"]

        d_cur, d_prev = lots(r, CHG_MET, has5)
        dchg = None
        if d_cur is not None and d_prev is not None:
            if CHG_UNIT == "ratio":
                if moi and r.get("moi_prev"):
                    dchg = (d_cur / moi - d_prev / r["moi_prev"]) * 100
            else:
                dchg = (d_cur - d_prev) * p * r["shares"]

        ph = r.get("phist") or []
        chg_n = None
        if len(ph) >= 2:
            j = len(ph) - 1 - DAYS_N
            if j >= 0 and ph[j]:
                chg_n = (ph[-1] / ph[j] - 1) * 100

        # ---- 條件 ----
        if SCALE_ON:
            if scale is None:
                continue
            if SCALE_LO is not None and scale < SCALE_LO * E:
                continue
            if SCALE_HI is not None and scale > SCALE_HI * E:
                continue
        if HOLD_ON:
            if hold is None:
                continue
            hv = abs(hold) if HOLD_ABS else hold
            fac = 1 if HOLD_UNIT == "ratio" else E
            if not passes(hv, HOLD_OP, HOLD_VAL * fac):
                continue
        if CHG_ON:
            if dchg is None:
                continue
            dv = abs(dchg) if CHG_ABS else dchg
            fac = 1 if CHG_UNIT == "ratio" else E
            if not passes(dv, CHG_OP, CHG_VAL * fac):
                continue
        if DAYS_ON:
            if chg_n is None:
                continue
            if (chg_n <= 0) if DAYS_DIR == "up" else (chg_n >= 0):
                continue

        out.append({**r, "_px": p, "_chg": chg_pct, "_scale": scale,
                    "_hold": hold, "_dchg": dchg, "_chgN": chg_n})

    key = {"name": lambda x: x["name"], "px": lambda x: x["_px"], "chg": lambda x: x["_chg"] or 0,
           "scale": lambda x: x["_scale"] or 0, "hold": lambda x: x["_hold"] or 0,
           "dchg": lambda x: x["_dchg"] or 0, "chgN": lambda x: x["_chgN"] or 0}[SORT_KEY]
    out.sort(key=key, reverse=SORT_DESC)
    return out


# ---------------------------------------------------------------- 格式化
def f_amt(v):
    if v is None:
        return "—"
    a = abs(v)
    s = "-" if v < 0 else ""
    return s + (f"{a/E:.2f} 億" if a >= E else f"{a/1e4:.0f} 萬")


def f_pct(v, plus=True):
    if v is None:
        return "—"
    return f"{'+' if (plus and v > 0) else ''}{v:.2f}%"


def f_ratio(v):
    if v is None:
        return "—"
    return f"{'+' if v > 0 else ''}{v:.1f}%"


def cond_text():
    bits = [f"前{'十' if RK==10 else '五'}大"]
    if SCALE_ON:
        lo = f"{SCALE_LO:g}" if SCALE_LO is not None else ""
        hi = f"{SCALE_HI:g}" if SCALE_HI is not None else ""
        bits.append(f"股期規模 {lo}~{hi} 億")
    if HOLD_ON:
        u = "比率" if HOLD_UNIT == "ratio" else "規模"
        unit = "%" if HOLD_UNIT == "ratio" else " 億"
        bits.append(f"{MET[HOLD_MET]}持有{u} {HOLD_OP} {HOLD_VAL:g}{unit}")
    if CHG_ON:
        u = "比率" if CHG_UNIT == "ratio" else "規模"
        unit = "%" if CHG_UNIT == "ratio" else " 億"
        bits.append(f"{MET[CHG_MET]}變化{u} {CHG_OP} {CHG_VAL:g}{unit}")
    if DAYS_ON:
        bits.append(f"近{DAYS_N}日{'上漲' if DAYS_DIR=='up' else '下跌'}")
    return " ・ ".join(bits)


def build_html(rows, date):
    UP, DN, MUT, LINE = "#ff6b6b", "#4ade80", "#9aa7b4", "#2a3441"
    hold_hd = MET[HOLD_MET] + ("持有比率" if HOLD_UNIT == "ratio" else "持有規模")
    th = ('style="text-align:right;padding:8px 10px;border-bottom:1px solid %s;'
          'color:%s;font-weight:400;white-space:nowrap"' % (LINE, MUT))
    thl = th.replace("text-align:right", "text-align:left")
    td = 'style="text-align:right;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.05);white-space:nowrap"'
    tdl = td.replace("text-align:right", "text-align:left")

    head = (f'<tr><th {thl}>股票名稱</th><th {th}>收盤價</th><th {th}>漲跌%</th>'
            f'<th {th}>股票期貨規模</th><th {th}>{hold_hd}</th><th {th}>近{DAYS_N}日漲跌</th></tr>')

    body = []
    for r in rows:
        c = lambda v: UP if (v or 0) > 0 else (DN if (v or 0) < 0 else MUT)
        link = f'{SITE}/stocks.html?code={r["code"]}&rk={RK}&panels={HOLD_MET}'
        mini = ' <span style="color:%s;font-size:11px">小型</span>' % MUT if r.get("mini") else ""
        sid = f'<span style="color:{MUT};font-size:12.5px;margin-right:5px">{r["sid"]}</span>' if r.get("sid") else ""
        body.append(
            f'<tr>'
            f'<td {tdl}><a href="{link}" style="color:#7cc4ff;text-decoration:none">{sid}{r["name"]}</a>{mini}</td>'
            f'<td {td}>{r["_px"]:,.6g}</td>'
            f'<td {td}><span style="color:{c(r["_chg"])}">{f_pct(r["_chg"])}</span></td>'
            f'<td {td}>{f_amt(r["_scale"])}</td>'
            f'<td {td}><span style="color:{c(r["_hold"])}">'
            f'{f_ratio(r["_hold"]) if HOLD_UNIT=="ratio" else f_amt(r["_hold"])}</span></td>'
            f'<td {td}><span style="color:{c(r["_chgN"])}">{f_ratio(r["_chgN"])}</span></td>'
            f'</tr>')

    empty = (f'<tr><td colspan="6" style="padding:16px;color:{MUT}">本日無符合條件的個股。</td></tr>')
    return f"""<div style="background:#0f1620;padding:20px;font-family:-apple-system,'Segoe UI','Microsoft JhengHei',sans-serif;color:#e6edf3">
  <div style="font-size:18px;font-weight:700;margin-bottom:4px">股票期貨篩選報告</div>
  <div style="color:{MUT};font-size:13px;margin-bottom:14px">資料日期 <b style="color:#e6edf3">{date}</b> ・ 符合條件 <b style="color:#e6edf3">{len(rows)}</b> 檔</div>
  <div style="color:{MUT};font-size:12.5px;background:#161d27;border:1px solid {LINE};border-radius:8px;padding:9px 12px;margin-bottom:14px">
    篩選條件:{cond_text()}<br>排序:{MET[HOLD_MET]}持有{'比率' if HOLD_UNIT=='ratio' else '規模'}由大到小
  </div>
  <table style="border-collapse:collapse;font-size:14px;width:100%;background:#131a24;border:1px solid {LINE};border-radius:8px">
    <thead>{head}</thead><tbody>{''.join(body) if body else empty}</tbody>
  </table>
  <div style="color:{MUT};font-size:12px;margin-top:14px;line-height:1.7">
    點股票名稱可開啟該檔圖表(已自動切換為前{'十' if RK==10 else '五'}大、只顯示{MET[HOLD_MET]}面板)。<br>
    持有比率 = 淨部位 ÷ 全市場未沖銷口數;股票期貨規模 = 全市場未沖銷口數 × 近月股期收盤價 × 每口股數。<br>
    <a href="{SITE}/screener.html" style="color:#7cc4ff;text-decoration:none">開啟線上篩選器</a>
    ・資料來源:臺灣期貨交易所。本報告僅供參考,不構成投資建議。
  </div>
</div>"""


def build_text(rows, date):
    lines = [f"股票期貨篩選報告 — 資料日期 {date} — 符合 {len(rows)} 檔",
             f"條件:{cond_text()}", ""]
    for r in rows:
        hold = f_ratio(r["_hold"]) if HOLD_UNIT == "ratio" else f_amt(r["_hold"])
        lines.append(f'{(r.get("sid") or ""):>4} {r["name"]}  收{r["_px"]:g}  {f_pct(r["_chg"])}  '
                     f'規模{f_amt(r["_scale"])}  {MET[HOLD_MET]}{hold}  近{DAYS_N}日{f_ratio(r["_chgN"])}')
    if not rows:
        lines.append("(本日無符合條件的個股)")
    return "\n".join(lines)


# ---------------------------------------------------------------- 寄信
def send(subject, html, text):
    user = os.environ.get("MAIL_USER", "").strip()
    pwd = os.environ.get("MAIL_PASS", "").replace(" ", "").strip()
    to = [x.strip() for x in os.environ.get("MAIL_TO", "").split(",") if x.strip()]
    if not (user and pwd and to):
        print("缺少 MAIL_USER / MAIL_PASS / MAIL_TO,略過寄信")
        return False
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"已寄出給 {len(to)} 位收件者")
    return True


def main():
    rank = json.load(open(os.path.join(DATA, "rank.json"), encoding="utf-8"))
    date = rank.get("date", "")
    rows = compute(rank)
    html, text = build_html(rows, date), build_text(rows, date)
    print(text)
    if os.environ.get("DRY_RUN") == "1":
        print("\n[DRY_RUN] 不寄信")
        return
    send(f"[股期報告] {date} ・ 符合 {len(rows)} 檔", html, text)


if __name__ == "__main__":
    main()
