#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日盤後資料抓取腳本 (台灣期交所 TAIFEX / 證交所 TWSE)

六大分類:
  1. 外資選擇權       <- callsAndPutsDate  (臺指選擇權 / 外資及陸資 / 未平倉)
  2. 自營選擇權       <- callsAndPutsDate  (臺指選擇權 / 自營商   / 未平倉)
  3. 外資期貨、現貨   <- futContractsDate  (臺股期貨 / 外資 / 未平倉) + TWSE BFI82U (外資現貨買賣差額)
  4. 大額交易人選擇權 <- largeTraderOptQry (臺指買權 / 臺指賣權)
  5. 大額交易人期貨   <- largeTraderFutQry (臺股期貨: 當月 + 所有契約, 不含週)
  6. 大額交易人股票期貨 <- largeTraderFutQry (各個股期貨, 依「契約名稱」對齊, 每檔獨立)

設計重點 (對應需求):
  - 嚴格驗證「來源頁顯示的資料日期 == 今天」, 否則等 30 分鐘重試 (可調), 多次失敗則標註「資料未更新」, 不以舊資料假冒。
  - 歷史資料以「日期」為鍵 append, 不覆蓋舊資料 (至少保留一年, 預設無限累積)。
  - 個股期貨一律以「商品代碼 / 契約名稱」對齊, 不用排序位置; 新增/下架自動處理。
  - 休市判斷: 週末 + holidays.txt + 「來源無當日資料」三重保護。

