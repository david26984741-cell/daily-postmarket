"""
籌碼回測 — 共用底層 (base layer)

只做三件事,不含任何策略邏輯與結論:
  1. 讀大額交易人未沖銷部位 -> 九種族群淨部位 -> 持有比率
  2. 讀現股日K + 除權息還原因子 -> 還原收盤價
  3. 對齊成 DataFrame (index=日期, columns=股期代號),存 pickle 快取

口徑依交接文件 2026-08-15-籌碼回測重啟.md 第二節:
  a5/a10 = 前五/前十大「交易人」淨部位 (type 0, buy-sell)
  s5/s10 = 前五/前十大「特定法人」淨部位 (type 1, buy-sell)
  自然人 = 交易人 - 特定法人
  主力   = 自然人 - 特定法人 = 交易人 - 2*特定法人
  6-10大 = 前十 - 前五
  持有比率 = 族群淨部位 / market_oi
全部取 month == "999999" (所有契約)

用法:
    from base import load
    D = load()                 # 有快取就讀快取
    D = load(rebuild=True)     # 強制重建
    D['ratio']['主力6-10']     # DataFrame 持有比率
    D['px']                    # DataFrame 現股還原收盤
"""

import json
import os
import pickle
import time

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = "/tmp/chips_base.pkl"

# 九種族群: (族群, 檔位)
FAMILIES = ["交易人", "特定法人", "自然人", "主力"]
SLICES = ["前五", "前十", "6-10"]


def _net(a5, a10, s5, s10, fam, sl):
    """由 a5/a10/s5/s10 推出指定族群、指定檔位的淨部位"""
    if sl == "前五":
        a, s = a5, s5
    elif sl == "前十":
        a, s = a10, s10
    else:  # 6-10 = 前十 - 前五
        a, s = a10 - a5, s10 - s5

    if fam == "交易人":
        return a
    if fam == "特定法人":
        return s
    if fam == "自然人":
        return a - s
    if fam == "主力":
        return a - 2 * s
    raise ValueError(fam)


def _read_chips():
    """回傳 dict: code -> {date -> (a5, a10, s5, s10, moi)}"""
    base = os.path.join(REPO, "data", "stocks")
    out = {}
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".json"):
            continue
        code = fn[:-5]
        try:
            d = json.load(open(os.path.join(base, fn), encoding="utf-8"))
        except Exception:
            continue
        rows = {}
        for date, recs in d.get("records", {}).items():
            r0 = r1 = None
            for r in recs:
                if r.get("month") != "999999":
                    continue
                if r.get("type") == "0":
                    r0 = r
                elif r.get("type") == "1":
                    r1 = r
            if r0 is None or r1 is None:
                continue
            moi = r0.get("market_oi") or 0
            if not moi:
                continue
            rows[date] = (
                r0["top5_buy"] - r0["top5_sell"],
                r0["top10_buy"] - r0["top10_sell"],
                r1["top5_buy"] - r1["top5_sell"],
                r1["top10_buy"] - r1["top10_sell"],
                moi,
            )
        if rows:
            out[code] = rows
    return out


def _read_px():
    """
    回傳 dict of {sid: {date: value}}:
      adjc  還原收盤 = 原始收盤 * adjfactor   -> 算報酬用
      adjo  還原開盤 = 原始開盤 * adjfactor   -> 算報酬用(開盤版進場)
      rawc  原始收盤                          -> 算金額/規模用(還原價不是真實價)
      amt   現貨成交金額 = 成交股數 * 原始收盤 -> 算「股期規模/現貨成交金額」用
      lock  當日一價到底 (高==低)             -> 不可成交判定
    """
    kdir = os.path.join(REPO, "data", "kline")
    adir = os.path.join(REPO, "data", "adjfactor")
    out = {k: {} for k in ("adjc", "adjo", "rawc", "amt", "lock")}
    for fn in sorted(os.listdir(kdir)):
        if not fn.endswith(".json"):
            continue
        sid = fn[:-5]
        apath = os.path.join(adir, fn)
        if not os.path.exists(apath):
            continue  # 沒有還原因子的不納入 (本次價格來源鎖定還原價)
        k = json.load(open(os.path.join(kdir, fn), encoding="utf-8")).get("records", {})
        a = json.load(open(apath, encoding="utf-8")).get("records", {})
        d = {key: {} for key in out}
        for date, bar in k.items():
            f = a.get(date)
            if f is None or not bar or bar[3] in (None, 0):
                continue
            o, h, l, c = bar[0], bar[1], bar[2], bar[3]
            v = bar[4] if len(bar) > 4 else None
            d["adjc"][date] = c * f
            d["adjo"][date] = o * f if o else None
            d["rawc"][date] = c
            d["amt"][date] = (v * c) if v else None
            d["lock"][date] = bool(h is not None and l is not None and h == l)
        if d["adjc"]:
            for key in out:
                out[key][sid] = d[key]
    return out


