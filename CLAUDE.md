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

### 2026/07/20(家用電腦)— 報告附圖改由資料自繪
- 新增 `tools/charts.py`(matplotlib):直接讀 data/*.json 產出 4 張圖,**不再截網頁**。
  好處:不受頁面排版限制(CALL/PUT 可並置一張)、不必等部署、網站改版也不會壞。
  1_外資選擇權 / 2_自營選擇權:**一張圖含 CALL 圖 + PUT 圖 + 共用近五日表**;
  3_外資期貨現貨、4_大額交易人期貨:單圖 + 近五日表。
- 版面規則(每張一致):標題左上、當日重點數值**並排於右上**(20pt 粗體,右錨點 .90
  略往中間收);台指期收盤**一律右軸**(lw 3.2 且 zorder 置頂,才不會被柱子蓋住);
  金額單位一律**億元**(原始為千元,直接標千元會出現「80萬千元」難換算);
  下方近五日表(含今日、最新在上)有格線與表頭底色,欄位比照網站。
- 圖型:`plot_series(kind=)` — bar 強制柱狀 / line 折線 / auto(跨 0 用柱狀, 同號用折線
  並讓 Y 軸貼合範圍)。選擇權與外資期貨依需求**強制柱狀**;PUT 用 `invert=True`
  反轉配色(正值=綠, 代表空方部位增溫)。
- `tools/shots.py` 縮減為只截 **rank.html 的 `.rank-grid`**(四宮格)一張,
  其餘四張已由 charts.py 取代。report.yml 對應改成兩個步驟(產生圖表 / 產生排行截圖),
  兩者皆 continue-on-error — 圖掛掉不影響報告寄出。
- runner 仍需 `fonts-noto-cjk`(matplotlib 與截圖都會用到)。

### 2026/07/21(公司電腦)— 股期日K:每日排程其實從沒成功過
- **症狀**:網站股期日K停在 7/17,7/20 沒進來。查 index.json `status_log` 發現
  7/17、7/20 都是 `fkline: no-data` — 也就是**每日排程從這功能上線起就沒抓成功過**;
  7/17 那批資料其實是事後用 fkline.yml 手動回補的。
- **根因**:`fetch_fkline_day` 走 `Dailydownload/Daily_*.zip`,但那是**逐筆成交明細**:
  欄位 = 成交日期/商品代號/到期月份/成交時間/成交價格/成交數量,
  **單日 135 萬列、沒有開高低收**,日期還是 `20260717`(無斜線)。
  → 根本不是日K資料源,`_fut_rows_pick` 解析必然 0 筆,然後靜靜記 `no-data` 就結束。
  (檔案 3MB,探測時還發生下載逾時)
- **修正**:改用「**期貨每日交易行情下載**」契約=全部,一次請求拿回全市場(約 2,100 列)。
  - 端點仍是 `futDataDown`,但**必須 POST**(新增 `http_post()`)。
  - 「全部」= **`commodity_id=all`**。頁面上選單叫 `commodity_idt`/`commodity_id2t`,
    送出前由 `checkSubmit()` 複製到 `commodity_id`/`commodity_id2` 再 POST。
  - 實測四種組合(2026/07/21):`commodity_id=all` → 2113 列 ✓;
    `specialid`+`id2=all` → 1813 列;`commodity_id` 留空 → **只有標題列 1 行**(先前踩此坑)。
  - 「全部」會一併含 `BRF`/`GDF` 等 3 碼商品期貨 → 以當日大額交易人的股期代碼(`fk_codes`)濾除。
- **保留退路**:主路徑空手時自動退回 `futDataDown` 逐檔查詢(與 backfill_fkline 同路徑)。
  少了退路,排程只會留下 `no-data`,資料就永遠缺一天。
- **狀態改寫實情**:`ok (287 檔 · 每日行情(全部))` / `資料未更新`,不再用曖昧的 `no-data`。
- **效果**:抓取步驟 **4m53s → 59 秒**;對期交所請求 **315 次 → 1 次**。
- `tools/audit.py` 新增 `--probe-zip`(workflow「資料稽核」填 probe_zip=yes):
  印出來源的標題列、樣本列與現行解析器命中數。這次就是靠它一眼看出「解析到 0 筆」。
  期交所日後若再改格式,同樣手法可快速定位。
- 註:7/20 缺的資料已先用 fkline.yml 補齊(310 檔)。

### 2026/07/22(公司電腦)— Cowork 操作方式的取捨(重要)
- 問題:能不能全程用「檔案處理 + 程式執行」取代「操控電腦」?實測結論:**部分可以,pull/push 不行**。
- **改檔/讀檔/驗語法/分析資料** → 用 Read/Write/Edit + bash,不碰電腦操控,又快又準(本來就這樣做)。
- **git pull** → 砂箱**連得到** GitHub(`git ls-remote` 成功),但 **`git pull` 會逾時**:
  本 repo 九年資料、幾千檔,物件量大,超過工具 45 秒上限。逾時中斷會留下 `.git/index.lock`,
  而**砂箱對 `.git` 無刪除權限**(`Operation not permitted`),那個 lock 連 GitHub Desktop 都會擋
  (跳 "A lock file already exists")。清 lock 只能回頭用電腦操控(「執行」對話框下 del)。
  → **不要用 bash `git pull` 硬拉本 repo**,只會卡出 lock。pull 一律走 GitHub Desktop(增量+背景+有憑證)。
- **git push** → 砂箱無憑證,**永遠只能經 GitHub Desktop**。
- 另注意:砂箱讀 `.git/` 是舊快取(`ls` 看到的 lock 狀態不可信),要判斷 git 狀態以 GitHub Desktop 為準。
- 一句話:**盡量用程式,只有 pull/push 走 GitHub Desktop**。

### 2026/07/22~23(公司+家用電腦)— 新掛牌股期自動補證券代號 & 報告圖符號
- (公司)**報告圖標題右側**:水位值(未平倉金額/淨部位/多空淨額)不帶 +/-,方向改用顏色
  (紅正/綠負);只有「較前一日」這種真變動量保留 +/-。charts.py f_lot/f_e 加 signed 參數。
  近五日表格維持現狀(使用者確認)。
- (家用)detail.html 歷史趨勢圖:**PUT 欄位柱色反轉**(正=綠,代表空方增溫)— 與 charts.py 的
  PUT invert 口徑一致。
- (公司)**新掛牌股期自動補證券代號**:貿聯-KY 等新契約原本 sid 空白(共 86 檔)。
  原因:新契約自動發現時,大額 CSV 只有商品代號+名稱;期交所 stockLists 頁又常漏列新標的
  (實測 86 檔在該頁零命中)。
  修正:`fetch_name_sid_map()` 用當日現貨行情(TWSE MI_INDEX + 上櫃 TPEx)的「名稱→代號」
  反查補 sid;`resolve_sid()` 小型契約先繼承本尊;`_norm_name()` 破折號統一半形(KY 股)。
  只在確實缺 sid 時才抓對照(一天最多一次),純加值、查不到就維持現狀。
- **已驗證生效**:7/22 排程自動補上 貿聯3665/世芯3661/保瑞6472/台灣虎航6757 等 14 檔。
  剩 72 檔缺 sid:67 檔為已下市股期(當日無部位,不影響網站);5 檔 ETF 期貨因簡稱帶
  「ETF」尾綴對不上現貨名稱 → 7/23 再補「去 ETF 尾綴重查」規則(本機已驗 5 檔全中)。
### 2026/07/23(家用電腦)
- 歷史趨勢圖(detail.html):PUT 開頭欄位柱色反轉(正=綠 偏空/負=紅),與報告圖表一致。
- stocks.html 與 screener.html 新增口徑「**第六~十大**」(rk=6):
  = 前十大 − 前五大(t0/t1 各自相減後,主力/自然人/法人公式照舊)。
  stocks.html:NET() 支援 rk=6、radio rk6、prefs 與 ?rk=6 皆可帶入;
  screener.html:vals() 以 main−main5 / inst−inst5 推導,點股名連結帶 rk=6。
  驗證:前五 + 六~十 = 前十(t0/t1 皆成立)。rank.html 未加(未要求)。
- 盤後 Email 報告改版:口徑=第六~十大、規模 2.5~100 億、主力持有比率|x|>0%;
  輸出改**兩張表**(主力持有比率 前20高=偏多 / 前20低=偏空,TOP_N 常數可調)。
- 導覽移除「籌碼研究」分頁(analysis.html 檔案與 analysis.yml 照舊保留,直接打網址仍可看)。

### 2026/07/24 — 新增「主力6-10大 多空策略追蹤」頁
- 新增 `tools/strategy610.py` + `strategy.html`:主力第6~10大 多空固定10檔 H3 策略的每日部位追蹤器。
  - `strategy610.py`(每日由 daily.yml 產生 `data/strategy610.json`,純讀 repo 內既有資料、不對外連線):
    口徑=主力6-10比率 ((a10−a5)−2×(s10−s5))/moi;池子規模 2.5億~100億;每日比率最高10檔多、最低10檔空;
    H3 三批重疊;價格股期(fkline)優先、缺漏退回現股(kline)。輸出:今日進場、目前部位(近3日入榜次數)、
    YTD 每日策略累積 vs 台指期(txf.json)、口數/名目/保證金(估13.5%)、過往每日訊號與部位(供下拉查詢)。
  - **價格來源踩雷**:同一碼在序列中途於 fkline/kline 間切換(基差)會製造假跳空 → `ret1` 只在前後同源時計算,
    跨來源當天設 NaN(82 碼、1542 次切換,不修的話 YTD 被灌大)。
  - **等權口數**:以「單口名目盡量相等」求最少口數;基準=最貴的無小型標的(單口最大,設1口);
    有小型契約的標的一律用小型(100股)算,降低門檻。目前完整部位(31檔)名目約1.6億、保證金約2164萬。
  - `strategy.html`:頂部策略標準/邏輯/回測績效(年化43.1%·Sharpe2.43·t6.2·MDD−16.5%,毛值);
    今日/過往兩分頁;走勢圖用 Chart.js(策略紅實線 vs 台指虛線)。過往用下拉選日期(避免單頁資料過多)。
  - **驗證**:兩套獨立引擎(strategy610 與 big.pkl 回測引擎)2026 YTD 皆 +132%(現股),確認非 bug——
    2026 是特別強的年(Sharpe 5.6,長期均值 2.4);股期口徑 YTD +138%。
- 接線:app.js CATS + PAGE_MAP 新增 strategy;daily.yml 於 scrape 後、commit 前新增步驟
  (`pip install pandas numpy` → `python tools/strategy610.py`,continue-on-error);
  strategy.html 加入六個 workflow 部署 cp 清單(screener.html 之後)。
- 註:daily.yml 原本純標準庫(scrape.py),本步驟需 pandas/numpy 故自帶 pip install。
  strategy610.json 隨 `git add -A data/` 一併 commit(如 rank.json)。
- **獨立頁面(使用者要求)**:strategy.html 做成「獨立站」——移除共用頁首「每日盤後資料」、
  導覽列(不載入 app.js)、返回總覽連結;app.js CATS/PAGE_MAP 不放 strategy(原站導覽不出現此頁)。
  仍在同 repo、同 Pages 網址(.../strategy.html),仍在六個部署清單與 daily 產生步驟內。
  頁面自帶標題頁首(.sy-top,accent 底線),沿用 assets/style.css 主題。

### 2026/07/25 — 策略網站改為「去重+滾動續抱+隔日開盤進」並加歷史資料分頁
- **strategy610.py 全面改寫**(口徑改為使用者最終確認的實際可執行版):
  - 進場=訊號隔一交易日【開盤價】;持有3交易日,期間內再入榜即續抱(出場日重設為末次入榜+3日、不重複買進);
    連續3日未入榜於第3日【收盤】賣出;賣出後再入榜隔日重買。價格每筆整筆同源(股期優先退現股)。
  - 引擎用「入榜串(streak)」分組產生部位;輸出:今日新進場(隔日開盤買的新入榜檔)、目前部位(滾動book,含進場日/已持有天)、
    全期+YTD 多空對沖淨值、回測統計、逐年表。淨值=每日 mean(多當日報酬)−mean(空當日報酬),進場日開→收、其後收→收。
  - **績效(全期2017~今,毛值):年化27.2%、Sharpe1.85、t5.2、MDD−18.8%、總報酬+811%;2026 YTD +93.2%。**
    比舊「重疊H3、當日收盤進」版(年化43%)低,主因隔日開盤讓出訊號後第一天的走勢(最強一段)——此為貼近實際的代價。
  - 註:今年以來顯示【累積】報酬(年化會把5個月放大失真);今年Sharpe=累積/年化波動。
- **strategy.html**:頂部數據改新版;移除「過往查詢」分頁;新增「歷史資料」分頁(全期走勢圖 策略vs台指 + 逐年表 + 全期績效)。
  今日部位改滾動版(今日新進場可能只有0~數檔;目前部位顯示進場日/已持有天,取代舊「被選次數」)。
- 註:txf.json 實際涵蓋 2016/07~今(非僅3年),故全期圖台指線可完整對照。

### 2026/07/29~31(家用電腦)— 除權息資料與 backward 還原因子
- 新增 `scrape_exright.py`(逐月爬 TWSE+TPEx 除權息)、`build_adjfactor.py`(算還原因子)、
  `test_exright.py`(規格書 §4 全部驗收測試)、workflow `exright_backfill.yml`(手動回補,
  含斷點續抓)與 `exright_daily.yml`(每日增量)。
- 資料:`data/exright/{twse,tpex}.json`(2016-01~2026-07, 127 個月, **零失敗月份**,
  TWSE 10,751 筆 + TPEx 9,509 筆 = 20,260 筆)、`data/adjfactor/<sid>.json`(264 檔,
  backward 最新一日=1.0, 格式照規格書 §3.2 每日一個值)。
- **端點(皆用 DevTools 實查, 非猜測)**:
  - TWSE `GET /rwd/zh/exRight/TWT49U?startDate=YYYYMMDD&endDate=YYYYMMDD&response=json`,
    成功判斷 `stat=="OK"`。**必須逐月**, 跨年度區間會靜默截斷。
  - TPEx `POST /www/zh-tw/bulletin/exDailyQ`,
    body `startDate=YYYY/MM/DD&endDate=YYYY/MM/DD&id=&response=json`。
    三個陷阱:①送出是**西元**日期但回傳資料是**民國**;②`stat` 是**小寫** `"ok"`;
    ③欄位與 TWSE 不同(權值/息值拆兩欄, 故「權值+息值」在 index 7、「權/息」在 8)。
    資料在 `tables[0].data`。
  - `openapi/v1/tpex_exright_daily` **不能用**:只回最近數筆, 無日期參數(已實測)。
- **效果**:264 檔宇宙內 2,383 個除息日, 平均日報酬 **−3.646% → +0.110%**,
  跌超過 5% 者 748 → 100 筆。2412 三個除息日 −3.69/−4.38/−2.60% → +0.20/−0.61/+1.16%。
- **修正規格書三處錯誤**:
  ① 「2024/06 應有 278 筆」不成立 — 實測 TWSE 177 + TPEx 136 = 313, 回應完整未截斷,
     任何子集合都湊不出 278。驗收改用區間, 不寫死數字。
  ② 2412 的 2024 年除息日是 **07/04** 不是 07/05;且 `data/kline/2412.json` 缺 07/04 該日。
  ③ 2025/07/03 還原後 +1.16% 非計算錯誤而是真實填息(參考價 129.50, 開 130.00 收 131.00),
     門檻放寬為 ±1.5%。
- **方法邊界**:除權息表**不含分割/減資**(TWSE 表格註記自己寫明)。實測唯一重大案例
  **0050 於 2025/06/18 一拆四**, 還原後仍留 −74.1% 假跌幅, 下游用 0050 要另外處理。
  其餘殘留跳空多為大盤事件(2024/08/05 同日 140 檔), 屬真實波動不該還原。
- **抓取管道**:Cowork 沙箱連不到 twse/tpex/github(proxy 擋), 但**瀏覽器可以**。
  作法:Chrome 導到 twse.com.tw / tpex.org.tw 後用**同源 fetch** 逐月抓, 在瀏覽器內彙總,
  再用 Blob download 落地到 Downloads。沙箱只能讀 `raw.githubusercontent.com`(web_fetch), 不能寫。
- **踩雷**:沙箱跑 `git status` 會建 `.git/index.lock` 且刪不掉(`Operation not permitted`),
  會卡住 GitHub Desktop。改用 Cowork 的 `allow_cowork_file_delete` 授權後即可刪除。
  結論不變:**沙箱不要對本 repo 跑任何會寫 index 的 git 指令**。
- GitHub Desktop 授權:程式名稱會綁到外層啟動器而被擋, 要用 request_access 傳
  **`githubdesktop.exe`** 才會解析到 `app-3.6.3\githubdesktop.exe`(版本更新後需重新授權)。

(之後的修改請接著往下記)
