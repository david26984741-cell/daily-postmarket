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
# 對應網站篩選器的 ①~⑥;每一組 = 信件中的一個區塊。要改條件只動這一區。
#   rk        ① 10=前十大 / 5=前五大 / 6=第六~十大(前十−前五)
#   scale     ② 股期規模區間 (億), None=不限
#   hold      ③ (口徑, ratio|amt, 運算子, 門檻, 取絕對值)
#   chg       ④ 同上, None=不啟用
#   days      ⑤ (X日, up|down), None=不啟用
#   sratio    ⑥ 股期規模 ÷ 現貨近五日均成交金額 (%) → (運算子, 門檻), None=不啟用
#   mode      "hilo"=同時出前N高與前N低兩張表 / "top"=只出一張(依排序取前N)
SCANS = [
    {"title": "主力持有比率", "rk": 6, "scale": (2.5, 100),
     "hold": ("main", "ratio", ">", 0, True), "chg": None, "days": None, "sratio": None,
     "sort": "hold", "desc": True, "mode": "hilo", "top": 20},

    {"title": "第六~十大・法人持有比率", "rk": 6, "scale": (2.5, 500),
     "hold": ("inst", "ratio", ">", 0, True), "chg": ("inst", "ratio", ">", 0, True),
     "days": None, "sratio": None,
     "sort": "hold", "desc": True, "mode": "hilo", "top": 10},
]

MET = {"t0": "交易人合計", "main": "主力", "nat": "自然人", "inst": "法人"}
RK_TAG = {10: "前十大", 5: "前五大", 6: "第六~十大"}


# ---------------------------------------------------------------- 公式 (對齊 screener.html)
def _sub(a, b):
    return a - b if (a is not None and b is not None) else None


def vals(r, has5, rk):
    if rk == 5 and has5:
        return r.get("main5"), r.get("main5_prev"), r.get("inst5"), r.get("inst5_prev")
    if rk == 6 and has5:   # 第六~十大 = 前十大 − 前五大 (t0/t1 各自相減)
        return (_sub(r.get("main"), r.get("main5")), _sub(r.get("main_prev"), r.get("main5_prev")),
                _sub(r.get("inst"), r.get("inst5")), _sub(r.get("inst_prev"), r.get("inst5_prev")))
    return r.get("main"), r.get("main_prev"), r.get("inst"), r.get("inst_prev")


def lots(r, m, has5, rk):
    t0, t0p, t1, t1p = vals(r, has5, rk)
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