def build():
    t0 = time.time()
    chips = _read_chips()
    P = _read_px()
    px_sid = P["adjc"]
    smap = json.load(open(os.path.join(REPO, "data", "stock_map.json"), encoding="utf-8"))

    # 只留「有籌碼 + 有還原價」的股期
    code2sid = {c: smap[c]["sid"] for c in chips if c in smap and smap[c].get("sid")}
    codes = sorted(c for c, sid in code2sid.items() if sid in px_sid)

    # 淨部位原始欄位 -> DataFrame
    raw = {k: {} for k in ("a5", "a10", "s5", "s10", "moi")}
    for c in codes:
        for date, (a5, a10, s5, s10, moi) in chips[c].items():
            raw["a5"].setdefault(date, {})[c] = a5
            raw["a10"].setdefault(date, {})[c] = a10
            raw["s5"].setdefault(date, {})[c] = s5
            raw["s10"].setdefault(date, {})[c] = s10
            raw["moi"].setdefault(date, {})[c] = moi
    R = {k: pd.DataFrame.from_dict(v, orient="index").sort_index().reindex(columns=codes)
         for k, v in raw.items()}

    # 九種族群持有比率
    ratio, net = {}, {}
    for fam in FAMILIES:
        for sl in SLICES:
            n = _net(R["a5"], R["a10"], R["s5"], R["s10"], fam, sl)
            name = f"{fam}{sl}"
            net[name] = n
            ratio[name] = n / R["moi"]

    # 價格/金額欄位,對齊到同一組日期與代號
    dates = R["moi"].index

    def frame(key):
        src = P[key]
        return pd.DataFrame(
            {c: pd.Series(src[code2sid[c]]) for c in codes}
        ).sort_index().reindex(dates)

    px = frame("adjc")     # 還原收盤(算報酬)
    pxo = frame("adjo")    # 還原開盤(算報酬)
    rawc = frame("rawc")   # 原始收盤(算金額)
    amt = frame("amt")     # 現貨成交金額
    lock = frame("lock").fillna(False).astype(bool)

    # 每口股數: 商品名稱開頭「小型」= 100 股,其餘 2000 股
    shares_per_lot = {}
    for c in codes:
        nm = json.load(open(os.path.join(REPO, "data", "stocks", c + ".json"),
                            encoding="utf-8")).get("name", "")
        shares_per_lot[c] = 100 if nm.startswith("小型") else 2000
    spl = pd.Series(shares_per_lot)

    # 股期規模(元) 必須用「原始收盤」,還原價不是真實價格
    scale = R["moi"] * rawc * spl
    # 股期規模 / 現貨成交金額 (代表性比率)
    rep = scale / amt

    D = {
        "codes": codes,
        "code2sid": code2sid,
        "names": {c: smap[c].get("short", c) for c in codes},
        "shares_per_lot": spl,
        "raw": R,
        "net": net,
        "ratio": ratio,
        "px": px,        # 還原收盤
        "pxo": pxo,      # 還原開盤
        "rawc": rawc,    # 原始收盤
        "amt": amt,      # 現貨成交金額(元)
        "lock": lock,    # 一價到底
        "scale": scale,  # 股期規模(元)
        "rep": rep,      # 股期規模 / 現貨成交金額
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "build_sec": round(time.time() - t0, 1),
    }
    with open(CACHE, "wb") as f:
        pickle.dump(D, f, protocol=4)
    return D


def load(rebuild=False):
    if not rebuild and os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    return build()


if __name__ == "__main__":
    D = build()
    print(f"built in {D['build_sec']}s  codes={len(D['codes'])}")
    print(f"dates {D['px'].index[0]} ~ {D['px'].index[-1]}  n={len(D['px'])}")
    r = D["ratio"]["主力6-10"]
    print("ratio 主力6-10 非空比例:", round(r.notna().mean().mean() * 100, 1), "%")
    print("px 非空比例:", round(D["px"].notna().mean().mean() * 100, 1), "%")
