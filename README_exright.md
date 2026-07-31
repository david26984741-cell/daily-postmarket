# 除權息資料與還原因子 — 安裝說明

## 檔案放置位置

| 本資料夾的檔案 | 放到 repo 的 |
|---|---|
| `scrape_exright.py` | `scrape_exright.py` (repo 根目錄, 與 `scrape.py` 同層) |
| `build_adjfactor.py` | `build_adjfactor.py` (repo 根目錄) |
| `test_exright.py` | `test_exright.py` (repo 根目錄) |
| `exright_backfill.yml` | `.github/workflows/exright_backfill.yml` |
| `exright_daily.yml` | `.github/workflows/exright_daily.yml` |
| `data/exright/twse.json` | `data/exright/twse.json` |
| `data/exright/tpex.json` | `data/exright/tpex.json` |

還原因子 (`data/adjfactor/*.json`) 不隨附 —— 在 repo 根目錄執行
`python build_adjfactor.py` 即可從上述兩個 exright 檔案 + 既有的
`data/kline/` 產生 264 檔。

## 執行順序

```bash
python build_adjfactor.py     # 產生 data/adjfactor/*.json
python test_exright.py        # 列印完整驗收報告
pytest -v test_exright.py     # 或用 pytest 跑斷言
```

歷史回補若要重跑, 到 GitHub Actions 手動觸發「除權息歷史回補」。
`data/exright/_progress.json` 會記錄已完成月份, 中斷後重跑會自動續抓。

## 端點 (皆經 DevTools 實測確認)

```
TWSE  GET  https://www.twse.com.tw/rwd/zh/exRight/TWT49U
           ?startDate=YYYYMMDD&endDate=YYYYMMDD&response=json
           成功: stat == "OK"

TPEx  POST https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ
           body: startDate=YYYY/MM/DD&endDate=YYYY/MM/DD&id=&response=json
           成功: stat.lower() == "ok"
           資料在 tables[0].data
```

TPEx 兩個要注意的差異:

1. POST body 的日期是**西元**格式 (`2024/06/01`), 但回傳資料裡的日期欄位是**民國**
   (`113/06/04`)。頁面前端會做轉換, 容易看錯。
2. `stat` 是**小寫** `"ok"`, 與 TWSE 的大寫 `"OK"` 不同。
3. 欄位配置與 TWSE 不同 —— TPEx 把權值與息值拆成兩欄, 所以
   「權值+息值」在 index 7、「權/息」在 index 8, 而 TWSE 分別在 5 和 6。

`https://www.tpex.org.tw/openapi/v1/tpex_exright_daily` **不能用於回補** ——
實測只回傳最近數筆, 且不接受任何日期參數。

## 與規格書不符之處 (實測結果)

1. **「2024 年 6 月應有 278 筆」不成立。** 實測 TWSE 177 筆、TPEx 136 筆、合計 313 筆。
   TWSE 的回應是完整的 (`stat:"OK"`, 尾部 notes/formula 區塊齊全, 涵蓋 06/03–06/28),
   沒有被截斷。177 筆中 ETF 13 檔、非 ETF 164 檔、除息 172 / 除權+權息 5。
   任何子集合都湊不出 278。驗收測試因此改用合理區間, 不寫死單一數字。

2. **2412 的 2024 年除息日是 07/04, 不是 07/05。** TWSE 記錄為
   `2024/07/04 前收 125.50 -> 參考價 120.74`。而 `data/kline/2412.json` **缺少 2024/07/04
   這一天**, 直接從 07/03 跳到 07/05, 所以看起來像是 07/05 除息。還原因子仍能正確處理
   (事件日 > t 的判斷不需要該日出現在 kline 中)。

3. **2412 2025/07/03 還原後為 +1.16%, 超出規格書的 ±1%。** 這不是計算錯誤:
   當日 TWSE 參考價 129.50, 實際開 130.00 / 最低 129.50 / 收 131.00 —— 開在參考價後
   上漲 1.16%, 是真實的填息。門檻已調為 ±1.5% 並在測試中註明理由。

## 已知限制

- `data/kline/2412.json` 起始於 2017/07/12, 各檔起始日不同。還原因子只在各檔
  自己的 kline 日期範圍內產生, 早於該範圍的除權息事件不會影響因子 (也無價格可還原)。
- **除權息表不涵蓋股票分割與減資。** TWSE 的表格註記寫明「本表不含除息併案辦理退還股款
  減資或分割減資之資料」。實測到的唯一重大案例: **0050 於 2025/06/18 進行 1 拆 4**,
  還原後仍留下 −74.1% 的假跌幅。若下游要用 0050, 必須另外處理分割。
  這是還原因子方法本身的邊界, 不是抓取缺漏。
- `data/stock_map.json` 仍有多檔 `sid` 為空字串 (新光金 DD、中鴻 FC、葡萄王 MA、
  富邦媒 RM、晶電 DU、南僑 ER、中壽 HY … 等約 60 檔)。這些股票期貨無法對應到現股,
  因此拿不到還原因子。需要人工補齊代號。