def compute(rank, cfg):
    """依單一組設定 cfg 篩選並排序, 回傳 row 清單。"""
    rows = rank.get("rows", [])
    has5 = any(x.get("main5") is not None for x in rows)
    rk = cfg["rk"]
    hm, hu, hop, hv0, habs = cfg["hold"]
    cm, cu, cop, cv0, cabs = cfg["chg"] if cfg["chg"] else (None,)*5
    out = []
    for r in rows:
        p = px(r)
        if p is None:
            continue
        pp = pxp(r)
        chg_pct = (p - pp) / pp * 100 if pp else None
        moi = r.get("moi")
        scale = moi * p * r["shares"] if moi is not None else None
        samt = r.get("samt5")
        sratio = (scale / samt * 100) if (scale is not None and samt) else None

        h_cur, _ = lots(r, hm, has5, rk)
        hold = None
        if h_cur is not None:
            hold = (h_cur / moi * 100) if (hu == "ratio" and moi) else h_cur * p * r["shares"]

        dchg = None
        if cm:
            d_cur, d_prev = lots(r, cm, has5, rk)
            if d_cur is not None and d_prev is not None:
                if cu == "ratio":
                    if moi and r.get("moi_prev"):
                        dchg = (d_cur / moi - d_prev / r["moi_prev"]) * 100
                else:
                    dchg = (d_cur - d_prev) * p * r["shares"]

        chg_n = None
        if cfg["days"]:
            ph = r.get("phist") or []
            n = cfg["days"][0]
            if len(ph) >= 2:
                j = len(ph) - 1 - n
                if j >= 0 and ph[j]:
                    chg_n = (ph[-1] / ph[j] - 1) * 100

        # ---- 條件 ----
        if cfg["scale"]:
            lo, hi = cfg["scale"]
            if scale is None:
                continue
            if lo is not None and scale < lo * E:
                continue
            if hi is not None and scale > hi * E:
                continue
        if hold is None:
            continue
        hvv = abs(hold) if habs else hold
        if not passes(hvv, hop, hv0 * (1 if hu == "ratio" else E)):
            continue
        if cfg["chg"]:
            if dchg is None:
                continue
            dvv = abs(dchg) if cabs else dchg
            if not passes(dvv, cop, cv0 * (1 if cu == "ratio" else E)):
                continue
        if cfg["days"]:
            if chg_n is None:
                continue
            if (chg_n <= 0) if cfg["days"][1] == "up" else (chg_n >= 0):
                continue
        if cfg["sratio"]:
            op, thr = cfg["sratio"]
            if sratio is None:
                continue
            if not passes(sratio, op, thr):
                continue

        out.append({**r, "_px": p, "_chg": chg_pct, "_scale": scale,
                    "_hold": hold, "_dchg": dchg, "_chgN": chg_n, "_sRat": sratio})

    key = {"name": lambda x: x["name"], "px": lambda x: x["_px"], "chg": lambda x: x["_chg"] or 0,
           "scale": lambda x: x["_scale"] or 0, "hold": lambda x: x["_hold"] or 0,
           "dchg": lambda x: x["_dchg"] or 0, "chgN": lambda x: x["_chgN"] or 0,
           "sRat": lambda x: x["_sRat"] or 0}[cfg["sort"]]
    out.sort(key=key, reverse=cfg["desc"])
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


def cond_text(cfg):
    bits = [RK_TAG.get(cfg["rk"], "前十大")]
    if cfg["scale"]:
        lo, hi = cfg["scale"]
        bits.append(f"股期規模 {lo if lo is not None else ''}~{hi if hi is not None else ''} 億")
    hm, hu, hop, hv0, habs = cfg["hold"]
    u = "比率" if hu == "ratio" else "規模"
    unit = "%" if hu == "ratio" else " 億"
    bits.append(f"{MET[hm]}持有{u} {'|x| ' if habs else ''}{hop} {hv0:g}{unit}")
    if cfg["chg"]:
        cm, cu, cop, cv0, cabs = cfg["chg"]
        u = "比率" if cu == "ratio" else "規模"
        unit = "%" if cu == "ratio" else " 億"
        bits.append(f"{MET[cm]}變化{u} {'|x| ' if cabs else ''}{cop} {cv0:g}{unit}")
    if cfg["days"]:
        bits.append(f"近{cfg['days'][0]}日{'上漲' if cfg['days'][1]=='up' else '下跌'}")
    if cfg["sratio"]:
        op, thr = cfg["sratio"]
        bits.append(f"股期/現貨成交 {op} {thr:g}%")
    return " ・ ".join(bits)


UPC, DNC, MUT, LINE = "#ff6b6b", "#4ade80", "#9aa7b4", "#2a3441"


def _srtxt(r):
    v = r.get("_sRat")
    return "—" if v is None else f"{v:.0f}%"


