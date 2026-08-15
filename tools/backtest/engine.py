"""
籌碼回測引擎 (向量化)

規格見 handoffs 討論定案版:
  池子    每日剔除股期規模最小 40% (規模用「原始收盤價」計),無上限
  去重    同一 sid 只留一個契約,取「當日距池子中位數最遠」者(對稱,不偏袒高低端)
  分組    五分位(主表) / 三分位(雙重分組章節) / 固定 N(附表)
  進場    訊號日 T 盤後公布 -> T+1 進場
            close 版: T+1 收 -> T+1+H 收
            open  版: T+1 開 -> T+1+H 收   (出場點相同,唯一變數是進場時點)
  重疊    每日建倉,每天換 1/H 部位
  不可成交 T+1 一價到底(高=低) 不進場;T+1 無報價不進場不遞補
  停牌/下市 持有中以最後可得價格接續 (ffill)
  超額    減去同結構的「全池等權」基準
  t 值    Newey-West 調整 (lag=H),因重疊建倉會讓一般 t 值虛胖
"""

import numpy as np
import pandas as pd

TRADING_DAYS = 244


# ---------------------------------------------------------------- 前置

def prep(D, min_scale_pct=0.40, band=None):
    """
    回傳回測所需的對齊矩陣。
    band=(lo_億, hi_億) 時改用固定金額帶(舊池穩健性對照);hi 可為 None 表示無上限。
    """
    px, pxo, sc = D["px"], D["pxo"], D["scale"]
    ok = px.notna() & sc.notna() & (sc > 0)

    if band is None:
        pct = sc.where(ok).rank(axis=1, pct=True)
        elig = ok & (pct > min_scale_pct)
    else:
        lo, hi = band
        elig = ok & (sc >= lo * 1e8)
        if hi is not None:
            elig &= sc <= hi * 1e8

    pxf = px.ffill()                       # 出場用:停牌/下市以最後價接續
    rcc = pxf / pxf.shift(1) - 1           # 收盤到收盤日報酬
    rintra = px / pxo - 1                  # 當日開盤到收盤(開盤版進場首日)

    # T+1 可成交:有開/收報價,且非一價到底
    tradable = px.notna() & D["lock"].eq(False)
    tradable_open = tradable & pxo.notna() & (pxo > 0)

    return {
        "elig": elig,
        "rcc": rcc.replace([np.inf, -np.inf], np.nan),
        "rintra": rintra.replace([np.inf, -np.inf], np.nan),
        "tradable": tradable,
        "tradable_open": tradable_open,
        "dates": px.index,
        "codes": px.columns,
        "_px": px,
        "_pxo": pxo,
        "_pxf": pxf,
    }


def dup_pairs(D):
    """同一 sid 的契約組(僅處理成對,實務上沒有三個以上)"""
    from collections import defaultdict
    g = defaultdict(list)
    for c, s in D["code2sid"].items():
        if c in D["px"].columns:
            g[s].append(c)
    return [v for v in g.values() if len(v) > 1]


def dedup(ratio, elig, pairs, D, rule="extreme"):
    """
    同一 sid 只留一個契約。
    rule='extreme' 取當日「距池子橫斷面中位數最遠」者 -> 高低端對稱
    rule='scale'   取當日股期規模較大者
    回傳新的 elig(已把落選契約設 False)
    """
    e = elig.copy()
    r = ratio.where(elig)

    if rule == "extreme":
        med = r.median(axis=1)
        key = r.sub(med, axis=0).abs()
    elif rule == "scale":
        key = D["scale"].where(elig)
    else:
        raise ValueError(rule)

    for grp in pairs:
        grp = [c for c in grp if c in e.columns]
        if len(grp) < 2:
            continue
        sub = key[grp]
        # 兩邊都有效時才需要取捨;並列時取欄名較前者以確保可重現
        valid = sub.notna()
        n_valid = valid.sum(axis=1)
        need = n_valid > 1
        if not need.any():
            continue
        sub2 = sub[need]
        if sub2.empty:
            continue
        win = sub2.idxmax(axis=1)
        for c in grp:
            drop = win.index[win != c]
            e.loc[drop, c] = False
    return e


# ---------------------------------------------------------------- 分組

