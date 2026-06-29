# 每日盤後資料 — 期交所/證交所 三大法人與大額交易人

每個交易日下午自動抓取台灣期交所 (TAIFEX) 與證交所 (TWSE) 指定資料，整理成六大分類，
逐日累積歷史，並產生一個給客戶觀看的純前端靜態網站。

## 六大分類與資料來源

| # | 分類 | 來源 | 取用內容 |
|---|------|------|----------|
| 1 | 外資選擇權 | `callsAndPutsDate` | 臺指選擇權 · 外資及陸資 · **未平倉** (買方/賣方/買賣差額, CALL+PUT) |
| 2 | 自營選擇權 | `callsAndPutsDate` | 臺指選擇權 · 自營商 · **未平倉** (買方/賣方/買賣差額, CALL+PUT) |
| 3 | 外資期貨、現貨 | `futContractsDate` + TWSE `BFI82U` | 臺股期貨外資未平倉 + 外資及陸資(不含外資自營商)現貨買賣差額 |
| 4 | 大額交易人選擇權 | `largeTraderOptQry` | 臺指買權 + 臺指賣權 全部資料 |
| 5 | 大額交易人期貨 | `largeTraderFutQry` | 臺股期貨 · 當月 + 所有契約 (不含週契約) |
| 6 | 大額交易人股票期貨 | `largeTraderFutQry` | 各個股期貨，**每檔獨立一頁**，依契約名稱對齊歷史 |

## 檔案結構

```
每日盤後資料/
├─ scrape.py              # 抓取主程式 (純標準函式庫, 無第三方相依)
├─ requirements.txt
├─ index.html             # 頁面A:當日整合總覽
├─ detail.html            # 頁面B:各分類明細 (當日 + 歷史)  ?cat=<分類id>
├─ stock.html             # 個股期貨明細 (當日 + 歷史)        ?code=<商品代碼>
├─ assets/style.css, app.js
├─ data/                  # 逐日累積的結構化資料 (JSON)
│  ├─ index.json          # 最新日期、分類清單、個股清單、各來源狀態
│  ├─ options_foreign.json / options_dealer.json
│  ├─ foreign_fut_spot.json / large_opt.json / large_fut_txf.json
│  ├─ stocks/<代碼>.json   # 每檔個股期貨一個檔, records 以日期為鍵
│  ├─ stock_map.json      # 商品代碼 → 個股簡稱/證券代號 對照
│  └─ holidays.txt        # 休市日清單 (請依期交所公告維護)
├─ tools/seed_2026-06-23.py  # 一次性種子資料 (建立雛形, 之後由 scrape.py 接手)
└─ .github/workflows/daily.yml  # 每交易日 15:05(台北) 自動執行 + commit + 部署
```

## 資料時效性與正確性規則 (已實作於 scrape.py)

- **當日驗證**:抓取後比對 CSV/JSON 內的資料日期必須等於目標日期，否則視為「尚未更新」。
- **30 分鐘重試**:未更新時等待 30 分鐘重抓，最多 6 次 (約 3 小時)。可用環境變數 `RETRY_WAIT`、`MAX_RETRY` 調整。
- **不覆蓋歷史**:每天以「日期」為鍵 append；同日重跑只覆蓋當日，不動其他日期。
- **休市判斷**:週末自動排除 + `holidays.txt` + 「來源無當日資料」三重保護。
- **個股對齊**:一律以商品代碼／契約名稱對齊，不用排序位置；新增/下架自動處理。
- **失敗標註**:多次重試仍非當日資料時，於 `index.json` 狀態與網站標註「資料未更新」，不以舊資料假冒。

## 本機測試

```bash
# 抓取 (需可連外網路;指定日期、略過 30 分鐘等待)
python scrape.py --date 2026/06/23 --no-retry

# 本機預覽網站 (因前端以 fetch 讀 JSON, 需用 http 伺服器而非直接開檔)
python -m http.server 8000
# 瀏覽器開 http://localhost:8000/
```

> 註:本專案附帶的 `data/` 為 2026/06/23 的種子資料。分類 1–4 與主要個股為當日真實數值；
> 分類 5 (臺股期貨大額) 與其餘個股將於首次正式排程執行時由完整 CSV 自動補齊。

## 部署到 GitHub Pages (固定網址、每日自動更新)

1. 在 GitHub 建立一個 **public** 倉庫，例如 `daily-postmarket`。
2. 將本資料夾所有內容 push 上去:
   ```bash
   cd 每日盤後資料
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<你的帳號>/daily-postmarket.git
   git push -u origin main
   ```
3. 倉庫 **Settings → Pages**:Source 選「Deploy from a branch」，Branch 選 `main`、資料夾 `/ (root)`，存檔。
   數分鐘後網址為 `https://<你的帳號>.github.io/daily-postmarket/` (完全公開)。
4. 倉庫 **Settings → Actions → General**:Workflow permissions 設為「Read and write permissions」(讓排程能 commit 資料)。
5. 完成。`.github/workflows/daily.yml` 會在每交易日 15:05(台北時間) 自動執行抓取 →
   commit 更新 `data/` → GitHub Pages 自動重新部署。也可在 **Actions** 分頁手動 `Run workflow` (可指定日期) 立即測試。

## 自訂

- 修改抓取時間:編輯 `daily.yml` 的 `cron` (UTC 時間)。
- 新增/維護休市日:編輯 `data/holidays.txt`。
- 歷史保留:預設無限累積。如需只留一年，可於 `scrape.py` 加入清理舊鍵的邏輯。

---
資料來源:臺灣期貨交易所、臺灣證券交易所。本網站僅供參考，不構成投資建議。
