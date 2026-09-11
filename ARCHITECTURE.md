# 架構與資料流

本專案有兩種執行模式，共用同一份資料與同一套前端邏輯：

| 模式 | 用途 | 伺服器 | 資料來源 |
|------|------|--------|----------|
| 本機模式 | 日常使用與開發 | FastAPI | 直接查詢 SQLite |
| 靜態模式 | GitHub Pages 展示 | 無（只送檔案） | 預先匯出的 JSON |

---

## 一、為什麼需要靜態模式

GitHub Pages 是**只會送檔案、不會執行程式**的伺服器。它不能跑 Python、不能查資料庫，
因此原本由 FastAPI 完成的查詢與篩選，必須提前在本機做完並存成檔案。

---

## 二、資料流全貌

```
                   data/stock.db
              （唯一的真實資料，只存在本機）
                         │
          ┌──────────────┴───────────────┐
          │                              │
   FastAPI 查詢                  export_static.py 匯出
          │                              │
          ↓                              ↓
    本機瀏覽器                      docs/data/*.json
  （localhost:8000）                      │
                                     git push
                                          │
                                          ↓
                                   GitHub Pages
                                          │
                                          ↓
                                    訪客的瀏覽器
```

`stock.db` 始終是唯一的真實資料來源，JSON 只是由它派生出來的靜態快照。
本機模式不會讀取 JSON，仍然查詢資料庫。

---

## 三、篩選邏輯的位置

這是兩種模式最大的差異，也是設計上最需要留意的地方。

### 原本：篩選在後端

```
使用者點「投信」
   ↓
GET /api/industries/flow?date=20260910&investor=trust
   ↓
FastAPI 執行 SQL：SELECT industry, trust_amt AS amount ... ORDER BY amount DESC
   ↓
回傳已篩選、已排序的 36 筆
```

每次切換法人別、日期或下鑽，都要往返伺服器一次。

### 改為：篩選在前端

```
（事前，本機執行一次）
export_static.py 查 db，把當日「四種法人別」的資料一次寫進
docs/data/day/20260910.json

（訪客操作時）
開啟網頁 → fetch('data/day/20260910.json') → 資料留在瀏覽器記憶體
   ↓
點「投信」→ JavaScript 從記憶體取 trust_amt 欄位、排序 → 畫圖（不連網）
```

### 為何本機也改用前端篩選

若只有靜態模式使用前端篩選，就會出現兩套邏輯，日後修改要改兩遍，
並可能發生「本機正常、線上錯誤」。因此：

```
組出當日完整資料的函式（唯一一份）
        ├→ 後端端點 /api/day/{date}    → 本機前端取用
        └→ export_static.py 寫成 JSON  → 靜態前端取用
                    ↓
        兩者格式完全相同，前端篩選邏輯只有一套
```

後端端點與匯出腳本呼叫**同一個函式**產生資料，格式不可能不一致。

---

## 四、JSON 檔案的組織方式

不為「日期 × 法人別」的每個組合各產生一個檔案（24 天 × 4 法人 = 96 檔，
還有下鑽與排行的組合，數量會爆炸且同一份資料重複多次）。

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
  "streak": { "total_amt": [], "foreign_amt": [], "trust_amt": [], "dealer_amt": [] }
}
```

三個設計重點：

**1. 只存原始資料，衍生結果由前端算**

類股組成（下鑽用的個股）、個股買賣超排行、ETF 的法人買賣超，都能從 `stocks`
推導出來，不另外輸出，否則同一份資料會依四種法人別各存一次。

**2. 個股以陣列輸出，欄位名只寫一次**

當日有兩千多檔個股，若每筆都帶欄位名，檔案會膨脹一倍以上。
實測單日由 431 KB 降至 185 KB。金額一律取整（以元為單位，小數無意義）。

**3. 連續買賣超仍由後端算**

`streak` 需要跨日資料，前端手上只有當日檔案，因此四種法人別各算一份後輸出。

---

## 五、訪客操作與連網行為

| 操作 | 是否需要下載檔案 |
|------|-----------------|
| 切換法人別（外資 / 投信 / 自營商） | 否，資料已在記憶體 |
| 點類股下鑽看個股排名 | 否，當日個股已全部載入 |
| 切換「類股內顯示個股」 | 否 |
| 切換交易日 | 是，下載該日的 day/*.json |
| 類股近 20 日趨勢圖 | 是，首次下載 history.json |
| 切到主動式 ETF 頁籤 | 是，首次下載 etf.json |

多數操作不需連網，體感比本機模式更快。

---

## 六、檔案結構

```
app/static/index.html        原始檔，保留 {{v}} 與 {{mode}} 佔位符（本機用）
           app.js            雙模式：依 mode 決定讀 API 或 JSON
           style.css
           vendor/echarts.min.js

