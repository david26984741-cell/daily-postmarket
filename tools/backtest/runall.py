"""
跑全部回測設定,結果存 /tmp/results.pkl (分段執行,避免單次逾時)

用法: python3 runall.py <section>
  pool     池子特性表
  main     五分位主表        9因子 × 5H × 2進場
  topn     固定N=10附表      9因子 × 5H × 2進場 (滾動續抱)
  cond     期貨代表性雙重分組 9因子 × 5H × 2進場 × 高/低 (三分位)
  rep      代表性比率單獨當因子 5H × 2進場 (五分位)
  oldpool  舊池2.5~100億穩健性 9因子 × 5H × 2進場 (固定N=10)
"""

import os
import pickle
import sys
import time
import warnings

warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

import base
import engine as E

RES = "/tmp/results.pkl"
FACTORS = [f"{fam}{sl}" for fam in ("特定法人", "自然人", "主力")
           for sl in ("前五", "前十", "6-10")]
HS = [1, 3, 5, 10, 20]
MODES = ["close", "open"]
HALF = "2022/01/18"


def load_res():
    return pickle.load(open(RES, "rb")) if os.path.exists(RES) else {}


def save_res(r):
    pickle.dump(r, open(RES, "wb"), protocol=4)


def yearly(series, H):
    """
    逐年一律回報【累積】報酬,不年化。
    2017 只有 120 個交易日、2026 只有 148 個,年化會把它們外推成誤導性的數字
    (實測 2026 全池基準 累積 +71% 會被年化成 +141%)。
    """
    s = series.dropna()
    out = {}
    for y, g in s.groupby([i[:4] for i in s.index]):
        if len(g) < 20:
            continue
        out[y] = {"cum": float((1 + g).prod() - 1) * 100, "days": len(g)}
    return out


def halves(series, H):
    s = series.dropna()
    a, b = s[s.index < HALF], s[s.index >= HALF]
    return {"前半": E.stats(a, H), "後半": E.stats(b, H)}


def pack(r, H):
    """把 run() 的輸出壓成報告需要的摘要(不存整條序列以節省空間)"""
    return {
        "n_avg": r["n_avg"],
        "bench": r["bench"],
        "groups": r["groups"],
        "spread": r["spread"],
        "spread_yearly": yearly(r["spread_series"], H),
        "spread_halves": halves(r["spread_series"], H),
        "bench_yearly": yearly(r["bench_series"], H),
        # Q1/Q5 逐年累積,以及各自相對全池基準的超額 —— 回答「因子有沒有效」
        "q1_yearly": yearly(r["series"][0], H),
        "q5_yearly": yearly(r["series"][-1], H),
        "q1_ex_yearly": yearly(r["series"][0] - r["bench_series"], H),
        "q5_ex_yearly": yearly(r["series"][-1] - r["bench_series"], H),
        "q_ann": [g["raw"]["ann"] for g in r["groups"]],
        "q_ex": [g["excess"]["ann"] for g in r["groups"]],
    }