def quantile_groups(ratio, elig, nq):
    """
    依比率由高到低切 nq 等份。回傳 list of boolean DataFrame,index 0 = 比率最高組。
    """
    r = ratio.where(elig)
    rk = r.rank(axis=1, pct=True, ascending=False)
    out = []
    for i in range(nq):
        lo, hi = i / nq, (i + 1) / nq
        m = (rk > lo) & (rk <= hi) if i > 0 else (rk > 0) & (rk <= hi)
        out.append(m.fillna(False))
    return out


def topn_groups(ratio, elig, n):
    """固定 N:回傳 (最高 N 檔, 最低 N 檔)"""
    r = ratio.where(elig)
    hi = r.rank(axis=1, ascending=False, method="first")
    lo = r.rank(axis=1, ascending=True, method="first")
    return (hi <= n).fillna(False), (lo <= n).fillna(False)


# ---------------------------------------------------------------- 報酬

def _weights(sel, P, mode):
    """
    選股布林矩陣 -> 每列權重。
    分母用「選出的檔數」而非「可成交檔數」,買不到的那格留現金不遞補(規格要求)。
    """
    trad = P["tradable_open"] if mode == "open" else P["tradable"]
    n = sel.sum(axis=1)                                  # 原始選出檔數
    ok = sel & trad.shift(-1).fillna(False).astype(bool)  # 訊號在 t,看 t+1 能否成交
    w = ok.div(n.replace(0, np.nan), axis=0)
    return w.fillna(0.0), n


def daily_series(sel, P, H, mode):
    """
    每日重疊建倉的策略日報酬序列。
    close 版:第 d 日活躍的 cohort 為 t in [d-1-H, d-2] 共 H 個
    open  版:多一個 cohort(t=d-1)貢獻當日開->收
    分母用「當日實際活躍的 cohort 數」,樣本頭尾與空手日才不會被灌大。
    """
    w, n = _weights(sel, P, mode)
    rcc = P["rcc"].fillna(0.0)
    rintra = P["rintra"].fillna(0.0)
    live = (n > 0).astype(float)          # 該訊號日有沒有建倉

    # sum_{k=2}^{H+1} w[d-k]  ==  長度 H、結束於 d-2 的滾動和 (比逐一 shift 快得多)
    pos = w.shift(2).rolling(H, min_periods=1).sum().fillna(0.0)
    act = live.shift(2).rolling(H, min_periods=1).sum().fillna(0.0)
    cc = (pos * rcc).sum(axis=1)

    if mode == "open":
        pos_i = w.shift(1).fillna(0.0)
        act_i = live.shift(1).fillna(0.0)
        num = cc + (pos_i * rintra).sum(axis=1)
        den = act + act_i
    else:
        num, den = cc, act

    # den==0 表示當日沒有任何活躍 cohort(樣本頭尾/空手期) -> 留 NaN,
    # 不可填 0,否則這些空手日會被算進年化與 Sharpe 的分母,稀釋掉所有統計量。
    ret = num / den.replace(0, np.nan)
    return ret, n


def cohort_returns(sel, P, H, mode):
    """
    每一批(cohort)的整筆報酬 —— 進出場點固定,可直接跨進場方式比較。
    close: px[t+1+H]/px[t+1]-1     open: px[t+1+H]/pxo[t+1]-1
    """
    px = P["_px"]
    pxf = P["_pxf"]
    ent = (P["_pxo"] if mode == "open" else px).shift(-1)
    ext = pxf.shift(-(1 + H))
    fwd = ext / ent - 1
    w, n = _weights(sel, P, mode)
    r = (w * fwd.replace([np.inf, -np.inf], np.nan).fillna(0.0)).sum(axis=1)
    return r.where(n > 0)


# ---------------------------------------------------------------- 統計

def newey_west_t(x, lag):
    """Newey-West 調整後的 t 值(檢定均值是否為 0)"""
    x = np.asarray(pd.Series(x).dropna(), dtype=float)
    n = len(x)
    if n < 30:
        return np.nan
    mu = x.mean()
    e = x - mu
    g0 = (e @ e) / n
    s = g0
    for l in range(1, min(lag, n - 1) + 1):
        gl = (e[l:] @ e[:-l]) / n
        s += 2 * (1 - l / (lag + 1)) * gl
    if s <= 0:
        return np.nan
    return mu / np.sqrt(s / n)