def _table(rows, cfg, title, note):
    """單一排行表 (標題 + 表格) 的 HTML。"""
    hm, hu = cfg["hold"][0], cfg["hold"][1]
    hold_hd = MET[hm] + ("持有比率" if hu == "ratio" else "持有規模")
    th = ('style="text-align:right;padding:8px 10px;border-bottom:1px solid %s;'
          'color:%s;font-weight:400;white-space:nowrap"' % (LINE, MUT))
    thl = th.replace("text-align:right", "text-align:left")
    td = 'style="text-align:right;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.05);white-space:nowrap"'
    tdl = td.replace("text-align:right", "text-align:left")

    has_chg, has_days, has_sr = bool(cfg["chg"]), bool(cfg["days"]), bool(cfg["sratio"])
    chg_hd = ""
    if has_chg:
        cm, cu = cfg["chg"][0], cfg["chg"][1]
        chg_hd = MET[cm] + ("變化比率" if cu == "ratio" else "變化規模")
    head = (f'<tr><th {thl}>股票名稱</th><th {th}>收盤價</th><th {th}>漲跌%</th>'
            f'<th {th}>股票期貨規模</th><th {th}>{hold_hd}</th>'
            + (f'<th {th}>{chg_hd}</th>' if has_chg else "")
            + (f'<th {th}>近{cfg["days"][0]}日漲跌</th>' if has_days else "")
            + (f'<th {th}>股期/現貨成交</th>' if has_sr else "")
            + '</tr>')

    body = []
    for r in rows:
        c = lambda v: UPC if (v or 0) > 0 else (DNC if (v or 0) < 0 else MUT)
        link = f'{SITE}/stocks.html?code={r["code"]}&rk={cfg["rk"]}&panels={hm}'
        mini = ' <span style="color:%s;font-size:11px">小型</span>' % MUT if r.get("mini") else ""
        sid = f'<span style="color:{MUT};font-size:12.5px;margin-right:5px">{r["sid"]}</span>' if r.get("sid") else ""
        body.append(
            f'<tr>'
            f'<td {tdl}><a href="{link}" style="color:#7cc4ff;text-decoration:none">{sid}{r["name"]}</a>{mini}</td>'
            f'<td {td}>{r["_px"]:,.6g}</td>'
            f'<td {td}><span style="color:{c(r["_chg"])}">{f_pct(r["_chg"])}</span></td>'
            f'<td {td}>{f_amt(r["_scale"])}</td>'
            f'<td {td}><span style="color:{c(r["_hold"])}">'
            f'{f_ratio(r["_hold"]) if hu=="ratio" else f_amt(r["_hold"])}</span></td>'
            + (f'<td {td}><span style="color:{c(r["_dchg"])}">'
               f'{f_ratio(r["_dchg"]) if cfg["chg"][1]=="ratio" else f_amt(r["_dchg"])}</span></td>' if has_chg else "")
            + (f'<td {td}><span style="color:{c(r["_chgN"])}">{f_ratio(r["_chgN"])}</span></td>' if has_days else "")
            + (f'<td {td}>{_srtxt(r)}</td>' if has_sr else "")
            + '</tr>')

    empty = (f'<tr><td colspan="8" style="padding:16px;color:{MUT}">本日無符合條件的個股。</td></tr>')
    return f"""
  <div style="font-size:15px;font-weight:700;margin:20px 0 4px">{title}
    <span style="color:{MUT};font-size:12px;font-weight:400;margin-left:8px">{note}</span></div>
  <div style="color:{MUT};font-size:11.5px;margin-bottom:6px">篩選:{cond_text(cfg)}</div>
  <table style="border-collapse:collapse;font-size:14px;width:100%;background:#131a24;border:1px solid {LINE};border-radius:8px">
    <thead>{head}</thead><tbody>{''.join(body) if body else empty}</tbody>
  </table>"""


def fill_samt5(rank):
    """rank.json 若無 samt5 (舊版 scrape.py 產生的檔), 就地由 data/kline 補算,
    使 ⑥股期/現貨成交 條件不會因為欄位缺漏而全部落空。"""
    rows = rank.get("rows", [])
    if any(r.get("samt5") for r in rows):
        return
    latest = rank.get("date", "")
    kd = os.path.join(DATA, "kline")
    for r in rows:
        sid = r.get("sid")
        if not sid:
            continue
        try:
            recs = json.load(open(os.path.join(kd, f"{sid}.json"), encoding="utf-8"))["records"]
        except Exception:
            continue
        vals = []
        for d in sorted((d for d in recs if d <= latest), reverse=True):
            k = recs[d]
            if k and len(k) >= 5 and k[3] and k[4]:
                vals.append(k[3] * k[4])
                if len(vals) >= 5:
                    break
        if vals:
            r["samt5"] = round(sum(vals) / len(vals))


