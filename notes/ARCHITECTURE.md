# 架構與資料流

本專案有兩種執行模式，共用同一套前端，差別只在資料從哪裡來：

| 模式 | 用途 | 伺服器 | 資料來源 | 資料庫 |
|------|------|--------|----------|--------|
| 本機模式 | 日常使用與開發 | FastAPI | 即時查詢 SQLite | 本機的 `data/stock.db` |
| 靜態模式 | GitHub Pages 線上版 | 無 (只送檔案) | 預先匯出的 JSON | GitHub Actions 快取裡的 `stock.db` |

靜態模式的網址為 <https://cs1dada.github.io/tw-institutional-flow/>。

**兩份資料庫是分開的、互不同步**，這是理解整個專案最重要的一點：
本機抓的資料只會出現在本機網站，線上網站的內容完全由 Actions 那份資料庫產生。

---

## 〇、前端與資料的分工

網站由兩個獨立的部分組成，更新頻率完全不同：

```
frontend/  --npm run build-->  dist/  --deploy_web.py-->  docs/       「殼」
                                                                      改前端時才更新 (本機執行)

stock.db   ----------export_static.py------------------>  docs/data/  「資料」
                                                                      每個交易日更新 (Actions 執行)
```

- **殼**：Vue 3 + TypeScript + Vite 的建置產物。`deploy_web.py` 會先清空 `docs/`
  (保留 `data/`、`.nojekyll` 與 `*.png`)，再把 `dist/` 整個複製進去，不做任何內容轉換。
  改了前端之後要在本機執行 `npm run build` 與 `deploy_web.py`，再 commit `docs/`。
- **資料**：由 GitHub Actions 每日更新，只寫 `docs/data/`。

Actions 不會動到殼，所以 CI 上不需要安裝 Node.js。這是兩者分開的主要理由。

---

## 一、為什麼需要靜態模式

GitHub Pages 是**只會送檔案、不會執行程式**的伺服器。它不能跑 Python、不能查資料庫，
因此原本由 FastAPI 完成的查詢，必須事先做完並存成 JSON 檔案。

---

## 二、資料流全貌

### 本機模式：抓完重新整理就看得到

```
各資料來源 (證交所、櫃買、期交所、各投信)
        │  ingest_day.py / backfill.py / ingest_etf.py / ingest_index.py ...
        ↓
本機 data/stock.db
        │  FastAPI 每次收到請求時即時查詢 (app/api/routes.py)
        ↓
/api/meta、/api/day/{date}、/api/history ...
        ↓
http://127.0.0.1:8000 (前端以 mode=api 執行)
```

不需要匯出 JSON，也不會讀取 `docs/data/`。

### 靜態模式：一律由 GitHub Actions 產生

```
各資料來源 (證交所、櫃買、各投信)
        │  daily.yml：daily_job.py、ingest_etf.py
        │  backfill.yml：backfill.py、backfill_etf.py
        ↓
Actions 快取裡的 stock.db (actions/cache 在每次執行之間保存)
        │  export_static.py
        ↓
docs/data/*.json
        │  Actions 自動 commit & push
        ↓
GitHub Pages 自動部署
        ↓
訪客的瀏覽器 (前端以 mode=static 執行，直接讀 JSON)
```

### 兩邊的差異

| | 本機 | 線上 |
|------|------|------|
| 前端模式 | `api` | `static` |
| 前端讀取 | `/api/meta`、`/api/day/{date}` ... | `data/meta.json`、`data/day/*.json` ... |
| 資料庫 | 本機 `data/stock.db` | Actions 快取裡的 `stock.db` |
| 誰抓資料 | 手動執行腳本 | Actions 排程或手動觸發 workflow |
| 是否需要匯出 | 不需要 | 需要 `export_static.py` |
| 資料範圍 | 取決於本機回補了多少 | 取決於 Actions 回補了多少，每日類股只匯出最近 60 個交易日 |

