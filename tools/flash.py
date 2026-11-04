#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盤後籌碼快報 — 一張圖看完當日大盤、三大法人、大額交易人、散戶指標、類股資金。

兩段式:
  collect  (daily.yml, 抓完資料後、commit 前)
      向 證交所 / 櫃買中心 / 期交所 抓當日數字, 存進 data/flash.json (依日期累積)。
      需要歷史的項目(連N買賣、近5/10日累積、走勢小圖、類股前5日均值)會自動回補:
        · 期交所的區間下載一次就拿到多日 → 每次都整段重算, 不怕漏
        · 證交所只能一天一天抓 → 只補 flash.json 裡還沒有的日子 (第一次跑約 2~3 分鐘)
      15:35 主班次證交所三大法人(BFI82U)常常還沒公布 → 先缺著, 21:35 備援會補上,
      report.py 的完整度指紋會因此改變 → 自動補寄一封完整的信。
  render   (report.yml)
      只讀 data/flash.json 畫圖, 不連網。輸出 0_盤後籌碼快報.png (檔名 0_ → 信件第一張)。

口徑 (2026/11/03 逐項與 統一期貨「盤後籌碼快報」對過, 全部一致):
  外資現貨 = BFI82U「外資及陸資(不含外資自營商)」; 自營 = 自行買賣 + 避險; 合計 = 合計列
  期貨合計 = 臺股期貨 + 小型臺指/4 + 微型臺指/20 的「多空未平倉口數淨額」
  選擇權   = TXO 未平倉契約金額買賣淨額 (千元 → 億)
  大額交易人 = largeTraderFutDown「TX+MTX/4+TMF/20」所有月份、全部交易人: 買方 − 賣方
  散戶指標 = −(三大法人該契約淨未平倉合計) ÷ 全市場未平倉(所有月份、一般時段) × 100
  PC ratio = 賣權未平倉 ÷ 買權未平倉 × 100
  類股雷達 = 上市普通股(證交所產業別), 成交占比 = 群組成交金額 ÷ 全體;
             均漲跌 = 群組內個股漲跌幅「等權平均」(不是類股指數);
             色彩 = 今日占比 − 前 5 個交易日占比平均 (pp)
  ⚠ 類股群組是我們依證交所官方產業別自己歸的, 統一期貨的歸類未公開,
    半導體/傳產等會有 ≤0.1 個百分點的差異, 屬正常。

用法:
  python tools/flash.py collect [--date YYYY/MM/DD]
  python tools/flash.py render  [--out .shots] [--date YYYY/MM/DD]
