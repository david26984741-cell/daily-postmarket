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
- 新增 HTML 頁面時,必須把檔名加進**六個** workflow 的「準備網站檔案」cp 清單
  (daily.yml / backfill.yml / kline.yml / analysis.yml / txf.yml / fkline.yml),否則不會被部署。

## Workflows(.github/workflows/)

| 檔案 | 用途 | 排程/觸發 | concurrency group |
|---|---|---|---|
| daily.yml | 每日抓取+部署 | 台北 15:35 主班次、21:35 備援(週一~五);可手動指定日期 | daily-postmarket |
| backfill.yml | 回補歷史部位資料 | 手動(起訖日期) | daily-postmarket |
| kline.yml | 回補現貨日K | 手動(起訖日期) | daily-postmarket-kline |
| analysis.yml | 籌碼研究分析 | 週日 02:00 UTC + 手動 | daily-postmarket-analysis |
| txf.yml | 回補台指期近月 | 手動(起訖日期) | daily-postmarket-txf |
| fkline.yml | 回補股期近月日K | 手動(起訖日期,量大建議分段) | daily-postmarket-fkline |

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
  `concept.html`(同概念股總覽,可排序)、`screener.html`(股期篩選器)、`detail.html`、
  `help.html`(名詞解釋)、`analysis.html`。
- `assets/style.css`(html zoom:1.25 全站放大 — Chart.js 內建 tooltip 因此座標會偏移,已停用,
  一律用自製查價視窗)、`assets/app.js`(CATS 導覽/共用工具)。
- `data/`:stocks/(部位,2017/07/10 起)、kline/(現股日K,2017 起)、fkline/(股期近月日K,
  期交所行情,前端優先使用)、txf.json(台指期近月)、rank.json、concepts.json
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

### 2026/07/16(家用電腦)
- 新增 CLAUDE.md 專案指南與雙電腦同步規則
- 新增台指期近月資料源:scrape.py fetch_txf_range → data/txf.json、
  tools/backfill_txf.py(逐月回補,約3年)、workflow txf.yml
  口徑=一般時段「成交量最大」月契約的「結算價」(與XQ期貨近月日線一致;結算日自動換月)
- 外資/自營選擇權:「差額金額(千元)」改名「未平倉金額(千元)」(當日卡片+歷史表格)
- 外資/自營選擇權歷史趨勢圖疊加台指期收盤線(黃線,右軸貼合價格區間)
- 歷史趨勢圖(detail.html)新增:滾輪縮放、左鍵拖曳平移、雙擊重置、軸刻度加大加亮
- 外資期貨「多空淨額」與大額期貨「未平倉淨部位」改文字顯示:淨多單/淨空單 X 口(紅多綠空);
  較前一日改「多單增加/空單增加 X 口」;大額期貨新增較前一日欄
- 大額交易人選擇權移除「傾向」欄
- 新增指數層級研究 tools/analyze_index.py → data/analysis_index.json(各分頁資料對台指期
  前瞻報酬的預測力,約3年樣本),analysis.html 新增第⑥節,analysis.yml 一併執行

### 2026/07/17~18(公司+家用電腦)
- (公司)stocks.html:前五/前十大切換(rk5/rk10)、NET(rows,t,rk) 口徑含排名、
  gAmt 標籤改「持有規模」、效能優化(rAF/IntersectionObserver)
- (家用)股期近月日K資料源:scrape.py fetch_fkline_day(每日 Daily zip)/fetch_fkline_range
  (futDataDown 逐檔逐月)→ data/fkline/{code}.json、tools/backfill_fkline.py、workflow fkline.yml。
  stocks.html K棒優先用股期報價(標籤顯示「股期」),缺漏退回現股(顯示「股價」)
- stocks.html:面板順序改 交易人/主力/自然人/法人;籌碼面板「金額/增減金額」改
  「持有規模/增減規模」;標題列新增「未平倉規模」(全市場未沖銷口數×1口契約價值)
- scrape.py _rank_row:新增 main5/inst5(前五大)與 fprice(股期近月價)欄位
- rank.html:前五/前十大切換、口徑新增「交易人合計(原始值)」、金額改用股期近月價
  (缺漏退回現股價);舊 rank.json 無前五大欄位時顯示提示並退回前十大
- screener.html(新):股票期貨篩選器 — ①前五/前十(必選)②股票期貨規模
  ③當日【口徑】持有規模 ④當日【口徑】變化規模(②③④可任意組合,單位億元,可取絕對值);
  結果表可排序,點股名進個股頁;條件存 localStorage,返回不清除
