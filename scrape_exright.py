#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台股除權息事件爬蟲 (上市 TWSE + 上櫃 TPEx)

產出:
  data/exright/twse.json
  data/exright/tpex.json
  data/exright/_progress.json   (斷點續抓用)

端點 (皆已用瀏覽器 DevTools 實測確認, 非猜測):

  TWSE  GET  https://www.twse.com.tw/rwd/zh/exRight/TWT49U
             ?startDate=YYYYMMDD&endDate=YYYYMMDD&response=json
        成功判斷: j["stat"] == "OK"
        j["data"] 每列: [0]民國日期 [1]代號 [2]名稱 [3]除權息前收盤價
                        [4]除權息參考價 [5]權值+息值 [6]權/息 ...

  TPEx  POST https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ
             body: startDate=YYYY/MM/DD&endDate=YYYY/MM/DD&id=&response=json
             (注意: TPEx 送出的是「西元」日期, 不是民國)
        成功判斷: j["stat"].lower() == "ok"
        j["tables"][0]["data"] 每列:
             [0]民國日期 [1]代號 [2]名稱 [3]除權息前收盤價 [4]除權息參考價
             [5]權值 [6]息值 [7]權值+息值 [8]權/息 ...

        ※ TPEx 的 openapi/v1/tpex_exright_daily 只回傳最近數筆, 無日期參數,
          無法用於歷史回補 —— 已實測確認, 不要用。

設計原則 (對應規格書 §2.1 的陷阱):
  - 逐月抓取。跨年度區間會被靜默截斷。
  - stat 不正確一律視為失敗並重試, 絕不當成「當月無事件」。
  - 任何月份最終失敗都會寫進 failed 清單並讓程式以非零 exit code 結束。
    缺漏比沒有更糟, 所以絕不靜默略過。
  - 支援斷點續抓: 已完成月份寫入進度檔, 中斷後重跑會跳過。
"""

import os, sys, json, time, argparse, datetime
import urllib.request, urllib.parse, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(DATA, "exright")

TWSE_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

SLEEP = float(os.environ.get("EXRIGHT_SLEEP", "3.2"))   # 請求間隔, 規格書建議 >= 3 秒
RETRY = int(os.environ.get("EXRIGHT_RETRY", "4"))
RETRY_WAIT = float(os.environ.get("EXRIGHT_RETRY_WAIT", "8"))


def log(m):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {m}", flush=True)


def num(s):
    """'1,455.00' -> 1455.0 ; '' / '--' -> None"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s in ("", "-", "--", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def roc_to_ad(s):
    """'113年06月13日' 或 '113/06/04' -> '2024/06/13'"""
    s = str(s).strip()
    if "年" in s:
        y = s.split("年")[0]
        m = s.split("年")[1].split("月")[0]
        d = s.split("月")[1].split("日")[0]
    else:
        parts = s.replace("-", "/").split("/")
        if len(parts) != 3:
            raise ValueError(f"無法解析日期: {s!r}")
        y, m, d = parts
    return f"{int(y) + 1911:04d}/{int(m):02d}/{int(d):02d}"


def months(start_ym, end_ym):
    y, m = start_ym
    while (y, m) <= end_ym:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def last_day(y, m):
    if m == 12:
        return 31
    return (datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)).day