def _blocks(rank):
    """跑完所有 SCANS → [(cfg, 標題, 註解, rows), ...]"""
    out = []
    for cfg in SCANS:
        rows = compute(rank, cfg)
        hm, hu = cfg["hold"][0], cfg["hold"][1]
        nm = MET[hm] + ("持有比率" if hu == "ratio" else "持有規模")
        n = cfg["top"]
        if cfg["mode"] == "hilo":
            out.append((cfg, f"▲ {nm} 前 {min(n,len(rows))} 高", f"{nm}由大到小(偏多)", rows[:n], len(rows)))
            out.append((cfg, f"▼ {nm} 前 {min(n,len(rows))} 低", f"{nm}由小到大(偏空)", rows[::-1][:n], len(rows)))
        else:
            out.append((cfg, f"◆ {cfg['title']}", f"依{nm}排序,取前 {min(n,len(rows))} 檔", rows[:n], len(rows)))
    return out


def build_html(blocks, date):
    tables = "".join(_table(rows, cfg, title, note + f" ・符合 {tot} 檔")
                     for cfg, title, note, rows, tot in blocks)
    return f"""<div style="background:#0f1620;padding:20px;font-family:-apple-system,'Segoe UI','Microsoft JhengHei',sans-serif;color:#e6edf3">
  <div style="font-size:18px;font-weight:700;margin-bottom:4px">股票期貨篩選報告</div>
  <div style="color:{MUT};font-size:13px;margin-bottom:6px">資料日期 <b style="color:#e6edf3">{date}</b></div>
  {tables}
  <div style="color:{MUT};font-size:12px;margin-top:16px;line-height:1.7">
    點股票名稱可開啟該檔圖表(自動切換為該區塊的口徑與面板)。<br>
    持有比率 = 淨部位 ÷ 全市場未沖銷口數;股期/現貨成交 = 股期規模 ÷ 現貨近五日均成交金額。<br>
    <a href="{SITE}/screener.html" style="color:#7cc4ff;text-decoration:none">開啟線上篩選器</a>
    ・資料來源:臺灣期貨交易所、臺灣證券交易所。本報告僅供參考,不構成投資建議。
  </div>
</div>"""


def build_text(blocks, date):
    lines = [f"股票期貨篩選報告 — 資料日期 {date}", ""]
    for cfg, title, note, rows, tot in blocks:
        hm, hu = cfg["hold"][0], cfg["hold"][1]
        lines.append(f"{title}({note} ・符合 {tot} 檔)")
        lines.append(f"  篩選:{cond_text(cfg)}")
        if not rows:
            lines.append("  (無符合)")
        for r in rows:
            hold = f_ratio(r["_hold"]) if hu == "ratio" else f_amt(r["_hold"])
            extra = f'  股期/現貨 {r["_sRat"]:.0f}%' if (cfg["sratio"] and r["_sRat"] is not None) else ""
            lines.append(f'  {(r.get("sid") or ""):>6} {r["name"]}  收{r["_px"]:g}  {f_pct(r["_chg"])}  '
                         f'規模{f_amt(r["_scale"])}  {MET[hm]}{hold}{extra}')
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 附圖
# tools/shots.py 產生的每日截圖; 目錄不進版控 (repo 公開), 僅作為 email 附件。
SHOTS_DIR = os.environ.get("SHOTS_DIR", os.path.join(BASE, ".shots"))


def collect_shots():
    """回傳 [(檔名, bytes), ...],依檔名排序 (1_…5_ 前綴決定順序)。無圖則回空清單。"""
    if not os.path.isdir(SHOTS_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(SHOTS_DIR)):
        if not fn.lower().endswith(".png"):
            continue
        path = os.path.join(SHOTS_DIR, fn)
        try:
            with open(path, "rb") as f:
                out.append((fn, f.read()))
        except OSError as e:
            print(f"  略過附圖 {fn}: {e}")
    return out


# ---------------------------------------------------------------- 寄信
def send(subject, html, text, shots=None):
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
    for fn, data in (shots or []):
        msg.add_attachment(data, maintype="image", subtype="png", filename=fn)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=120) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"已寄出給 {len(to)} 位收件者" + (f",附圖 {len(shots)} 張" if shots else ""))
    return True