- 六個 workflow 部署清單加入 screener.html
- 砂箱 git 注意:Cowork 砂箱可直接跑 git(repo 掛載),但需 core.autocrlf=true
  否則整庫誤判為已修改;push 仍須經 GitHub Desktop(砂箱無憑證)

### 2026/07/19(家用電腦)
- screener.html(公司+家用接力):②規模改「區間」(下限~上限,可只填一邊)、
  ③④持有/變化新增「規模(億)/比率(%)」切換(比率=淨部位÷全市場OI)、可取絕對值;
  新增⑤「近X日漲跌」(收盤價與 X 個交易日前相比,選上漲/下跌);結果表對應欄位、可排序
- screener 點股名 → 個股頁同步顯示設定:連結帶 ?rk=5|10&panels=t0,main,...
  (由③④選用的口徑組成);stocks.html 讀取 ?rk/?panels 只勾選對應面板(其餘不顯示)
- scrape.py _rank_row 新增 phist(近30日現股收盤序列,全史完整;缺漏退回股期)供⑤判斷
  近X日漲跌;rank.json 已重建(本地用既有 data 重算,未連期交所)
- 註:rank.json 的口徑欄位(main/inst/main5/inst5)、phist 由 _rank_row 產生,
  任何 rebuild(daily/kline/update_index)都會帶新欄位
- 股期日K回補至 2017:用期交所 futDailyMarketView 年度CSV(使用者下載,2017~2022 各一檔)本地
  建檔,經 scrape._fut_rows_pick(同 fkline 口徑:XXF月契約/一般時段/成交量最大)轉檔併入
  data/fkline/{code}.json,285 檔含 2017/01~2022/12,與既有 2023+ 無縫銜接。
  注意:2017 檔日期未補零(2017/1/3)須正規化為 YYYY/MM/DD;年度CSV 是最快的歷史回補法
  (免逐檔逐月打 futDataDown)。fkline.yml 仍可用於增量,但大量歷史建議用年度CSV。
- 股期日K完成:stocks.html K棒 2017 起顯示「股期」(322→更多檔),不足30日者仍退回現股

### 2026/07/19(家用電腦)— 每日股期報告(Email)
- 新增 `tools/report.py` + workflow `report.yml`:每日盤後抓取**成功**跑完就自動寄出篩選報告。
  觸發用 `workflow_run`(事件觸發, 非定時輪詢), 所以 15:35 主班次、21:35 備援、手動 Run workflow
  都會在約 1 分鐘內寄出; 同一資料日期用 actions/cache 防重複(主班次+備援不會各寄一封)。
  手動觸發可填 force=yes 強制重寄(測試用)。
- 篩選公式與 screener.html 完全一致(同讀 data/rank.json), 條件寫在 report.py 頂端常數區
  (RK / SCALE_* / HOLD_* / CHG_* / DAYS_* / SORT_*), 要改門檻或口徑只動這一區。
  目前設定:前十大、股期規模 2.5~500 億、自然人持有比率 > 20%、近20日上漲、依自然人比率降序。
- 信件為 HTML 表格(股名/收盤/漲跌%/股期規模/自然人持有比率/近X日漲跌), 股名是連結 →
  stocks.html?code=XX&rk=10&panels=nat(自動切前十大、只顯示該口徑面板)。
- **repo 為公開**, 報告一律不寫檔、不 commit、不部署, 只在記憶體處理後寄出。
- 需要 3 個 GitHub Secrets:`MAIL_USER`(Gmail)、`MAIL_PASS`(Gmail 應用程式密碼)、
  `MAIL_TO`(收件者, 逗號分隔可多筆)。程式端已支援多收件者。
- 電腦操作註記:Cowork 要控制 GitHub Desktop 時,用程式名稱授權會綁到外層啟動器
  (`AppData\Local\GitHubDesktop\GitHubDesktop.exe`), 但視窗其實由
  `AppData\Local\GitHubDesktop\app-<版本>\GitHubDesktop.exe` 持有, 會被判定未授權而擋掉輸入。
  解法:request_access 直接給**完整路徑**, 會自動解析到正確版本子資料夾。GitHub Desktop
  每次自動更新後版本號改變, 需重新授權一次。

### 2026/07/20(公司電腦)— 每日報告自動附圖
- 新增 `tools/shots.py` + report.yml 三個步驟:資料更新完成後自動截 **5 張圖**,以 email 附件寄出。
  1~4 = detail.html 的 外資選擇權 / 自營選擇權 / 外資期貨現貨 / 大額交易人期貨
        (近5日歷史表格 + 近六個月趨勢圖);5 = rank.html 整頁(預設即 前十大+主力)。
