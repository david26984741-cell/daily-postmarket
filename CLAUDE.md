# daily-postmarket 專案指南(給 Claude 的說明檔)

台股期貨盤後籌碼網站。每交易日自動抓取期交所/證交所資料,發布於 GitHub Pages:
https://david26984741-cell.github.io/daily-postmarket/

使用者(老黑)在**公司**與**家裡**兩台電腦上分別與 Claude 協作,以此 GitHub 儲存庫為唯一同步管道。

## ⚠️ 跨電腦工作規則(最重要)

1. **開工前必先 Pull**:GitHub Desktop → Fetch origin → Pull origin(或 `git pull`)。
   兩台電腦的 Claude 對話記憶不互通,唯一的共同事實是這個儲存庫。
   不 pull 就看不到另一台電腦(以及每日自動更新機器人)的修改。
2. **收工後必 Commit + Push**。
3. **絕對不要 force push**:遠端隨時可能有 workflow 機器人的資料 commit。
   跳出 force push 確認視窗時一律 Cancel,改用 Pull(合併)後再 Push。
4. 交接紀錄請更新本檔末尾的「變更日誌」。

## 部署方式(常見誤區)

- **push 程式碼不會更新網站**。網站只在 workflow 執行時部署(每個 workflow 的
  deploy 步驟把檔案複製到 _site 再上傳 Pages)。
- 要立即部署前端修改:手動觸發 `回補日K股價`(kline.yml),起訖日期都填最近交易日
  (例 2026/07/09),約 1 分鐘跑完並部署。
- 新增 HTML 頁面時,必須把檔名加進**四個** workflow 的「準備網站檔案」cp 清單
  (daily.yml / backfill.yml / kline.yml / analysis.yml),否則不會被部署。

## Workflows(.github/workflows/)

| 檔案 | 用途 | 排程/觸發 | concurrency group |
|---|---|---|---|
| daily.yml | 每日抓取+部署 | 台北 15:35 主班次、21:35 備援(週一~五);可手動指定日期 | daily-postmarket |
| backfill.yml | 回補歷史部位資料 | 手動(起訖日期) | daily-postmarket |
| kline.yml | 回補現貨日K | 手動(起訖日期) | daily-postmarket-kline |
| analysis.yml | 籌碼研究分析 | 週日 02:00 UTC + 手動 | daily-postmarket-analysis |

重要細節:
- Runner 跑在 UTC 且**無視 TZ 環境變數**,所有時間邏輯用 scrape.py 的 `now_taipei()`(utcnow+8h)。
- 所有 checkout 都設 `ref: main`(取開跑當下最新版)。原因:GitHub 在「觸發那一刻」凍結
  checkout 版本,若在佇列等待期間 main 前進,rebase 會大量衝突導致整批資料丟失(#16 事故)。
- Commit 步驟有 pkill + 重試迴圈:逾時取消後 python 可能仍在寫檔,必須先強制終結。
- GitHub cron 是盡力而為,常延遲甚至跳過(2026/07/09 發生過),所以有 21:35 備援班次。

## 資料口徑(全站統一,與 XQ 一致)

期交所大額交易人原始值:t0 = 前十大交易人合計淨部位、t1 = 前十大特定法人淨部位。
- **法人 = t1**
- **自然人 = t0 − t1**
- **主力 = 自然人 − 法人 = t0 − 2×t1** ← 注意:不是 t0!
- 金額 = 口數 × 現股收盤價 × 每口股數(小型契約 100 股、一般 2,000 股)
- rank.json 存原始值(main=t0, inst=t1),由前端(rank.html/concept.html)換算顯示。
- stocks.html 的 series() 與 tools/analyze.py 已用同口徑。

## 檔案地圖

- `scrape.py` — 每日抓取核心。cp950 解碼(「碁」等罕字)、BROWSER_UA(證交所 WAF 擋機器人)、
  cat6 股期自動發現(2字代號、排除 TX/TE/TF)、臨時休市保護(颱風假不寫入不重建 index)、
  午夜守衛(台北 <14 時抓前一交易日)、_rank_row 產 data/rank.json(含 price/price_prev)。
- `tools/backfill.py` — 回補部位(逐日呼叫 scrape.run,skip_kline=True)。
- `tools/backfill_kline.py` — 回補日K(每 40 個交易日 flush 一次,防逾時丟失)。
- `tools/analyze.py` — 研究管線(IC/五分位/walk-forward LightGBM/規則回測)→ data/analysis.json。
- 頁面:`index.html`(總覽)、`stocks.html`(個股圖表:K棒+主力/自然人/法人面板、滾輪縮放、
  拖曳平移、雙擊查價十字線、金額開關、偏好記憶)、`rank.html`(增減排行+概念股框框)、
  `concept.html`(同概念股總覽,可排序)、`detail.html`、`help.html`(名詞解釋)、`analysis.html`。
- `assets/style.css`(html zoom:1.25 全站放大 — Chart.js 內建 tooltip 因此座標會偏移,已停用,
  一律用自製查價視窗)、`assets/app.js`(CATS 導覽/共用工具)。
- `data/`:stocks/(部位,2017/07/10 起)、kline/(日K,2017 起)、rank.json、concepts.json
  (概念股對照,整理自財報狗產業地圖,格式 {sid:{m:主標籤,t:[產業·子產業,...]}})、
  index.json、analysis.json、stock_map.json、holidays.txt(2026 含颱風假)。

## 已知注意事項

- stocks.html 各面板軸寬鎖定 AXW=64(afterFit + layout padding),確保十字線跨面板筆直對齊,
  改圖表時不要破壞這個。
- K棒 Y 軸貼合可視價格區間(kYRange),籌碼面板 Y 軸含 0 基準線 — 兩者設計不同是刻意的。
- 概念股 concepts.json 是一次性整理(2026/07/12),新股期上市不會自動有標籤(不顯示框框,
  不會顯示錯誤),需要時重掃財報狗補上。
- TAIFEX 資料保留:大額交易人約 2017 年中起;選擇權/外資期貨僅約 3 年;證交所現貨僅近期。
- 部位與日K資料已完整回補至 2017/07/10~今(2026/07/13 完成)。

## 變更日誌

### 2026/07/11~13(家用電腦)
- 修 7/9 未更新(cron 跳過)→ 手動補跑 + 新增 21:35 備援班次
- 新股期自動發現(旺矽/小型旺矽/小型亞翔);颱風假/臨時休市保護
- 歷史回補:部位+日K 補到 2017/07/10(#16 rebase 衝突丟資料事故 → workflow checkout 改 ref:main 後重跑成功)
- stocks.html:滾輪縮放、拖曳平移、期間快選、K棒(現貨日K)面板、共同日期軸逐日對齊、
  雙擊查價十字線(自動換邊、滑鼠穿透)、移除內建 tooltip(zoom 座標偏移)、軸刻度加大加亮、
  K棒Y軸貼合價格區間、籌碼軸對調(淨部位左/增減右)、金額+增減金額顯示(可開關)、偏好記憶
- rank.html:增減口數/金額四榜、口徑修正(主力=自然人−法人,與個股頁/XQ一致)、
  概念股分類框框(可點擊)
- concept.html(新):同概念股總覽,七欄可排序
- help.html:名詞解釋(口徑定義更正)
- analyze.py:主力口徑改與網站一致;正式版分析已跑(9年資料):主力增減 IC 顯著(t 3~4.7),
  R1 主力大幅增倉 T+5 超額 +29bp / T+20 +85bp(2024 後更強)
- 修 rank.json 舊亂碼名稱(宏碁/啟碁)

(之後的修改請接著往下記)