兩份資料庫涵蓋的期間不同，因此同一個功能 (例如經理人成本) 在本機與線上可能算出不同的期間與數字。

---

## 三、同一份資料，兩種輸出

前端的篩選、排序、下鑽都在瀏覽器裡做，後端只負責組出「當日完整資料」：

```
（事前）export_static.py 把當日四種法人別的資料一次寫進 docs/data/day/20260910.json

（訪客操作時）
開啟網頁 → fetch('data/day/20260910.json') → 資料留在瀏覽器記憶體
   ↓
點「投信」→ JavaScript 從記憶體取 trust_amt 欄位、排序 → 畫圖 (不連網)
```

為了避免兩套邏輯造成「本機正常、線上錯誤」，本機也走相同路徑：

```
app/services/dataset.py 的 build_day / build_meta / build_history / build_etf / build_index
        ├→ 後端端點 /api/day/{date} 等  → 本機前端取用
        └→ export_static.py 寫成 JSON   → 靜態前端取用
```

後端端點與匯出腳本呼叫**同一個函式**產生資料，格式不可能不一致。
經理人成本的計算也只有一份 (`app/services/etf_cost.py`)：本機端點呼叫
`build_summary` / `build_detail`，匯出時呼叫 `compute`，兩者底層相同。

前端在 `frontend/src/api/dataSource.ts` 依模式切換讀取的網址：

| 資料 | 本機 (api) | 線上 (static) |
|------|-----------|---------------|
| 日期清單 | `/api/meta` | `data/meta.json` |
| 每日資料 | `/api/day/{date}` | `data/day/{date}.json` |
| 類股趨勢 | `/api/history` | `data/history.json` |
| ETF 持股 | `/api/etf-data` | `data/etf.json` |
| 大盤指數 | `/api/index-data` | `data/index.json` |
| 經理人成本 | `/api/etf-cost` | `data/etf_cost.json` |
| 個股成本疊圖 | `/api/etf-cost/{code}` | `data/etf_cost/{code}.json` |

可以把線上版想成「事先把本機 API 會回傳的內容全部存成檔案」：

```
                 app/services/dataset.py、etf_cost.py
                              │
          ┌───────────────────┴───────────────────┐
     本機：每次請求時呼叫                 線上：每天匯出時呼叫一次
     app/api/routes.py                    scripts/export_static.py
          │                                       │
     回傳 JSON 給瀏覽器                     寫成 docs/data/*.json
          │                                       │
          └──────────── 前端拿到的格式一模一樣 ────┘
```

邏輯相同，但仍有幾點不同：

| 項目 | 本機 | 線上 |
|------|------|------|
| 資料時效 | 即時查詢，抓完重新整理就看得到 | 等 Actions 匯出後才更新 |
| 可選的日期 | 日期選單列出最近 120 個交易日 (`list_dates` 的預設值)，資料庫有的日期都能查 | 只有匯出的 60 個交易日 |
| 經理人成本 | 每次請求都重新計算，查單一個股的疊圖也會整批重算，較慢 | 匯出時一次算完，存成個股各一檔 |
| 只有本機才有的端點 | `/api/intraday`、`/api/quote/*`、`/api/sino/*`、`/api/history/{code}` (個股 K 線) | 無，這些需要即時連外或 API 金鑰 |

`app/api/routes.py` 另外還留有 `/api/dates`、`/api/industries/*`、`/api/stocks/ranking`、
`/api/etf/*` 等早期依參數篩選的端點，目前前端已不再呼叫。

---

## 四、JSON 檔案的組織方式

不為「日期 × 法人別」的每個組合各產生一個檔案 (60 天 × 4 法人 = 240 檔，
還有下鑽與排行的組合，數量會爆炸且同一份資料重複多次)。

改為**一個交易日一個檔案，包含該日全部資料**：