- 作法:在 runner 本機起 `http.server` 直接讀 repo 檔案 → headless Chromium 截圖。
  **不走 GitHub Pages** — 不必等部署完成, 也不會截到舊版。
- `detail.html` 新增 **`?days=N`**:初始只畫最近 N 個交易日(未指定=全部)。
  重要:直接以 N 筆起繪, 遠比「先畫全歷史再滾輪縮放」輕 —
  實測全歷史(2440點×多圖)縮放會把瀏覽器渲染卡死。
- report.py:`collect_shots()` 讀 `SHOTS_DIR`(預設 .shots/)→ `msg.add_attachment(...)`。
  無圖時仍正常寄純文字報告(截圖步驟設 continue-on-error, 圖掛了不影響報告)。
- **踩雷紀錄(兩個都會安靜地壞掉)**:
  1. runner 預設無 CJK 字型 → 中文全變豆腐方塊。必須 `apt-get install fonts-noto-cjk`。
  2. `actions/upload-artifact@v4` 預設排除「.」開頭的隱藏目錄, `.shots/` 會得到
     "No files were found"。需加 `include-hidden-files: true`。
- `.gitignore` 加 `.shots/` — repo 公開, 圖片只當附件, 不進版控。
- 沙箱限制:Cowork 沙箱無法下載 Chromium(網路受限), 故 shots.py 無法在本機實跑,
  改以「推上去手動觸發 workflow + 讀 log」驗證。

### 2026/07/20(公司電腦)— 圖表效能:預設期間改近六個月
- **問題**:圖表預設載入全史 → 一開圖表整頁就卡。
  實測 stocks.html 6 檔×(K棒+4口徑)= 30 張圖 × 2,440 點 ≈ **7.3 萬點**;
  detail.html 大額期貨也是 2,439 點的圖 + 2,439 列的表格。
- **修正**(兩頁一致,`DEF_DAYS=120` 個交易日 ≈ 近六個月):
  - `stocks.html`:`range.from` 預設為倒數第 120 個交易日;
    **PREFS 鍵升 v3** — 舊存檔可能存著「全部」,不升版使用者會一直卡在全史。
  - `detail.html`:圖表預設近六個月(`?days=N` 自訂、`?days=0` 或雙擊 = 全部);
    歷史表格同步只列 120 列,需要時按「顯示全部 N 筆」展開
    (全史 2,439 列 × 欄數 = 上萬個 DOM 儲存格)。
- 實測結果:初始點數 2,439 → 120(**−95%**);6 檔連續滾輪 10 次頁面全程有回應。
- 「全部」仍隨時可選 — 只是改成明確選擇,不再是預設踩到的坑。
- **量測陷阱**:Chrome 對**背景分頁**會凍結 `requestAnimationFrame`。
  用 rAF 做 await 會永遠等不到 → CDP 逾時、誤判成「網頁當掉」。
  背景分頁量效能請改用 `setTimeout`,或以「初始渲染點數」這類靜態指標為準。

### 2026/07/20(家用電腦)— 分頁欄位精簡
- 外資/自營選擇權 歷史趨勢:原「CALL/PUT 買方未平倉」改為 **「CALL/PUT 未平倉差額(口)」**
  (= diff_oi_lots = 買方−賣方,不再只看買方);欄序改為
  日期 → CALL差額 → PUT差額 → CALL金額 → PUT金額。
- 外資期貨、現貨:當日卡片的**現貨**移除「較前一日」欄(只留今日買賣差額);
  歷史表格新增「較前一日增減(口)」(期貨淨額的日變化);圖表只保留「期貨多空淨額(口)」。
- 大額交易人期貨:歷史圖表只留「淨部位」;表格只留 日期/淨部位/全市場未沖銷。
- **大額交易人選擇權分頁移除**:app.js CATS 與 index.html 卡片皆拿掉。
  **資料 data/large_opt.json 保留不刪** — tools/analyze_index.py 仍用它做指數預測特徵
  (大額選法人 C−P);頁面移除後不會被任何頁面載入,不影響效能。
  detail.html 的 large_opt 渲染程式碼保留(直接打網址仍可看),只是導覽列不再出現。
- detail.html 表頭新增 `nochart:true` 旗標:該欄只進表格、不進上方圖表的欄位選單。

(之後的修改請接著往下記)