def http(url, data=None, headers=None, timeout=45):
    h = {"User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01",
         "X-Requested-With": "XMLHttpRequest"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


# --------------------------------------------------------------------- TWSE
def fetch_twse_month(y, m):
    """回傳 list[dict]; 失敗丟例外。"""
    sd = f"{y}{m:02d}01"
    ed = f"{y}{m:02d}{last_day(y, m):02d}"
    j = http(f"{TWSE_URL}?startDate={sd}&endDate={ed}&response=json",
             headers={"Referer": "https://www.twse.com.tw/zh/trading/exchange/twt49u.html"})
    stat = j.get("stat", "")
    if stat != "OK":
        # TWSE 查無資料時 stat 會是「很抱歉，沒有符合條件的資料!」
        if "沒有符合" in stat or "查無" in stat:
            return []
        raise RuntimeError(f"TWSE stat={stat!r}")
    out = []
    for r in j.get("data", []) or []:
        if len(r) < 7:
            continue
        pre, ref = num(r[3]), num(r[4])
        if pre is None or ref is None or pre <= 0 or ref <= 0:
            continue
        out.append({"date": roc_to_ad(r[0]), "sid": str(r[1]).strip(),
                    "name": str(r[2]).strip(), "pre_close": pre, "ref_price": ref,
                    "value": num(r[5]), "type": str(r[6]).strip()})
    return out


# --------------------------------------------------------------------- TPEx
def fetch_tpex_month(y, m):
    sd = f"{y}/{m:02d}/01"
    ed = f"{y}/{m:02d}/{last_day(y, m):02d}"
    j = http(TPEX_URL, data={"startDate": sd, "endDate": ed, "id": "", "response": "json"},
             headers={"Referer": "https://www.tpex.org.tw/zh-tw/announce/market/ex/cal.html"})
    if str(j.get("stat", "")).lower() != "ok":
        raise RuntimeError(f"TPEx stat={j.get('stat')!r}")
    tables = j.get("tables") or []
    if not tables:
        return []
    out = []
    for r in tables[0].get("data", []) or []:
        if len(r) < 9:
            continue
        pre, ref = num(r[3]), num(r[4])
        if pre is None or ref is None or pre <= 0 or ref <= 0:
            continue
        out.append({"date": roc_to_ad(r[0]), "sid": str(r[1]).strip(),
                    "name": str(r[2]).strip(), "pre_close": pre, "ref_price": ref,
                    "value": num(r[7]), "type": str(r[8]).strip()})
    return out


# --------------------------------------------------------------------- driver
FETCHERS = {"twse": fetch_twse_month, "tpex": fetch_tpex_month}


def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def run(market, start_ym, end_ym, resume=True):
    fetch = FETCHERS[market]
    out_path = os.path.join(OUT, f"{market}.json")
    prog_path = os.path.join(OUT, "_progress.json")

    doc = load(out_path, {"source": market.upper(), "records": []})
    prog = load(prog_path, {})
    done = set(prog.get(market, [])) if resume else set()

    # 以 (date, sid) 為鍵, 重跑時覆蓋同鍵而非重複追加
    by_key = {(r["date"], r["sid"]): r for r in doc.get("records", [])}
    by_month = {}
    failed = []

    todo = [(y, m) for y, m in months(start_ym, end_ym)]
    log(f"=== {market.upper()} 共 {len(todo)} 個月, 已完成 {len(done)} 個 ===")

    for y, m in todo:
        key = f"{y}-{m:02d}"
        if key in done:
            continue
        ok = False
        for attempt in range(1, RETRY + 1):
            try:
                rows = fetch(y, m)
                for r in rows:
                    by_key[(r["date"], r["sid"])] = r
                by_month[key] = len(rows)
                log(f"  {market} {key}: {len(rows)} 筆")
                ok = True
                break
            except Exception as e:
                log(f"  {market} {key}: 第 {attempt}/{RETRY} 次失敗 — {e}")
                if attempt < RETRY:
                    time.sleep(RETRY_WAIT)
        if ok:
            done.add(key)
            prog[market] = sorted(done)
            save(prog_path, prog)
        else:
            failed.append(key)
            log(f"  !! {market} {key} 最終失敗")
        time.sleep(SLEEP)

    recs = sorted(by_key.values(), key=lambda r: (r["date"], r["sid"]))
    doc = {"source": market.upper(),
           "updated_at": datetime.date.today().isoformat(),
           "months_fetched": len(done),
           "failed_months": failed,
           "records": recs}
    save(out_path, doc)
    log(f"=== {market.upper()} 完成: {len(recs)} 筆事件, 失敗月份 {failed or '無'} ===")
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["twse", "tpex", "both"], default="both")
    ap.add_argument("--start", default="2016-01", help="YYYY-MM")
    ap.add_argument("--end", default="", help="YYYY-MM, 預設本月")
    ap.add_argument("--no-resume", action="store_true")
    a = ap.parse_args()

    sy, sm = (int(x) for x in a.start.split("-"))
    if a.end:
        ey, em = (int(x) for x in a.end.split("-"))
    else:
        t = datetime.date.today()
        ey, em = t.year, t.month

    markets = ["twse", "tpex"] if a.market == "both" else [a.market]
    all_failed = {}
    for mk in markets:
        f = run(mk, (sy, sm), (ey, em), resume=not a.no_resume)
        if f:
            all_failed[mk] = f

    if all_failed:
        log(f"!!! 有月份抓取失敗, 未靜默略過: {all_failed}")
        return 1
    log("全部月份抓取成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