def main():
    sec = sys.argv[1]
    D = base.load()
    P = E.prep(D)
    res = load_res()
    t0 = time.time()

    if sec == "pool":
        elig = P["elig"]
        sc = D["scale"].where(elig)
        rows = {}
        for y, idx in pd.Series(elig.index, index=elig.index).groupby(
                [i[:4] for i in elig.index]):
            e = elig.loc[idx]
            if e.sum(axis=1).max() == 0:
                continue
            s = sc.loc[idx]
            full = D["scale"].where(P["elig"].notna() & D["px"].notna()).loc[idx]
            rows[y] = {
                "池子檔數": float(e.sum(axis=1).replace(0, np.nan).mean()),
                "切線億元": float((D["scale"].where(D["px"].notna()).loc[idx]
                                 .quantile(0.40, axis=1) / 1e8).mean()),
                "池內平均規模億": float((s.mean(axis=1) / 1e8).mean()),
                "池內中位規模億": float((s.median(axis=1) / 1e8).mean()),
            }
        res["pool"] = rows
        print(pd.DataFrame(rows).T.round(1).to_string())

    elif sec == "main":
        out = {}
        for f in FACTORS:
            pre = E.setup(D, f, P)
            for H in HS:
                for m in MODES:
                    out[(f, H, m)] = pack(E.run(D, f, H, m, nq=5, P=P, pre=pre), H)
            print("  %s done  %.0fs" % (f, time.time() - t0))
        res["main"] = out

    elif sec == "topn":
        out = {}
        for f in FACTORS:
            ratio, elig = E.setup(D, f, P)
            hi, lo = E.topn_groups(ratio, elig, 10)
            for H in HS:
                for m in MODES:
                    rh, nh = E.rolling_hold(hi, P, H, m)
                    rl, _ = E.rolling_hold(lo, P, H, m)
                    bench, _ = E.daily_series(elig, P, H, m)
                    sp = rh - rl
                    out[(f, H, m)] = {
                        "high": E.stats(rh, H), "low": E.stats(rl, H),
                        "spread": E.stats(sp, H), "bench": E.stats(bench, H),
                        "high_ex": E.stats(rh - bench, H),
                        "low_ex": E.stats(rl - bench, H),
                        "spread_yearly": yearly(sp, H),
                        "spread_halves": halves(sp, H),
                        "hold_avg": float(nh.replace(0, np.nan).mean()),
                    }
            print("  %s done  %.0fs" % (f, time.time() - t0))
        res["topn"] = out

    elif sec == "cond":
        rep_rank = D["rep"].where(P["elig"]).rank(axis=1, pct=True)
        conds = {"高": rep_rank > 0.5, "低": rep_rank <= 0.5}
        out = res.get("cond", {})          # 分段執行,累加
        lo = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        hi = int(sys.argv[3]) if len(sys.argv) > 3 else len(FACTORS)
        for f in FACTORS[lo:hi]:
            for cn, cm in conds.items():
                pre = E.setup(D, f, P, cond=cm)
                for H in HS:
                    for m in MODES:
                        out[(f, cn, H, m)] = pack(
                            E.run(D, f, H, m, nq=3, P=P, pre=pre), H)
            print("  %s done  %.0fs" % (f, time.time() - t0))
        res["cond"] = out

    elif sec == "entry":
        # 進場時點比較:同一批訊號、同一出場點,只換進場價 -> 唯一乾淨的比法
        out = {}
        for f in FACTORS:
            ratio, elig = E.setup(D, f, P)
            gs = E.quantile_groups(ratio, elig, 5)
            for H in HS:
                rec = {}
                for m in MODES:
                    q1 = E.cohort_returns(gs[0], P, H, m)
                    q5 = E.cohort_returns(gs[-1], P, H, m)
                    rec[m] = {"q1": q1, "q5": q5, "sp": q1 - q5}
                ok = rec["close"]["sp"].notna() & rec["open"]["sp"].notna()
                out[(f, H)] = {
                    "close_q1": float(rec["close"]["q1"][ok].mean()) * 100,
                    "open_q1": float(rec["open"]["q1"][ok].mean()) * 100,
                    "close_sp": float(rec["close"]["sp"][ok].mean()) * 100,
                    "open_sp": float(rec["open"]["sp"][ok].mean()) * 100,
                    "n": int(ok.sum()),
                }
                out[(f, H)]["diff_sp"] = out[(f, H)]["open_sp"] - out[(f, H)]["close_sp"]
            print("  %s done  %.0fs" % (f, time.time() - t0))
        res["entry"] = out

    elif sec == "rep":
        out = {}
        pre = E.setup(D, D["rep"], P)
        for H in HS:
            for m in MODES:
                out[(H, m)] = pack(E.run(D, D["rep"], H, m, nq=5, P=P, pre=pre), H)
        res["rep"] = out
        print("  done %.0fs" % (time.time() - t0))

    elif sec == "oldpool":
        P2 = E.prep(D, band=(2.5, 100))
        out = {}
        for f in FACTORS:
            ratio, elig = E.setup(D, f, P2)
            hi, lo = E.topn_groups(ratio, elig, 10)
            for H in HS:
                for m in MODES:
                    rh, _ = E.rolling_hold(hi, P2, H, m)
                    rl, _ = E.rolling_hold(lo, P2, H, m)
                    bench, _ = E.daily_series(elig, P2, H, m)
                    out[(f, H, m)] = {
                        "high": E.stats(rh, H), "low": E.stats(rl, H),
                        "spread": E.stats(rh - rl, H), "bench": E.stats(bench, H),
                    }
            print("  %s done  %.0fs" % (f, time.time() - t0))
        res["oldpool"] = out
        res["oldpool_n"] = float(P2["elig"].sum(axis=1).replace(0, np.nan).mean())

    else:
        raise SystemExit("unknown section: " + sec)

    save_res(res)
    print("[%s] 完成 %.0fs  已存 %s" % (sec, time.time() - t0, RES))


if __name__ == "__main__":
    main()