docs/                        匯出產生，GitHub Pages 的根目錄
  .nojekyll                  空檔案，關閉 GitHub 的 Jekyll 處理
  index.html                 由原始檔轉換而來
  app.js                     複製
  style.css                  複製
  vendor/echarts.min.js      複製
  data/
    meta.json                日期清單、已介接的 ETF（約 2 KB）
    day/20260910.json        每個交易日一檔（約 185 KB）
    history.json             各類股近 60 日趨勢（約 106 KB）
    etf.json                 ETF 持股、合計持股與持股變動（約 116 KB）
```

---

## 七、匯出時的三項轉換

`index.html` 不能直接複製，必須處理三件事：

**1. 絕對路徑改為相對路徑**

GitHub Pages 的網址包含 repo 名稱（`cs1dada.github.io/tw-institutional-flow/`），
絕對路徑 `/static/style.css` 會被解讀為 `cs1dada.github.io/static/style.css`，
少了 repo 名稱而 404。

```
href="/static/style.css"  →  href="style.css"
src="/static/app.js"      →  src="app.js"
```

`app.js` 中讀取資料的路徑同樣必須是 `data/day/*.json` 而非 `/data/day/*.json`。

**2. 版本號佔位符替換**

`{{v}}` 原本由 FastAPI 即時注入，靜態版需在匯出時寫入實際數值。

**3. 注入模式標記**

`{{mode}}` 替換為 `static`，讓 `app.js` 知道該讀 JSON 而非打 API。
本機由 FastAPI 注入 `api`。不以網域判斷，避免誤判。

---

## 八、部署流程

每日在本機執行：

```bash
python scripts/daily_job.py       # 抓當日三大法人與 ETF 持股
python scripts/export_static.py   # 匯出 JSON 與靜態頁面到 docs/
git add docs && git commit -m "更新資料" && git push
```

push 後 GitHub Pages 自動更新。

GitHub 端只需設定一次：Settings → Pages → Source 選 `main` 分支的 `/docs` 資料夾。

### 為何不用 GitHub Actions 自動抓資料

Actions 每次執行都是全新環境，沒有 `stock.db`，需額外處理資料庫的保存與還原；
且 Actions 的資料庫與本機是兩份獨立資料，可能不同步。
本機已有每日排程，多接兩行指令即可，架構單純且資料只有一份來源。

代價是電腦未開機的日子線上資料不會更新。

---

## 九、風險

| 項目 | 狀態 |
|------|------|
| 兩種模式的畫面與互動是否一致 | **已驗證**：以 http.server 模擬 GitHub Pages 實測，畫面相同，切換日期與法人別、下鑽、ETF 頁籤皆正常 |
| 證交所是否擋境外 IP | **已驗證不擋**（自境外呼叫 T86 回傳 stat=OK） |
| 各投信 API 是否擋境外 | 未驗證；因採本機匯出，實際上不受影響 |
| repo 體積成長 | 每日新增一批 JSON，一年約 50MB；可限制只保留最近 60 個交易日 |
| 資料庫不納入版本控制 | `data/stock.db` 仍在 .gitignore 中，不會被推上 GitHub |