GitHub Actions 每交易日 15:00 後觸發。本地測試: python scrape.py --date 2026/06/23 --no-retry
"""

import os, sys, json, time, argparse, datetime, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STOCKS = os.path.join(DATA, "stocks")

TAIFEX = "https://www.taifex.com.tw/cht/3/"
TWSE_BFI = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"

# 來源 (CSV 下載端點皆為 Big5/MS950 編碼)
SRC = {
    "callsAndPuts": TAIFEX + "callsAndPutsDateDown",
    "futContracts": TAIFEX + "futContractsDateDown",
    "largeOpt":     TAIFEX + "largeTraderOptDown",
    "largeFut":     TAIFEX + "largeTraderFutDown",
}

RETRY_WAIT = int(os.environ.get("RETRY_WAIT", "1800"))   # 30 分鐘
MAX_RETRY  = int(os.environ.get("MAX_RETRY", "6"))       # 最多重試次數
UA = "Mozilla/5.0 (compatible; daily-postmarket-bot/1.0)"


# ----------------------------------------------------------------------------- helpers
def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)

def num(s):
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "--"):
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return 0

def http_get(url, params=None, big5=False, timeout=40, headers=None):
    if params:
        from urllib.parse import urlencode
        url = url + "?" + urlencode(params)
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return raw.decode("big5", errors="replace") if big5 else raw.decode("utf-8", errors="replace")

def fetch_taifex_csv(key, date_slash):
    """抓 TAIFEX 下載 CSV (Big5), 回傳已解析的列 (list[list[str]])。"""
    txt = http_get(SRC[key], {"queryStartDate": date_slash, "queryEndDate": date_slash}, big5=True)
    rows = []
    for line in txt.splitlines():
        if not line.strip():
            continue
        rows.append([c.strip() for c in line.split(",")])
    return rows  # rows[0] 為標題列

def csv_date_ok(rows, date_slash):
    """確認 CSV 內第一筆資料列的日期 == 目標日期。"""
    for r in rows[1:]:
        if r and r[0]:
            return r[0].strip() == date_slash
    return False


# ----------------------------------------------------------------------------- parsers
def parse_options(rows, identity_keyword):
    """callsAndPuts: 取臺指選擇權, 指定身份別, 只取未平倉。回傳 {call:{...}, put:{...}} 或 None。"""
    out = {}
    for r in rows[1:]:
        if len(r) < 16:
            continue
        product, cp, ident = r[1], r[2], r[3]
        if product != "臺指選擇權":
            continue
        if identity_keyword not in ident:
            continue
        rec = {
            "buy_oi_lots": num(r[10]), "buy_oi_amt": num(r[11]),
            "sell_oi_lots": num(r[12]), "sell_oi_amt": num(r[13]),
            "diff_oi_lots": num(r[14]), "diff_oi_amt": num(r[15]),
            "identity": ident,
        }
        if cp.upper().startswith("C") or "買權" in cp or cp == "CALL":
            out["call"] = rec
        else:
            out["put"] = rec
    return out or None


def parse_foreign_fut(rows):
    """futContracts: 臺股期貨 / 外資及陸資 / 未平倉。"""
    for r in rows[1:]:
        if len(r) < 15:
            continue
        if r[1] != "臺股期貨":
            continue
        if "外資" not in r[2]:
            continue
        return {
            "long_oi_lots": num(r[9]),  "long_oi_amt": num(r[10]),
            "short_oi_lots": num(r[11]), "short_oi_amt": num(r[12]),
            "net_oi_lots": num(r[13]),   "net_oi_amt": num(r[14]),
            "identity": r[2],
        }
    return None


def parse_twse_spot(date_yyyymmdd):
    """TWSE BFI82U: 外資及陸資(不含外資自營商) 買賣差額 (現貨)。
       TWSE 的 rwd 端點對非台灣 IP / 無 Referer 的請求可能拒絕, 故加上 Referer 並重試。"""
    hdr = {"Referer": "https://www.twse.com.tw/zh/trading/foreign/bfi82u.html",
           "Accept": "application/json, text/javascript, */*; q=0.01",
           "X-Requested-With": "XMLHttpRequest"}
    obj = None
    for i in range(3):
        try:
            txt = http_get(TWSE_BFI, {"response": "json", "date": date_yyyymmdd, "type": "day"}, headers=hdr)
            obj = json.loads(txt)
            if obj.get("stat") == "OK":
                break
        except Exception as e:
            log(f"  TWSE 第 {i+1}/3 次失敗: {e}")
        time.sleep(5)
    if not obj or obj.get("stat") != "OK":
        return None, (obj or {}).get("date", "")
    # 確認回傳日期
    ret_date = obj.get("date", "")
    if ret_date and ret_date != date_yyyymmdd:
        return None, ret_date
    for row in obj.get("data", []):
        if row and "外資及陸資" in row[0] and "不含外資自營商" in row[0]:
            return {
                "buy_amt": num(row[1]), "sell_amt": num(row[2]), "net_amt": num(row[3]),
                "unit": row[0],
            }, ret_date
    return None, ret_date


def parse_large_opt(rows):
    """largeTraderOpt: TXO 臺指買權 / 臺指賣權 全部列。"""
    call, put = [], []
    for r in rows[1:]:
        if len(r) < 11:
            continue
        code, name, cp, month, typ = r[1], r[2], r[3], r[4], r[5]
        if code != "TXO":
            continue
        rec = {
            "month": month, "type": typ,
            "top5_buy": num(r[6]), "top5_sell": num(r[7]),
            "top10_buy": num(r[8]), "top10_sell": num(r[9]),
            "market_oi": num(r[10]),
        }
        if "買權" in cp or cp.upper().startswith("C"):
            call.append(rec)
        else:
            put.append(rec)
    if not call and not put:
        return None
    return {"call": call, "put": put}


def _front_month(months):
    """從一組到期月份字串中, 取出『當月』(最小且非 999999/666666 的純數字月份)。"""
    cand = [m for m in months if m.isdigit() and len(m) == 6]
    return min(cand) if cand else None


def parse_large_fut(rows, want_name=None, want_codes=None):
    """largeTraderFut: 回傳 {key: {code,name,rows:[...]}}。
       want_name: 只取該契約名稱 (cat5 臺股期貨)。
       want_codes: 只取這些商品代碼 (cat6 個股)。
       每個契約只保留『當月』與『所有契約(999999)』, 不取週契約。"""
    groups = {}
    for r in rows[1:]:
        if len(r) < 10:
            continue
        code, name, month, typ = r[1], r[2], r[3], r[4]
        if want_name is not None and name != want_name:
            continue
        if want_codes is not None and code not in want_codes:
            continue
        g = groups.setdefault(code, {"code": code, "name": name, "_rows": []})
        g["_rows"].append({
            "month": month, "type": typ,
            "top5_buy": num(r[5]), "top5_sell": num(r[6]),
            "top10_buy": num(r[7]), "top10_sell": num(r[8]),
            "market_oi": num(r[9]),
        })
    # 每組篩選: 當月 + 所有契約
    for code, g in groups.items():
        months = [x["month"] for x in g["_rows"]]
        fm = _front_month(months)
        keep = []
        for x in g["_rows"]:
            if x["month"] == "999999" or x["month"] == fm:
                # 標註語意
                x = dict(x)
                x["scope"] = "所有契約" if x["month"] == "999999" else "當月"
                keep.append(x)
        g["rows"] = keep
        del g["_rows"]
    return groups


# ----------------------------------------------------------------------------- storage
def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)

def append_record(filename, meta, date_slash, record):
    path = os.path.join(DATA, filename)
    doc = load_json(path, {"meta": meta, "records": {}})
    doc["meta"] = meta
    doc["records"][date_slash] = record   # 以日期為鍵 append (覆蓋同日, 不動其它日)
    save_json(path, doc)

def append_stock(code, name, sid, date_slash, rows):
    path = os.path.join(STOCKS, f"{code}.json")
    doc = load_json(path, {"code": code, "name": name, "sid": sid, "records": {}})
    doc["name"] = name or doc.get("name", code)
    if sid:
        doc["sid"] = sid
    doc["records"][date_slash] = rows
    save_json(path, doc)


# ----------------------------------------------------------------------------- trading-day
def load_holidays():
    path = os.path.join(DATA, "holidays.txt")
    hol = set()
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                hol.add(ln.replace("-", "/"))
    return hol

def is_trading_day(date_slash):
    d = datetime.datetime.strptime(date_slash, "%Y/%m/%d").date()
    if d.weekday() >= 5:           # 六、日
        return False, "週末"
    if date_slash in load_holidays():
        return False, "休市日(holidays.txt)"
    return True, ""


# ----------------------------------------------------------------------------- main flow
def fetch_with_retry(key, date_slash, no_retry=False):
    """抓取並驗證當日資料; 非當日則 30 分鐘重試。回傳 (rows | None)。"""
    attempts = 1 if no_retry else MAX_RETRY
    for i in range(attempts):
        try:
            rows = fetch_taifex_csv(key, date_slash)
            if csv_date_ok(rows, date_slash):
                log(f"  {key}: 已確認當日資料 ({len(rows)-1} 列)")
                return rows
            log(f"  {key}: 資料尚非當日 (第 {i+1}/{attempts} 次)")
        except Exception as e:
            log(f"  {key}: 抓取錯誤 {e} (第 {i+1}/{attempts} 次)")
        if i < attempts - 1:
            log(f"  等待 {RETRY_WAIT//60} 分鐘後重試…")
            time.sleep(RETRY_WAIT)
    return None


def run(date_slash, no_retry=False):
    os.makedirs(STOCKS, exist_ok=True)
    yyyymmdd = date_slash.replace("/", "")
    status = {}

    trading, why = is_trading_day(date_slash)
    if not trading:
        log(f"{date_slash} 非交易日 ({why}), 結束。")
        return 0

    log(f"=== 開始抓取 {date_slash} ===")
    stock_map = load_json(os.path.join(DATA, "stock_map.json"), {})

    # --- 來源 1: callsAndPuts (cat1, cat2) ---
    cp_rows = fetch_with_retry("callsAndPuts", date_slash, no_retry)
    if cp_rows:
        c1 = parse_options(cp_rows, "外資")
        c2 = parse_options(cp_rows, "自營商")
        if c1: append_record("options_foreign.json", {"title": "外資選擇權", "source": "臺指選擇權-買賣權分計-未平倉"}, date_slash, c1)
        if c2: append_record("options_dealer.json",  {"title": "自營選擇權", "source": "臺指選擇權-買賣權分計-未平倉"}, date_slash, c2)
        status["options_foreign"] = "ok" if c1 else "no-data"
        status["options_dealer"]  = "ok" if c2 else "no-data"
    else:
        status["options_foreign"] = status["options_dealer"] = "資料未更新"

    # --- 來源 2: futContracts + TWSE (cat3) ---
    fut_rows = fetch_with_retry("futContracts", date_slash, no_retry)
    fut = parse_foreign_fut(fut_rows) if fut_rows else None
    try:
        spot, _ = parse_twse_spot(yyyymmdd)
    except Exception as e:
        log(f"  TWSE 抓取錯誤: {e}"); spot = None
    if spot is None:
        # 回補/重抓舊日期時 TWSE 常無歷史資料 — 保留該日既有的現貨值, 不以 null 覆蓋
        _old = load_json(os.path.join(DATA, "foreign_fut_spot.json"), {}).get("records", {}).get(date_slash)
        if _old and _old.get("spot"):
            spot = _old["spot"]
            log("  TWSE 無資料, 保留該日既有現貨值")
    if fut or spot:
        append_record("foreign_fut_spot.json",
                      {"title": "外資期貨、現貨", "source": "臺股期貨外資未平倉 + TWSE外資現貨買賣差額"},
                      date_slash, {"fut": fut, "spot": spot})
        status["foreign_fut_spot"] = "ok" if (fut and spot) else "partial"
    else:
        status["foreign_fut_spot"] = "資料未更新"

    # --- 來源 3: largeTraderOpt (cat4) ---
    lo_rows = fetch_with_retry("largeOpt", date_slash, no_retry)
    lo = parse_large_opt(lo_rows) if lo_rows else None
    if lo:
        append_record("large_opt.json", {"title": "大額交易人選擇權", "source": "臺指買權/臺指賣權"}, date_slash, lo)
        status["large_opt"] = "ok"
    else:
        status["large_opt"] = "資料未更新"

    # --- 來源 4: largeTraderFut (cat5 + cat6) ---
    lf_rows = fetch_with_retry("largeFut", date_slash, no_retry)
    if lf_rows:
        # cat5: 臺股期貨 (大額交易人期貨檔以「商品代碼 TXF」為鍵, 與選擇權 TXO 對應; 名稱備援)
        txf = parse_large_fut(lf_rows, want_codes={"TXF", "TX"}) or parse_large_fut(lf_rows, want_name="臺股期貨")
        if txf:
            g = list(txf.values())[0]
            append_record("large_fut_txf.json", {"title": "大額交易人期貨", "source": "臺股期貨 當月+所有契約"},
                          date_slash, {"code": g["code"], "name": g["name"], "rows": g["rows"]})
            status["large_fut_txf"] = "ok"
        else:
            status["large_fut_txf"] = "no-data"
        # cat6: 個股期貨 — 自動辨識, 新掛牌契約 (含小型) 免維護即納入。
        # 規則: 商品代碼恰為 2 碼者即個股/ETF期貨;
        #   例外排除 (1) 指數期貨 TX/TE/TF (其名稱亦帶括號合計公式, 雙重保險)
        #            (2) 3 碼代碼 = 指數/匯率/商品期貨 (TXF,GDF,BRF,XIF ...)
        NON_STOCK_2CHAR = {"TX", "TE", "TF"}
        stocks = parse_large_fut(lf_rows)
        n = 0
        new_codes = []
        for code, g in stocks.items():
            name = g["name"] or ""
            if len(code) != 2 or code in NON_STOCK_2CHAR or "(" in name or "(" in name:
                continue
            info = stock_map.get(code)
            if info is None:
                # 新掛牌: 自動補進對照表; 小型契約嘗試繼承本尊的證券代號
                short = name[:-2] if name.endswith("期貨") else (name or code)
                sid = ""
                if short.startswith("小型"):
                    base = short[2:]
                    for v in stock_map.values():
                        if v.get("short") == base and v.get("sid"):
                            sid = v["sid"]; break
                info = {"short": short, "sid": sid, "full": ""}
                stock_map[code] = info
                new_codes.append(f"{code} {name}")
            append_stock(code, name or info.get("short", code), info.get("sid", ""), date_slash, g["rows"])
            n += 1
        if new_codes:
            save_json(os.path.join(DATA, "stock_map.json"), stock_map)
            log("  新增個股期貨對照: " + "、".join(new_codes))
        status["stocks"] = f"ok ({n} 檔)"
        log(f"  個股期貨: 寫入 {n} 檔")
    else:
        status["large_fut_txf"] = status["stocks"] = "資料未更新"

    # --- 更新 index.json (供前端讀取) ---
    update_index(date_slash, status)
    log(f"=== 完成 {date_slash} ===  {status}")
    return 0


def update_index(date_slash, status):
    idx_path = os.path.join(DATA, "index.json")
    idx = load_json(idx_path, {"dates": [], "status_log": {}})
    dates = set(idx.get("dates", []))
    dates.add(date_slash)
    idx["dates"] = sorted(dates, reverse=True)
    idx["latest_date"] = latest = idx["dates"][0]
    # 蒐集所有個股 (一律以「最新交易日」為準;回補舊日期時不會把最新的個股清單洗掉)
    stocks = []
    if os.path.isdir(STOCKS):
        for fn in sorted(os.listdir(STOCKS)):
            if fn.endswith(".json"):
                d = load_json(os.path.join(STOCKS, fn), {})
                if latest in d.get("records", {}):
                    stocks.append({"code": d.get("code"), "name": d.get("name"), "sid": d.get("sid", "")})
    idx["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    idx["stocks"] = stocks
    idx["categories"] = [
        {"id": "options_foreign", "title": "外資選擇權",       "file": "options_foreign.json"},
        {"id": "options_dealer",  "title": "自營選擇權",       "file": "options_dealer.json"},
        {"id": "foreign_fut_spot","title": "外資期貨、現貨",   "file": "foreign_fut_spot.json"},
        {"id": "large_opt",       "title": "大額交易人選擇權", "file": "large_opt.json"},
        {"id": "large_fut_txf",   "title": "大額交易人期貨",   "file": "large_fut_txf.json"},
        {"id": "stocks",          "title": "大額交易人股票期貨","file": None},
    ]
    idx.setdefault("status_log", {})[date_slash] = status
    save_json(idx_path, idx)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY/MM/DD, 預設今天")
    ap.add_argument("--no-retry", action="store_true", help="不等 30 分鐘重試 (測試用)")
    a = ap.parse_args()
    if a.date:
        date_slash = a.date
    else:
        # 排程若被 GitHub 延遲跨過午夜才觸發, 「今天」盤後資料根本尚未公布 —
        # 凌晨~中午執行且未指定日期時, 改抓前一個平日 (2026/07/10 00:xx 即發生過)。
        now = datetime.datetime.now()
        d = now.date()
        if now.hour < 14:
            d -= datetime.timedelta(days=1)
            while d.weekday() >= 5:
                d -= datetime.timedelta(days=1)
            log(f"排程於 {now:%H:%M} 觸發 (盤後資料未公布), 改抓前一平日 {d:%Y/%m/%d}")
        date_slash = d.strftime("%Y/%m/%d")
    sys.exit(run(date_slash, no_retry=a.no_retry))