"""
import os, sys, json, time, argparse, datetime, urllib.request, urllib.error
from urllib.parse import urlencode

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
FLASH = os.path.join(DATA, "flash.json")

TAIFEX = "https://www.taifex.com.tw/cht/3/"
TAIFEX_VIX = "https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym}new.txt"
TWSE = "https://www.twse.com.tw/rwd/zh/"
TWSE_OPENAPI_IND = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_HL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/highlight"

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_RETRY_CODES = {429, 500, 502, 503, 504, 520, 521, 522, 524}

E8 = 1e8     # 元 → 億
K2E = 1e5    # 千元 → 億

IDENTS = [("foreign", "外資及陸資"), ("trust", "投信"), ("dealer", "自營商")]

# 類股雷達群組 (證交所 產業別 代碼)。顯示順序 = 此清單順序 (上排 4 個、下排 4 個)。
# 07 化學生技醫療、13 電子工業 是彙總類別, 個股不會掛這兩個碼。
SECTORS = [
    ("半導體",         {"24"}),
    ("電子零組件",     {"28"}),
    ("電腦及週邊",     {"25"}),
    ("通信網路及光電", {"26", "27"}),
    ("金融保險",       {"17"}),
    ("航運與運輸",     {"15"}),
    ("傳統產業",       None),            # None = 其餘全部
    ("其他類股",       {"20", "29", "30", "31", "36"}),
]

BFI_DAYS = 40      # 證交所三大法人回補天數 (連N買賣要看得夠長)
SEC_DAYS = 6       # 類股: 今日 + 前 5 日
KEEP_DAYS = 90     # flash.json 只留最近 N 個交易日


def now_taipei():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def log(msg):
    print(f"[{now_taipei():%H:%M:%S}] {msg}", flush=True)


def num(s):
    s = str(s if s is not None else "").strip().replace(",", "").replace("%", "")
    if s in ("", "-", "--", "---"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ============================================================== HTTP
def _req(url, params=None, data=None, headers=None, big5=False, tries=4, timeout=60):
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    h = {"User-Agent": BROWSER_UA}
    if headers:
        h.update(headers)
    body = urlencode(data).encode("utf-8") if data is not None else None
    if body is not None:
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return raw.decode("cp950", errors="replace") if big5 else raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in _RETRY_CODES:
                raise
        except Exception as e:        # 逾時 / 連線重置
            last = e
        if i < tries - 1:
            time.sleep(15 * (i + 1))
    raise last


def taifex_rows(path, params):
    """期交所 CSV 下載 → list[list[str]] (第 0 列為標題)。回 HTML(錯誤頁)時丟例外。"""
    txt = _req(TAIFEX + path, params, big5=True,
               headers={"Referer": TAIFEX + "futContractsDate"})
    if txt.lstrip().startswith("<"):
        raise RuntimeError(f"{path}: 回傳 HTML (查詢區間過長或無資料)")
    rows = [[c.strip() for c in ln.split(",")] for ln in txt.splitlines() if ln.strip()]
    return rows


def _col(header, *keys, default=None):
    for k in keys:
        for i, h in enumerate(header):
            if h == k:
                return i
    for k in keys:
        for i, h in enumerate(header):
            if k in h:
                return i
    return default


def _rng(d, days):
    a = d - datetime.timedelta(days=days)
    return {"queryStartDate": a.strftime("%Y/%m/%d"), "queryEndDate": d.strftime("%Y/%m/%d")}


# ============================================================== 期交所
FUT_NAMES = {"臺股期貨": 1.0, "小型臺指期貨": 0.25, "微型臺指期貨": 0.05}


def fetch_fut_contracts(d):
    """三大法人 期貨 區分各契約 (近 ~60 天)。
    回傳 {date: {"fut": {foreign/trust/dealer: 口(合計換算)}, "mtx": 三大法人小台淨, "tmf": 微台淨}}"""
    rows = taifex_rows("futContractsDateDown", _rng(d, 62))
    hd = rows[0]
    i_net = _col(hd, "多空未平倉口數淨額", default=13)
    out = {}
    for c in rows[1:]:
        if len(c) <= i_net or not c[0][:4].isdigit():
            continue
        name, ident = c[1], c[2]
        if name not in FUT_NAMES:
            continue
        v = num(c[i_net])
        if v is None:
            continue
        rec = out.setdefault(c[0], {"fut": {k: 0.0 for k, _ in IDENTS}, "mtx": 0.0, "tmf": 0.0, "_n": 0})
        for k, lab in IDENTS:
            if ident == lab:
                rec["fut"][k] += v * FUT_NAMES[name]
                rec["_n"] += 1
        if name == "小型臺指期貨":
            rec["mtx"] += v
        elif name == "微型臺指期貨":
            rec["tmf"] += v
    return {k: v for k, v in out.items() if v.pop("_n") >= 9}   # 3 契約 × 3 身份別都要到齊


def fetch_fut_daily(cid, d):
    """期貨每日行情 (單次查詢限一個月內)。
    回傳 {date: {"oi": 一般時段全部月份未平倉合計, "close": 近月收盤, "pct": 近月漲跌%}}
    近月 = 一般時段、6 碼月份(排除週契約/價差) 中成交量最大者。"""
    rows = taifex_rows("futDataDown", dict(down_type="1", commodity_id=cid, **_rng(d, 27)))
    hd = rows[0]
    i_m = _col(hd, "到期月份", default=2)
    i_c = _col(hd, "收盤價", default=6)
    i_p = _col(hd, "漲跌%", default=8)
    i_v = _col(hd, "成交量", default=9)
    i_oi = _col(hd, "未沖銷契約數", default=11)
    i_s = _col(hd, "交易時段", default=17)
    out = {}
    for c in rows[1:]:
        if len(c) <= max(i_oi, i_s) or c[1] != cid or not c[0][:4].isdigit():
            continue
        if c[i_s] and c[i_s] != "一般":
            continue
        rec = out.setdefault(c[0], {"oi": 0.0, "_vol": -1})
        rec["oi"] += num(c[i_oi]) or 0
        m = c[i_m]
        if len(m) == 6 and m.isdigit():
            vol = num(c[i_v]) or 0
            close = num(c[i_c])
            if close and vol > rec["_vol"]:
                rec["_vol"] = vol
                rec["close"] = close
                rec["pct"] = num(c[i_p])
    for v in out.values():
        v.pop("_vol", None)
    return out


def fetch_options(d):
    """三大法人 TXO 買賣權 未平倉契約金額淨額 → 億。{date: {ident: [call, put]}}"""
    rows = taifex_rows("callsAndPutsDateDown", dict(commodityId="TXO", **_rng(d, 20)))
    hd = rows[0]
    i_net = _col(hd, "未平倉契約金額買賣淨額", default=15)
    i_cp = _col(hd, "買賣權別", default=2)
    i_id = _col(hd, "身份別", default=3)
    out = {}
    for c in rows[1:]:
        if len(c) <= i_net or not c[0][:4].isdigit():
            continue
        v = num(c[i_net])
        if v is None:
            continue
        rec = out.setdefault(c[0], {k: [None, None] for k, _ in IDENTS})
        j = 0 if c[i_cp].upper().startswith("C") or "買" in c[i_cp] else 1
        for k, lab in IDENTS:
            if c[i_id] == lab:
                rec[k][j] = round(v / K2E, 4)
    return {k: v for k, v in out.items() if all(x is not None for p in v.values() for x in p)}


def fetch_pc(d):
    """PC ratio: {date: [賣權未平倉, 買權未平倉, 比率%]}"""
    rows = taifex_rows("pcRatioDown", _rng(d, 20))
    out = {}
    for c in rows[1:]:
        if len(c) >= 7 and c[0][:4].isdigit():
            p, cl, r = num(c[4]), num(c[5]), num(c[6])
            if p and cl:
                out[c[0]] = [p, cl, r]
    return out


def fetch_large(d):
    """大額交易人 TX+MTX/4+TMF/20 所有月份、全部交易人: {date: [前五淨, 前十淨]}"""
    rows = taifex_rows("largeTraderFutDown", _rng(d, 18))
    out = {}
    for c in rows[1:]:
        if len(c) >= 9 and c[1] == "TX" and c[3] == "999999" and c[4] == "0":
            b5, s5, b10, s10 = (num(x) for x in c[5:9])
            if None not in (b5, s5, b10, s10):
                out[c[0]] = [b5 - s5, b10 - s10]
    return out


def fetch_vix(d):
    """VIX 每日收盤 (月檔, tab 分隔): {date: vix}"""
    out = {}
    first = d.replace(day=1)
    prev = (first - datetime.timedelta(days=1))
    for ym in (prev.strftime("%Y%m"), d.strftime("%Y%m")):
        try:
            txt = _req(TAIFEX_VIX.format(ym=ym), big5=True, tries=2)
        except Exception as e:
            log(f"  VIX {ym} 失敗: {e}")
            continue
        for ln in txt.splitlines():
            f = [x.strip() for x in ln.split("\t") if x.strip()]
            if len(f) >= 3 and len(f[0]) == 8 and f[0].isdigit():
                v = num(f[2])
                if v:
                    out[f"{f[0][:4]}/{f[0][4:6]}/{f[0][6:]}"] = v
    return out


# ============================================================== 證交所 / 櫃買
TWSE_HDR = {"Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest"}


def twse_json(path, params, referer):
    h = dict(TWSE_HDR, Referer=referer)
    obj = json.loads(_req(TWSE + path, params, headers=h, tries=3))
    return obj


def fetch_bfi(ymd):
    """三大法人買賣金額 (億)。未公布/非交易日回 None。

    ⚠ 日期參數是 **dayDate** 不是 date (2026/11/05 查證):
      BFI82U?date=20261028 會「忽略日期」直接回最新一天 → 下面的日期檢查擋掉 → 歷史永遠抓不到,
      11/03~11/04 的快報「近5日/近10日」因此空白、「連N買賣」只算到 2 天。
      dayDate=20261028 才會回 10/28 那天。兩個都帶, 以防哪天證交所又改回來。"""
    obj = twse_json("fund/BFI82U", {"dayDate": ymd, "date": ymd, "type": "day", "response": "json"},
                    "https://www.twse.com.tw/zh/trading/foreign/bfi82u.html")
    if obj.get("stat") != "OK" or str(obj.get("date", "")) != ymd:
        return None
    rec = {}
    for r in obj.get("data", []):
        name, net = str(r[0]), num(r[3])
        if net is None:
            continue
        net = round(net / E8, 4)
        if "自行買賣" in name:
            rec["dealer_self"] = net
        elif "避險" in name:
            rec["dealer_hedge"] = net
        elif name.startswith("投信"):
            rec["trust"] = net
        elif "外資及陸資" in name:
            rec["foreign"] = net
        elif name.startswith("合計"):
            rec["total"] = net
    if not all(k in rec for k in ("dealer_self", "dealer_hedge", "trust", "foreign", "total")):
        return None
    rec["dealer"] = round(rec["dealer_self"] + rec["dealer_hedge"], 4)
    return rec


def _signed_chg(sign_cell, val):
    v = num(val)
    if v is None:
        return None
    return -abs(v) if "-" in str(sign_cell) else abs(v)


def fetch_twse_index(ymd):
    """加權 / 電子 / 金融 收盤與漲跌%。"""
    obj = twse_json("afterTrading/MI_INDEX", {"date": ymd, "type": "IND", "response": "json"},
                    "https://www.twse.com.tw/zh/trading/historical/mi-index.html")
    if obj.get("stat") != "OK" or str(obj.get("date", "")) != ymd:
        return None
    want = {"taiex": "發行量加權股價指數", "elec": "電子工業類指數", "fin": "金融保險類指數"}
    out = {}
    for tb in obj.get("tables", []):
        f = tb.get("fields") or []
        if not f or "收盤指數" not in f:
            continue
        i_c = f.index("收盤指數")
        i_s = _col(f, "漲跌(+/-)", "漲跌")
        i_p = _col(f, "漲跌百分比")
        for r in tb.get("data", []):
            for k, nm in want.items():
                if k not in out and str(r[0]).strip() == nm:
                    close = num(r[i_c])
                    pct = num(r[i_p]) if i_p is not None else None
                    if pct is not None and i_s is not None:
                        pct = _signed_chg(r[i_s], pct)
                    out[k] = [close, pct]
    return out if len(out) == 3 else None


def fetch_twse_amount(ymd):
    """上市成交金額 (億) — 大盤統計資訊「總計(1~15)」。"""
    obj = twse_json("afterTrading/MI_INDEX", {"date": ymd, "type": "MS", "response": "json"},
                    "https://www.twse.com.tw/zh/trading/historical/mi-index.html")
    if obj.get("stat") != "OK" or str(obj.get("date", "")) != ymd:
        return None
    for tb in obj.get("tables", []):
        f = tb.get("fields") or []
        i_a = _col(f, "成交金額")
        if i_a is None:
            continue
        for r in tb.get("data", []):
            if str(r[0]).startswith("總計"):
                v = num(r[i_a])
                if v:
                    return round(v / E8, 2)
    return None


def fetch_twse_stocks(ymd):
    """上市個股: {代號: (成交金額, 收盤, 帶號漲跌價差)}。"""
    obj = twse_json("afterTrading/MI_INDEX", {"date": ymd, "type": "ALLBUT0999", "response": "json"},
                    "https://www.twse.com.tw/zh/trading/historical/mi-index.html")
    if obj.get("stat") != "OK" or str(obj.get("date", "")) != ymd:
        return None
    for tb in obj.get("tables", []):
        f = tb.get("fields") or []
        if "每日收盤行情" not in (tb.get("title") or "") or "證券代號" not in f:
            continue
        i_id, i_amt, i_c = f.index("證券代號"), _col(f, "成交金額"), _col(f, "收盤價")
        i_s, i_d = _col(f, "漲跌(+/-)"), _col(f, "漲跌價差")
        out = {}
        for r in tb.get("data", []):
            sid = str(r[i_id]).strip()
            out[sid] = (num(r[i_amt]) or 0.0, num(r[i_c]), _signed_chg(r[i_s], r[i_d]))
        return out
    return None


def fetch_tpex(ymd):
    """上櫃指數 收盤與漲跌%。"""
    dslash = f"{ymd[:4]}/{ymd[4:6]}/{ymd[6:]}"
    txt = _req(TPEX_HL, data={"date": dslash, "response": "json"}, tries=3,
               headers={"Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/highlight.html",
                        "Accept": "application/json"})
    obj = json.loads(txt)
    if str(obj.get("stat", "")).lower() != "ok":
        return None
    for tb in obj.get("tables") or []:
        f = tb.get("fields") or []
        i_c, i_d = _col(f, "收市指數"), _col(f, "指數漲跌")
        if i_c is None or i_d is None or not tb.get("data"):
            continue
        r = tb["data"][0]
        close, chg = num(r[i_c]), num(r[i_d])
        if close and chg is not None:
            return [close, round(chg / (close - chg) * 100, 4)]
    return None


def fetch_industry():
    """上市公司 產業別: {公司代號: 兩碼產業別}"""
    arr = json.loads(_req(TWSE_OPENAPI_IND, tries=3, headers={"Accept": "application/json"}))
    out = {}
    for r in arr:
        sid = str(r.get("公司代號", "")).strip()
        ind = str(r.get("產業別", "")).strip()
        if sid and ind:
            out[sid] = ind.zfill(2)
    return out


def sector_stats(stocks, industry):
    """→ {群組: [成交占比%, 等權平均漲跌%]}  (只算 產業別 對照表裡的上市普通股)"""
    def group_of(code):
        for name, codes in SECTORS:
            if codes is not None and code in codes:
                return name
        return "傳統產業"
    amt, pcts, total = {}, {}, 0.0
    for sid, (a, close, chg) in stocks.items():
        ind = industry.get(sid)
        if not ind or not (len(sid) == 4 and sid.isdigit()) or sid.startswith("0"):
            continue
        g = group_of(ind)
        amt[g] = amt.get(g, 0.0) + a
        total += a
        if close and chg is not None and close - chg > 0:
            pcts.setdefault(g, []).append(chg / (close - chg) * 100)
    if total <= 0:
        return None
    return {name: [round(amt.get(name, 0.0) / total * 100, 4),
                   round(sum(pcts[name]) / len(pcts[name]), 4) if pcts.get(name) else None]
            for name, _ in SECTORS}


# ============================================================== collect
def load_flash():
    if os.path.exists(FLASH):
        try:
            return json.load(open(FLASH, encoding="utf-8"))
        except Exception:
            pass
    return {"days": {}}


def save_flash(doc):
    days = doc.get("days", {})
    for k in sorted(days)[:-KEEP_DAYS]:
        del days[k]
    tmp = FLASH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, FLASH)


def latest_date():
    try:
        return json.load(open(os.path.join(DATA, "rank.json"), encoding="utf-8"))["date"]
    except Exception:
        return now_taipei().strftime("%Y/%m/%d")


def _try(label, fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        log(f"  ⚠ {label} 失敗: {e}")
        return None


def collect(date_slash):
    D = datetime.datetime.strptime(date_slash, "%Y/%m/%d").date()
    doc = load_flash()
    days = doc.setdefault("days", {})
    log(f"盤後籌碼快報 collect: {date_slash}")

    def day(k):
        return days.setdefault(k, {})

    # ---- 期交所 (區間下載, 每次整段重算) ----
    fc = _try("期交所 三大法人期貨", fetch_fut_contracts, D) or {}
    oi = {}
    for cid in ("TX", "MTX", "TMF"):
        oi[cid] = _try(f"期交所 {cid} 行情", fetch_fut_daily, cid, D) or {}
    for k, v in fc.items():
        if k > date_slash:
            continue
        day(k)["fut"] = {i: round(x, 4) for i, x in v["fut"].items()}
        ret = {}
        for cid, key in (("MTX", "mtx"), ("TMF", "tmf")):
            m = oi[cid].get(k, {}).get("oi")
            if m:
                ret[key] = round(-v[key] / m * 100, 4)
        if len(ret) == 2:
            day(k)["retail"] = ret
    for k, v in oi["TX"].items():
        if k <= date_slash and v.get("close"):
            day(k)["tx"] = [v["close"], v.get("pct")]
    for label, fn, key in (("選擇權", fetch_options, "opt"), ("PC ratio", fetch_pc, "pc"),
                           ("大額交易人", fetch_large, "large"), ("VIX", fetch_vix, "vix")):
        res = _try(label, fn, D) or {}
        for k, v in res.items():
            if k <= date_slash:
                day(k)[key] = v
        log(f"  {label}: {len(res)} 天")
    log(f"  期貨法人: {len(fc)} 天, TX/MTX/TMF 行情: {len(oi['TX'])}/{len(oi['MTX'])}/{len(oi['TMF'])} 天")

    # 交易日清單: 期交所有資料的日子 (+ 今天, 期交所還沒出來也要先抓證交所)
    # 再併入 flash.json 既有日期 (都是過去抓到過資料的交易日) → 期交所今天掛了也照樣能回補證交所
    tdays = sorted(k for k in set(fc) | set(oi["TX"]) | set(days) if k <= date_slash)
    if date_slash not in tdays and D.weekday() < 5:
        tdays.append(date_slash)
    tdays = sorted(tdays)

    # ---- 證交所: 一天一天抓, 只補缺的 ----
    def ymd(k):
        return k.replace("/", "")

    save_flash(doc)          # 期交所部分先落地, 後面證交所就算被 timeout 砍掉也不會全丟
    n = 0
    deadline = time.time() + 420     # 證交所回補最多 7 分鐘 (step 上限 20 分鐘), 沒補完下一班會接著補
    # 由新到舊:時間不夠時優先補「近 5/10 日、連N買賣」用得到的最近幾天
    for k in reversed(tdays[-BFI_DAYS:]):
        if time.time() > deadline:
            log("  證交所三大法人: 回補達時間上限, 剩下的下一班再補")
            break
        # 最近 2 個交易日每次都重抓:證交所 15:0x 先給初版, 晚上會修正
        # (例:11/04 投信 276.31 → 272.58 億), 只補缺的話初版數字會永遠留在歷史裡。
        if "bfi" in days.get(k, {}) and k not in tdays[-2:]:
            continue
        r = _try(f"BFI82U {k}", fetch_bfi, ymd(k))
        n += 1
        if r:
            day(k)["bfi"] = r
        time.sleep(2.5)
    have = sum(1 for k in tdays[-10:] if days.get(k, {}).get("bfi"))
    log(f"  證交所三大法人: 補抓 {n} 天; 近 10 個交易日有 {have}/{len(tdays[-10:])} 天"
        + ("" if have == len(tdays[-10:]) else "  ⚠ 不足 → 快報「近5/10日」會空白"))

    sec_need = [k for k in tdays[-SEC_DAYS:] if "sec" not in days.get(k, {})]
    if sec_need:
        ind = doc.get("industry") or {}
        stale = (not ind.get("map")) or ind.get("updated", "") < (D - datetime.timedelta(days=7)).strftime("%Y/%m/%d")
        if stale:
            m = _try("上市公司產業別", fetch_industry)
            if m and len(m) > 500:
                doc["industry"] = ind = {"updated": date_slash, "map": m}
        imap = (doc.get("industry") or {}).get("map") or {}
        if imap:
            for k in sec_need:
                st = _try(f"個股行情 {k}", fetch_twse_stocks, ymd(k))
                if st:
                    s = sector_stats(st, imap)
                    if s:
                        day(k)["sec"] = s
                time.sleep(3)
        log(f"  類股: 補抓 {len(sec_need)} 天")

    today = day(date_slash)
    if not today.get("idx"):
        r = _try("證交所指數", fetch_twse_index, ymd(date_slash))
        if r:
            today["idx"] = r
        time.sleep(2.5)
    if not today.get("amt"):
        r = _try("證交所成交金額", fetch_twse_amount, ymd(date_slash))
        if r:
            today["amt"] = r
        time.sleep(1)
    if not today.get("otc"):
        r = _try("櫃買指數", fetch_tpex, ymd(date_slash))
        if r:
            today["otc"] = r

    save_flash(doc)
    miss = missing_parts(doc, date_slash)
    log("  完成" + (f", 缺: {'、'.join(miss)}" if miss else ", 當日資料齊全"))


# 當日「該有的」項目 → 中文名稱 (給 report.py 完整度指紋 / 信件標題缺漏標記用)
PARTS = [("idx", "指數"), ("otc", "櫃買"), ("amt", "成交金額"), ("tx", "台指期"),
         ("bfi", "法人現貨"), ("fut", "法人期貨"), ("opt", "法人選擇權"), ("pc", "PC"),
         ("large", "大額交易人"), ("retail", "散戶指標"), ("vix", "VIX"), ("sec", "類股")]


def missing_parts(doc, date_slash):
    t = (doc.get("days") or {}).get(date_slash) or {}
    return [lab for k, lab in PARTS if not t.get(k)]


# ============================================================== main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "render"])
    ap.add_argument("--date")
    ap.add_argument("--out", default=os.path.join(BASE, ".shots"))
    a = ap.parse_args()
    d = a.date or latest_date()
    if a.cmd == "collect":
        collect(d)
    else:
        from flash_render import render       # noqa: E402  (只有 render 需要 matplotlib)
        os.makedirs(a.out, exist_ok=True)
        render(load_flash(), d, os.path.join(a.out, "0_盤後籌碼快報.png"))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
