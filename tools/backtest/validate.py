"""
引擎正確性驗證 —— 在相信任何回測數字之前必須全部通過。

1. 安慰劑:用隨機訊號,價差年化應 ~0、|t| 應 <2
2. 神諭  :用「未來報酬」當訊號,價差應暴衝(證明引擎抓得到訊號)
3. 前視  :把訊號多延一日(T-1 的資料),結果應變弱但不應崩壞
4. 手算  :單一日期單一分位,人工重算報酬並與引擎比對
5. t 值  :H=1 時 Newey-West t 應接近一般 t
6. 基準  :全池等權應與大盤同數量級
"""

import warnings
import numpy as np
import pandas as pd

warnings.simplefilter("ignore")

import base
import engine as E

D = base.load()
P = E.prep(D)
FACTOR, H, MODE = "主力6-10", 5, "close"

print("=" * 68)
print("引擎驗證")
print("=" * 68)

# --- 基準線 ---
ref = E.run(D, FACTOR, H, MODE, P=P)
print("\n[基準] %s H=%d %s" % (FACTOR, H, MODE))
print("  Q1 %.2f%%  Q5 %.2f%%  價差 %.2f%%  t=%.2f"
      % (ref["groups"][0]["raw"]["ann"], ref["groups"][-1]["raw"]["ann"],
         ref["spread"]["ann"], ref["spread"]["t"]))

# --- 1. 安慰劑 ---
print("\n[1] 安慰劑:隨機訊號 (跑 %d 次,檢查 t 的分布是否符合標準常態)" % 40)
rng = np.random.default_rng(0)
real = D["ratio"][FACTOR]
anns, ts = [], []
for i in range(40):
    fake = pd.DataFrame(rng.standard_normal(real.shape),
                        index=real.index, columns=real.columns).where(real.notna())
    r = E.run(D, fake, H, MODE, P=P)
    anns.append(r["spread"]["ann"]); ts.append(r["spread"]["t"])
ts = np.array(ts); anns = np.array(anns)
print("    價差年化: 平均 %+.2f%%  標準差 %.2f%%" % (anns.mean(), anns.std()))
print("    t 值    : 平均 %+.2f   標準差 %.2f   (理論應為 0 與 1.00)"
      % (ts.mean(), ts.std()))
print("    |t|>2 的比例 %.1f%%  (理論 4.6%%)   最大|t| %.2f"
      % ((np.abs(ts) > 2).mean() * 100, np.abs(ts).max()))
ok1 = abs(anns.mean()) < 2 and 0.7 < ts.std() < 1.4 and abs(ts.mean()) < 0.5
print("    ->  %s" % ("通過" if ok1 else "**失敗:t 值有系統性偏誤**"))

# --- 2. 神諭 ---
print("\n[2] 神諭:用未來 H 日報酬當訊號(應暴衝)")
px = D["px"].ffill()
oracle = (px.shift(-(1 + H)) / px.shift(-1) - 1).where(real.notna())
ro = E.run(D, oracle, H, MODE, P=P)
ok2 = ro["spread"]["ann"] > 100
print("    價差年化 %.1f%%   t=%.1f  ->  %s"
      % (ro["spread"]["ann"], ro["spread"]["t"], "通過" if ok2 else "**失敗**"))

# --- 3. 訊號延遲 ---
print("\n[3] 訊號多延一日(用 T-1 的籌碼)")
lag1 = real.shift(1)
rl = E.run(D, lag1, H, MODE, P=P)
print("    價差年化 %.2f%%  t=%.2f   (原始 %.2f%% / t=%.2f)"
      % (rl["spread"]["ann"], rl["spread"]["t"], ref["spread"]["ann"], ref["spread"]["t"]))
ok3 = rl["spread"]["ann"] < ref["spread"]["ann"] * 1.3
print("    延遲後未增強  ->  %s" % ("通過" if ok3 else "**失敗:延遲反而更好,可疑**"))