```json
{
  "date": "20260910",
  "industries": [
    { "industry": "半導體業", "total_amt": 2740000000, "foreign_amt": 980000000,
      "trust_amt": 2150000000, "dealer_amt": -400000000,
      "buy_count": 72, "sell_count": 38, "stock_count": 110 }
  ],
  "stock_fields": ["code","name","market","industry","is_etf","close",
                   "total_amt","foreign_amt","trust_amt","dealer_amt"],
  "stocks": [
    ["2454","聯發科","TWSE","半導體業",0,4720,8407000000,7800000000,400000000,207000000]
  ],
  "streak": { "total_amt": [], "foreign_amt": [], "trust_amt": [], "dealer_amt": [] },
  "streak_days": 10,
  "etf_changes": []
}
```

五個設計重點：

**1. 只存原始資料，衍生結果由前端算**

類股組成 (下鑽用的個股)、個股買賣超排行、ETF 的法人買賣超，都能從 `stocks`
推導出來，不另外輸出，否則同一份資料會依四種法人別各存一次。

**2. 個股以陣列輸出，欄位名只寫一次**

當日有兩千多檔個股，若每筆都帶欄位名，檔案會膨脹一倍以上。
當初實測單日由 431 KB 降至 185 KB；加入 `etf_changes` 後目前每檔約 190 至 230 KB。
金額一律取整 (以元為單位，小數無意義)。

**3. 連續買賣超仍由後端算**

`streak` 需要跨日資料，前端手上只有當日檔案，因此四種法人別各算一份後輸出。
回看天數固定為 10 天 (`STREAK_DAYS`)，寫在 `streak_days`。

**4. ETF 持股變動放在每日檔**

`etf_changes` 是各 ETF 截至當日的最新快照與前一個快照的差異。放在每日檔裡，
切換交易日時就會跟著換，不必另外下載。海外持股的 ETF 基準日較晚，當日可能比對的是前一日。

**5. 指數只輸出日線**

`index.json` 以陣列輸出最近 2500 個交易日 (約十年) 的日線，每筆為日期、開高低收、
成交金額 (億元) 與漲跌。週線與月線由前端聚合而成 (`frontend/src/utils/indexBars.ts`)，
不各存一份：聚合規則單純 (期初開盤、期末收盤、期間高低極值、成交金額加總)，
放在前端還能即時切換週期而不必再次下載。

---

## 五、訪客操作與連網行為