# 影響信件內容的資料檔:①~④ 附圖由 charts.py 讀這四個, 報告表格與 ⑤~⑧ 排行圖讀 rank.json。
# (⑨ 選擇權籌碼是 runner 即時抓、不進 repo, 無法納入指紋, 也不影響「資料補齊要重寄」的判斷。)
SIG_FILES = ["foreign_fut_spot.json", "options_foreign.json",
             "options_dealer.json", "large_fut_txf.json"]


def content_sig():
    """當日資料的「內容指紋」— 給 report.yml 當防重複快取的一部分。

    為什麼需要:原本防重複只看「資料日期」, 所以 15:35 主班次抓不到證交所現貨(常見:
    BFI82U 公布得比 15:35 晚)就先寄了一封缺圖的信, 21:35 備援補到資料後
    因為「今天寄過了」而不再寄 —— 使用者永遠只收到殘缺那封, 而且網站是對的、信是錯的。
    把資料本身納入指紋後:資料有補齊 → 指紋變 → 重寄;資料沒變 → 指紋同 → 不重寄。

    只取「當日那一筆」而非整檔, 這樣歷史回補不會誤觸重寄。
    rank.json 只取 date 與筆數 —— 整份 hash 太敏感(重建時的細微差異會造成無謂重寄)。
    """
    import hashlib
    parts = []
    try:
        rk = json.load(open(os.path.join(DATA, "rank.json"), encoding="utf-8"))
        date = rk.get("date", "")
        parts += ["rank", date, str(len(rk.get("rows") or []))]
    except Exception:
        return "nodata"
    for fn in SIG_FILES:
        rec = None
        try:
            d = json.load(open(os.path.join(DATA, fn), encoding="utf-8"))
            rec = (d.get("records") or {}).get(date)
        except Exception:
            pass
        parts.append(fn + "=" + json.dumps(rec, sort_keys=True, ensure_ascii=False))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def data_gaps():
    """當日還缺哪些資料 — 標在信件標題上。

    修好防重複之後, 資料不齊的日子會收到兩封信(先殘缺、補齊後再一封)。
    沒有標記的話兩封長得一樣, 分不出哪封才是完整的。
    """
    try:
        rk = json.load(open(os.path.join(DATA, "rank.json"), encoding="utf-8"))
        date = rk.get("date", "")
    except Exception:
        return ["排行資料"]
    gaps = []
    for fn, label in [("foreign_fut_spot.json", "外資期貨現貨"),
                      ("options_foreign.json", "外資選擇權"),
                      ("options_dealer.json", "自營選擇權"),
                      ("large_fut_txf.json", "大額交易人期貨")]:
        try:
            rec = (json.load(open(os.path.join(DATA, fn), encoding="utf-8"))
                   .get("records") or {}).get(date)
        except Exception:
            rec = None
        if not rec:
            gaps.append(label)
        elif fn == "foreign_fut_spot.json":
            # 這一項最常出包:證交所 BFI82U 公布得比 15:35 主班次晚, 期貨有、現貨還沒有
            if not rec.get("spot"):
                gaps.append("外資現貨")
            if not rec.get("fut"):
                gaps.append("外資期貨")
    return gaps


def main():
    if "--sig" in sys.argv:          # 給 workflow 取指紋用, 不做其他事
        print(content_sig())
        return
    rank = json.load(open(os.path.join(DATA, "rank.json"), encoding="utf-8"))
    date = rank.get("date", "")
    fill_samt5(rank)
    blocks = _blocks(rank)
    html = build_html(blocks, date)
    text = build_text(blocks, date)
    print(text)
    shots = collect_shots()
    print(f"\n附圖 {len(shots)} 張: " + (", ".join(fn for fn, _ in shots) if shots else "(無)"))
    if os.environ.get("DRY_RUN") == "1":
        print("\n[DRY_RUN] 不寄信")
        return
    n = sum(len(r) for _, _, _, r, _ in blocks)
    gaps = data_gaps()
    # 資料補齊後會再寄一封, 標題沒有「⚠缺」的那封才是完整版
    tag = ("　⚠缺:" + "、".join(gaps)) if gaps else ""
    send(f"[股期報告] {date} ・ {len(blocks)} 張排行{tag}", html, text, shots)


if __name__ == "__main__":
    main()