# --- 4. 手算比對 ---
print("\n[4] 手算比對:單一 cohort 的整筆報酬")
elig = P["elig"] & real.notna()
elig = E.dedup(real, elig, E.dup_pairs(D), D, "extreme")
gs = E.quantile_groups(real, elig, 5)
q1 = gs[0]
dates = list(D["px"].index)
i = dates.index("2024/03/15")
t = dates[i]
sel = [c for c in q1.columns if q1.loc[t, c]]
pxf = D["px"].ffill()
ent_d, ext_d = dates[i + 1], dates[i + 1 + H]
man = []
for c in sel:
    e0, e1 = D["px"].loc[ent_d, c], pxf.loc[ext_d, c]
    if pd.notna(e0) and pd.notna(e1) and not D["lock"].loc[ent_d, c]:
        man.append(e1 / e0 - 1)
    else:
        man.append(0.0)
manual = float(np.sum(man) / len(sel))
eng = float(E.cohort_returns(q1, P, H, MODE).loc[t])
print("    日期 %s  選出 %d 檔  進場 %s  出場 %s" % (t, len(sel), ent_d, ext_d))
print("    手算 %.6f   引擎 %.6f   差 %.2e" % (manual, eng, abs(manual - eng)))
ok4 = abs(manual - eng) < 1e-9
print("    ->  %s" % ("通過" if ok4 else "**失敗**"))

# --- 5. NW t vs 一般 t ---
print("\n[5] H=1 時 Newey-West t 應接近一般 t")
r1 = E.run(D, FACTOR, 1, MODE, P=P)
s = r1["spread_series"].dropna()
plain = s.mean() / (s.std() / np.sqrt(len(s)))
nw = E.newey_west_t(s, 1)
ok5 = abs(plain - nw) / abs(plain) < 0.30
print("    一般 t=%.2f   NW t=%.2f   差異 %.1f%%  ->  %s"
      % (plain, nw, abs(plain - nw) / abs(plain) * 100, "通過" if ok5 else "**失敗**"))

print("\n[5b] H 越大,NW 修正應越明顯(證明重疊確實造成自我相關)")
for h in (1, 5, 20):
    rr = E.run(D, FACTOR, h, MODE, P=P)["spread_series"].dropna()
    p = rr.mean() / (rr.std() / np.sqrt(len(rr)))
    n = E.newey_west_t(rr, h)
    print("    H=%-2d  一般 t=%5.2f   NW t=%5.2f   虛胖 %4.0f%%" % (h, p, n, (p / n - 1) * 100))

# --- 6. 基準合理性 ---
print("\n[6] 全池等權基準 vs 台指期")
import json, os
txf = json.load(open(os.path.join(base.REPO, "data", "txf.json"), encoding="utf-8"))
rec = txf.get("records", txf)
tx = pd.Series({k: (v[3] if isinstance(v, list) else v) for k, v in rec.items()}).sort_index()
bs = ref["bench_series"].dropna()
common = [d for d in bs.index if d in tx.index]
tx = tx.reindex(common).astype(float).dropna()
yrs = len(tx) / 244
tx_ann = (tx.iloc[-1] / tx.iloc[0]) ** (1 / yrs) - 1
print("    有效回測期間 %s ~ %s (%d 日)" % (bs.index[0], bs.index[-1], len(bs)))
print("    全池等權年化 %.2f%%   台指期年化 %.2f%%   (同期間 %.1f 年)"
      % (ref["bench"]["ann"], tx_ann * 100, yrs))
ok6 = 0 < ref["bench"]["ann"] < 40
print("    ->  %s" % ("通過(數量級合理)" if ok6 else "**失敗**"))

print("\n" + "=" * 68)
allok = all([ok1, ok2, ok3, ok4, ok5, ok6])
print("總結: %s" % ("全部通過,引擎可信" if allok else "**有項目未通過,不可採用結果**"))
print("=" * 68)