| 操作 | 是否需要下載檔案 |
|------|-----------------|
| 開啟類股資金流向頁 | 是，下載 meta.json、當日 day/*.json 與 history.json |
| 切換法人別 (外資 / 投信 / 自營商) | 否，資料已在記憶體 |
| 點類股下鑽看個股排名 | 否，當日個股已全部載入 |
| 切換「類股內顯示個股」 | 否 |
| 切換交易日 | 是，下載該日的 day/*.json |
| 類股趨勢圖 | 否，history.json 含 60 天，前端只畫最近 20 天 |
| 切到主動式 ETF 頁 | 是，首次下載 etf.json 與 etf_cost.json (meta 與當日檔已在記憶體則沿用) |
| 在經理人成本表點選個股 | 是，首次下載該股的 etf_cost/{代號}.json |
| 切到大盤指數頁 | 是，首次下載 index.json |

前端 PWA 的 Service Worker 另有快取規則 (`frontend/vite.config.ts`)：
`day/*.json` 內容不會再變，採 CacheFirst；`meta.json` 採 NetworkFirst；
history、etf、index 採 StaleWhileRevalidate。

---

## 六、檔案結構

```
app/
  main.py                    FastAPI 進入點，送出 dist/index.html 並注入模式旗標
  config.py                  設定與功能開關 (INTRADAY_ENABLED、各 API 金鑰)
  db.py                      SQLite 連線與資料表定義
  api/
    routes.py                /api 主要端點 (本機模式的資料來源)
    quote_routes.py          /api/quote/* 富果報價
    sino_routes.py           /api/sino/* 永豐 Shioaji 報價
  fetchers/                  對外抓取資料，一個來源一個模組
    twse.py / tpex.py        證交所、櫃買的三大法人與收盤行情
    isin.py                  個股主檔與產業別
    taifex.py                期交所微台期即時報價與期貨日線
    index_quote.py           大盤指數日線 (以月為單位抓取)
    intraday.py              盤中即時報價 (MIS)，只有本機模式會用到
    fugle.py / sinotrade.py  富果、永豐 API
    etf/                     各投信的主動式 ETF 持股 (野村、統一、群益、安聯、中信)
  services/
    ingest.py                匯入單日資料、類股聚合
    aggregate.py             類股聚合邏輯
    dataset.py               組出前端所需資料，本機端點與匯出共用
    etf_ingest.py            ETF 持股寫入
    etf_cost.py              經理人成本推估
    index_ingest.py          大盤指數寫入
    history.py               個股與期貨日線查詢
    intraday.py              盤中類股聚合與記憶體快取
    quote.py / sino_quote.py 報價頁的資料整理

scripts/
  init_db.py                 建立資料表並抓個股主檔
  daily_job.py               每日排程進入點 (見第八節)
  ingest_day.py              匯入單日三大法人與收盤行情
  ingest_etf.py              抓主動式 ETF 最新持股
  ingest_index.py            抓大盤指數日線
  backfill.py                回補三大法人與收盤行情
  backfill_etf.py            回補 ETF 歷史持股
  backfill_ohlc.py           只回補個股開高低收
  backfill_futures.py        回補期貨日線
  export_static.py           匯出 docs/data/*.json
  deploy_web.py              把 dist/ 複製到 docs/
  make_icons.py              產生 PWA 圖示

frontend/                    前端 (Vue 3 + TypeScript + Vite)
  index.html                 以 %VITE_APP_MODE% 等佔位符宣告模式旗標
  .env.development           開發模式：mode=api
  .env.production            正式建置：mode=static，報價與盤中頁關閉
  src/api/dataSource.ts      依模式決定讀 API 或 JSON
  src/router.ts              hash 路由，GitHub Pages 不會 404
  src/views/                 六個功能頁
    IndustryFlowView.vue     類股資金流向 (/)
    EtfView.vue              主動式 ETF 與經理人成本 (/etf)
    IndexChartView.vue       大盤指數 K 線 (/index)
    IntradayView.vue         盤中觀察 (/intraday，僅本機且需開啟)
    QuoteView.vue            富果報價 (/quote，僅本機且需金鑰)
    SinoQuoteView.vue        永豐報價 (/sino，僅本機且需金鑰)
  src/components/            圖表與側邊導覽
  src/utils/                 計算邏輯 (類股聚合、K 線聚合、格式化、主題)
  public/pwa-*.png           PWA 圖示，不納入版控，由 make_icons.py 產生

dist/                        npm run build 的產物，不納入版控

docs/                        GitHub Pages 的根目錄
  .nojekyll                  空檔案，關閉 GitHub 的 Jekyll 處理
  index.html、assets/        ┐
  sw.js、workbox-*.js        │ 由 deploy_web.py 從 dist/ 複製
  registerSW.js              │ 只在改動前端時才需要更新
  manifest.webmanifest       ┘
  *.png                      PWA 圖示與 README 用的截圖
  data/
    meta.json                已匯出的日期清單、已介接的 ETF (約 4 KB)
    day/20260910.json        每個交易日一檔 (約 190 至 230 KB)
    history.json             各類股近 60 日趨勢 (約 260 KB)
    etf.json                 ETF 持股、合計持股與持股變動 (約 160 KB)
    etf_cost.json            經理人成本：各股共識價與每日買賣摘要 (約 50 KB)
    etf_cost/2330.json       個股的成本疊圖資料，每檔約 1 至 3 KB，每次匯出整批重建
    index.json               加權指數日線，約十年 (約 150 KB)
```

資料表定義見 [SCHEMA.md](SCHEMA.md)。

---

## 七、模式旗標與路徑處理

同一份建置產物要能同時在本機與 GitHub Pages 執行，靠下列機制處理：

**1. 相對路徑**

GitHub Pages 的網址包含 repo 名稱 (`cs1dada.github.io/tw-institutional-flow/`)，
絕對路徑會少了 repo 名稱而 404。因此：

- Vite 正式建置時設定 `base: "./"`，資源檔一律以相對路徑引用
- 路由採 hash 模式 (`#/etf`)，重新整理時伺服器只會收到根路徑
- 資料檔路徑寫成 `data/day/*.json`，不加開頭的 `/`

**2. 模式旗標**

`frontend/index.html` 宣告四個全域旗標：

```html
window.APP_MODE = "%VITE_APP_MODE%";
window.APP_INTRADAY = "%VITE_APP_INTRADAY%";
window.APP_QUOTE = "%VITE_APP_QUOTE%";
window.APP_SINO = "%VITE_APP_SINO%";
```

- 建置時由 Vite 依 `.env.production` 填入 `static` / `off` / `off` / `off`，
  這就是 GitHub Pages 上的版本
- 本機由 `app/main.py` 送出 `dist/index.html` 時把 `APP_MODE` 換成 `api`，
  其餘三個依 `config.py` 的開關與金鑰是否存在換成 `on` 或 `off`

不以網域判斷模式，避免誤判。

**3. 快取與版本**

- JS 與 CSS 由 Vite 產生帶 hash 的檔名 (例如 `assets/index-DjtoyfGK.js`)，內容改變檔名就變
- GitHub Pages 對靜態檔案回應 `Cache-Control: max-age=600`，因此 `meta.json`
  每次請求都附上時間戳以取得最新版，其餘資料檔則帶上 meta 中的 `generated_at` 作為版本
  (`dataSource.ts` 的 `versioned()`)；資料未更新時仍可沿用快取
- 本機不使用 PWA：`main.py` 把註冊 Service Worker 的標籤換成註銷腳本，`/sw.js` 也回傳會自我註銷的版本，
  避免開發時被舊快取卡住

---

## 八、線上資料的更新方式

線上資料完全由 GitHub Actions 維護，不需要本機介入。有兩個 workflow：

| workflow | 觸發方式 | 用途 |
|------|------|------|
| `daily.yml` 每日更新資料 | 週一至週五 UTC 08:40 (台灣 16:40)，也可手動 | 抓當日資料並更新網站 |
| `backfill.yml` 回補歷史資料 | 只能手動，填入起訖日 | 往前回補三大法人與 ETF 持股 |

兩者共用 `concurrency: daily-update`，同時觸發時會排隊執行，不會同時修改資料庫。

### 每日排程 (daily.yml)

選在 16:40 是因為上市三大法人約 16:00 才公布，更早會抓不到。
GitHub 的排程不保證準時，實際可能延後數十分鐘甚至數小時。

```
還原資料庫快取 → daily_job.py → ingest_etf.py 補抓 → export_static.py → commit & push
                                                                       ↓
                                                               GitHub Pages 自動部署
```

`daily_job.py` 依序做五件事：

1. 個股主檔超過 7 天未更新時重新抓取 (新上市、產業重分類)
2. 匯入今日三大法人與收盤行情
3. 抓取主動式 ETF 最新一日的持股
4. 重抓最近 2 個月的大盤指數 (尚無資料時回補 120 個月)
5. 補抓近 7 天內資料不齊全的工作日 (排程跑得早只拿到上櫃、或當天沒執行)

部分投信較晚公布持股，因此之後再跑一次 `ingest_etf.py` 補抓 (continue-on-error，失敗不影響其他步驟)。

### 回補歷史資料 (backfill.yml)

在 GitHub 的 Actions 頁面選「回補歷史資料」，或用指令觸發：

```bash
gh workflow run backfill.yml -f inst_start=20260101 -f inst_end=20260630 \
                             -f etf_start=20260101 -f etf_end=20260909
```

| 輸入 | 說明 |
|------|------|
| `inst_start` / `inst_end` | 三大法人與收盤行情的起訖日，空白則不回補 |
| `etf_start` / `etf_end` | ETF 持股的起訖日，空白則不回補 |

注意事項：

- **先補三大法人再補 ETF**：`backfill_etf.py` 以資料庫 `daily_price` 中的日期作為交易日，
  沒有股價的期間會被當成「0 個交易日」直接略過。兩者在同一次執行時會依序進行，不必分開跑
- **時間上限**：整個 job 200 分鐘，三大法人一步 60 分鐘，ETF 一步 150 分鐘。
  每個請求間隔 3 秒，三大法人每個交易日 4 個請求，一次約可補半年
- **可以中斷續跑**：快取的還原與存回分成兩步，存回設為 `if: always()`，
  逾時或失敗時已完成的部分仍會存回；再次執行時會略過已存在的日期
- **投信保留期限不同**：連續 3 個交易日查不到就停止往前，例如中信只保留近期資料
- 找不到資料庫快取時直接失敗，需要先跑過一次每日排程
- 最後同樣會匯出並 commit (訊息為「chore: 回補歷史資料」)

### Actions 的資料庫怎麼保存

每次執行都是全新機器，`data/stock.db` 不在版本控制中。因此：

- 用 `actions/cache` 在每次執行之間保存資料庫
- 快取金鑰每次不同 (`stock-db-<run_id>`) 以便存入新版，`restore-keys` 以前綴取回最近一次的內容
- `daily.yml` 使用合併版的 `actions/cache`，**只有整個 job 成功時才會存回**；
  `backfill.yml` 則不論成敗都會存回
- 每個 repo 的快取上限為 10 GB，超過時自動淘汰最舊的；資料庫壓縮後約 11 MB，離上限很遠
- 快取 7 天未使用會被 GitHub 清除，每日排程會持續使用，平常不會發生

快取不存在時 (首次執行或被清除)，`daily.yml` 會重新建立資料庫並回補最近 100 個日曆日 (約 68 個交易日) 的三大法人，
足以涵蓋匯出的 60 個交易日，網站可以直接恢復更新。耗時約 15 分鐘，在 job 的 30 分鐘上限內。
之前回補的 ETF 持股與更早的歷史資料都需要再用 `backfill.yml` 重跑。

### 匯出的保護機制

`export_static.py` 只匯出最近 60 個交易日 (`DEFAULT_DAYS`)，超出範圍的舊 `day/*.json`
不會刪除，但 `meta.json` 不會列出它們，前端也就不會讀到。

為了避免以較少的資料覆蓋線上內容，`export_static.py` 會比較「本次匯出的天數」與
「既有的 day 檔數與 60 兩者取小」，本次較少時就中止，需明確加上 `--force` 才會覆蓋。
中止時結束碼仍為 0，workflow 會顯示成功，但提交步驟會印出「資料無變動，略過提交」。
網站沒有更新時，先檢查匯出步驟的 log。

### 對本機操作的影響

Actions 會自動 commit `docs/` 並推回 repo，因此**本機 push 前要先 pull**：

```bash
git pull --rebase
```

本機平常不需要執行 `export_static.py`，也不要推送本機匯出的 `docs/data/`，
否則會用本機資料庫的內容蓋掉線上資料。要更新線上資料，改為觸發 workflow：

```bash
gh workflow run daily.yml           # 立即跑一次每日更新
gh run list --workflow daily.yml    # 查看執行結果
```

---

## 九、盤中資料為何不進資料庫

盤中觀察頁預設關閉 (`config.py` 的 `INTRADAY_ENABLED = False`)，關閉時側邊欄不顯示入口，
`/api/intraday` 回傳 404，後端也不會對外送出任何請求。開啟後的路徑與其他頁完全不同：

```
其他頁：證交所盤後資料 -> stock.db -> FastAPI / JSON 匯出 -> 前端

盤中頁：證交所 MIS 即時報價 -> 記憶體快取 (180 秒) -> FastAPI -> 前端
                                  (不寫入資料庫)
```

三個原因：

**1. 盤中資料是瞬時值，隔天就沒有意義**

「開盤至今的成交金額」只在當下有參考價值，收盤後會被完整的盤後資料取代，
而盤後資料本來就會寫進 `daily_price`。存下來只會讓資料庫多出一份較不準確的重複資料。

**2. 靜態站無法提供這一頁**

MIS 端點沒有 `access-control-allow-origin` 標頭，瀏覽器直接呼叫會被 CORS 擋下；
GitHub Pages 又只會送檔案、不能執行程式，沒有地方可以代為抓取。
因此正式建置的 `APP_INTRADAY` 固定為 `off`，側邊欄 (`SideNav.vue`) 在靜態模式下不顯示這個項目。
`/intraday` 路由仍存在，直接輸入網址會進入頁面但讀不到資料。

**3. 來源有請求量限制**

掃完全市場要 24 個請求 (單次上限實測為 120 檔，取 100 保留餘裕)。
MIS 原本是給看盤頁查少數幾檔用的，連續密集掃描會被封鎖：

> 實測在半小時內送出約 200 個請求後，整個 `mis.twse.com.tw` 對該 IP
> 停止回應達 20 分鐘以上，連 `fibest.jsp` 網頁本身都是 `ERR_EMPTY_RESPONSE`。
> 同一時間 `www.twse.com.tw`、`www.tpex.org.tw`、`isin.twse.com.tw` 都正常，
> 封鎖只針對 MIS 這個主機，每日盤後更新不受影響。

三分鐘一輪等於每分鐘 8 個請求，一個交易日約 2200 個請求。

因此後端做了四層保護：

- 快取 180 秒，多個分頁共用同一份，不會各自觸發掃描
- 併發限制在 3 條 (實測併發 6 會開始被斷線)
- 只在 08:30 至 14:00 之間抓取，收盤後沿用最後一份
- 掃描結果明顯不完整 (完全沒有報價，或不到前一份的一半) 時**不覆蓋快取**，
  改為沿用前一份並標示 `stale`，同時進入退避 (60 秒起，連續失敗加倍，最多 30 分鐘)

沒有最後一層保護的話，被封鎖的當下畫面會整個變成空白。

---

## 十、風險

| 項目 | 狀態 |
|------|------|
| 兩種模式的畫面與互動是否一致 | **已驗證**：以 http.server 模擬 GitHub Pages 實測，畫面相同，切換日期與法人別、下鑽、ETF 頁皆正常 |
| 證交所是否擋境外 IP | **已驗證不擋** (自境外呼叫 T86 回傳 stat=OK) |
| 各投信 API 是否擋境外 | **已驗證不擋**：Actions 在境外執行，每日排程能正常抓到各投信的持股 |
| GitHub 快取遺失 | 會重建並回補 100 個日曆日，足以涵蓋匯出的 60 個交易日，網站可直接恢復更新。更早的三大法人與所有 ETF 歷史持股需手動執行 `backfill.yml` 補回，否則經理人成本的期間會縮短。回補天數若少於 60 個交易日，匯出保護會擋下更新 |
| 排程延遲 | GitHub 的排程可能延後數小時；`daily_job.py` 會補抓近 7 天不齊全的工作日，隔天仍會補上 |
| repo 體積成長 | 舊的 day/*.json 不會刪除，每個交易日約增加 200 KB；history、etf、index、etf_cost 每天整檔重寫，git 歷史持續變大。目前 `docs/data` 約 13 MB |
| 資料庫不納入版本控制 | `data/stock.db` 在 .gitignore 中，不會被推上 GitHub |