def stats(r, lag):
    """由日報酬序列算出報告需要的統計量"""
    r = pd.Series(r).dropna()
    if len(r) < 30:
        return {k: np.nan for k in
                ("ann", "cum", "vol", "sharpe", "t", "win", "mdd", "days")}
    cum = (1 + r).cumprod()
    yrs = len(r) / TRADING_DAYS
    ann = cum.iloc[-1] ** (1 / yrs) - 1 if cum.iloc[-1] > 0 else np.nan
    vol = r.std() * np.sqrt(TRADING_DAYS)
    dd = cum / cum.cummax() - 1
    return {
        "ann": float(ann) * 100 if ann == ann else np.nan,
        "cum": float(cum.iloc[-1] - 1) * 100,
        "vol": float(vol) * 100,
        "sharpe": float(ann / vol) if vol and vol == vol and ann == ann else np.nan,
        "t": float(newey_west_t(r, lag)),
        "win": float((r > 0).mean()) * 100,
        "mdd": float(dd.min()) * 100,
        "days": int(len(r)),
    }


# ---------------------------------------------------------------- 主流程

def rolling_hold(sel, P, H, mode):
    """
    滾動續抱(附表用):入榜隔日進場,持有 H 日;期間再入榜則把出場日往後推,不重複買進;
    連續 H 日未入榜則於第 H 日收盤賣出。等權,每日再平衡。
    held[d] = 過去 H 個訊號日內曾入榜。
    """
    s = sel.astype(float)
    base_hold = s.rolling(H, min_periods=1).max()
    held = (base_hold.shift(1) if mode == "open" else base_hold.shift(2)).fillna(0.0)

    trad = (P["tradable_open"] if mode == "open" else P["tradable"])
    held = held * trad.astype(float)

    rcc = P["rcc"].fillna(0.0)
    n = held.sum(axis=1)
    w = held.div(n.replace(0, np.nan), axis=0).fillna(0.0)

    if mode == "open":
        new = ((held > 0) & (held.shift(1).fillna(0.0) == 0)).astype(float)
        rr = P["rcc"].fillna(0.0) * (1 - new) + P["rintra"].fillna(0.0) * new
    else:
        rr = rcc

    ret = (w * rr).sum(axis=1).where(n > 0)
    return ret, n


def setup(D, factor, P, cond=None, dedup_rule="extreme"):
    """
    同一因子的池子與去重只跟 (factor, pool, cond) 有關,與 H/mode 無關。
    先算一次再餵給多個 run(),可省下大量重複計算。
    """
    ratio = D["ratio"][factor] if isinstance(factor, str) else factor
    elig = P["elig"] & ratio.notna()
    if cond is not None:
        elig = elig & cond
    elig = dedup(ratio, elig, dup_pairs(D), D, dedup_rule)
    return ratio, elig


def run(D, factor, H, mode, nq=5, min_scale_pct=0.40, band=None,
        dedup_rule="extreme", cond=None, P=None, pre=None):
    """
    跑單一設定,回傳 dict:
      groups  各分位的日報酬序列與統計(原始與超額)
      bench   全池等權基準
      spread  最高分位 - 最低分位
    cond: 可選的額外條件遮罩(雙重分組用),布林 DataFrame
    """
    if P is None:
        P = prep(D, min_scale_pct, band)

    if pre is not None:
        ratio, elig = pre
    else:
        ratio, elig = setup(D, factor, P, cond, dedup_rule)

    bench_r, _ = daily_series(elig, P, H, mode)

    gs = quantile_groups(ratio, elig, nq)
    out = {"bench": stats(bench_r, H), "bench_series": bench_r,
           "groups": [], "series": [], "nq": nq,
           "n_avg": float(elig.sum(axis=1).replace(0, np.nan).mean())}
    for g in gs:
        r, _ = daily_series(g, P, H, mode)
        ex = r - bench_r
        out["groups"].append({"raw": stats(r, H), "excess": stats(ex, H)})
        out["series"].append(r)

    sp = out["series"][0] - out["series"][-1]
    out["spread"] = stats(sp, H)
    out["spread_series"] = sp
    return out
