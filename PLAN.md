# 台股三大法人類股資金流向網站 — 實作計畫

**建立日期**：2026-09-10

**選定方向**：Python + FastAPI + SQLite、上市 + 上櫃、本機執行、歷史回補近一個月

---

## 一、資料來源（已實測可用）

| 用途 | 端點 | 說明 |
|------|------|------|
| 上市個股三大法人買賣超 | `https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALL&response=json` | 外資、投信、自營商買賣超**股數**，逐檔 |
| 上市每日收盤價 | `https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL` | 用來把股數換算成金額 |
| 上市公司產業別 | `https://openapi.twse.com.tw/v1/opendata/t187ap03_L` | 欄位「產業別」為代碼 (01 水泥、24 半導體…) |
| 上櫃個股三大法人 | `https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading` | 欄位為英文，命名不一致但有完整資料 |
| 上櫃公司產業別 | `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O` | 欄位 `SecuritiesIndustryCode` |

全部免費、免金鑰，不需要爬蟲繞驗證。

**重要前提**：官方沒有現成的「類股資金流向」資料，必須自行以個股資料 join 產業別後聚合產生。

---

## 二、專案結構

```
D:\sideproject\stock\
├── app\
│   ├── main.py              FastAPI 進入點，掛載 API 與靜態頁
│   ├── config.py            路徑、API URL、節流秒數等設定
│   ├── db.py                SQLite 連線與 schema 建立
│   ├── fetchers\
│   │   ├── twse.py          上市：T86、STOCK_DAY_ALL、t187ap03_L
│   │   └── tpex.py          上櫃：三大法人、行情、mopsfin_t187ap03_O
│   ├── services\
│   │   ├── ingest.py        單日匯入流程 (抓取 → 清洗 → 寫入)
│   │   └── aggregate.py     類股聚合計算
│   ├── api\
│   │   └── routes.py        REST API
│   └── static\
│       ├── index.html
│       ├── app.js
│       └── style.css
├── scripts\
│   ├── init_db.py           建表 + 匯入產業別對照
│   ├── backfill.py          歷史回補 (指定日期區間)
│   └── daily_job.py         每日排程進入點
├── data\
│   └── stock.db
├── requirements.txt
├── PLAN.md
└── README.md
```

---

## 三、資料表設計

| 資料表 | 用途 | 主要欄位 |
|--------|------|----------|
| `industry` | 產業別代碼對照 | market, code, name |
| `stock_info` | 個股主檔 | code, name, market, industry_code, is_etf, updated_at |
| `daily_price` | 每日收盤 | date, code, close, volume, turnover |
| `inst_trade` | 個股三大法人買賣超 | date, code, foreign_net, trust_net, dealer_self_net, dealer_hedge_net, total_net (股數) + 各自換算金額 |
| `industry_daily` | 類股聚合結果 | date, market, industry_code, foreign_amt, trust_amt, dealer_amt, total_amt, buy_count, sell_count |
| `ingest_log` | 匯入狀態 | date, market, status, row_count, error_msg |

`industry_daily` 為預先算好的聚合表，前端查詢不需即時 group by；資料重跑時整批覆蓋該日。

---

## 四、資料處理流程

```
daily_job.py (交易日 15:30 後執行)
  │
  ├─ 1. 確認該日是否為交易日 (先打 T86，stat != "OK" 就跳過)
  ├─ 2. 上市：T86 買賣超股數 + STOCK_DAY_ALL 收盤價
  ├─ 3. 上櫃：tpex_3insti_daily_trading + 上櫃行情
  ├─ 4. 清洗：去除千分位逗號、全形空白、股名尾端空白
  ├─ 5. 換算金額 = 買賣超股數 × 當日收盤價
  ├─ 6. join stock_info 取得產業別，ETF 歸入「ETF」虛擬類別
  ├─ 7. 寫入 inst_trade / daily_price
  └─ 8. 重算該日 industry_daily
```

`stock_info` 與 `industry` 每週更新一次即可（新上市、產業重分類），不必每日抓取。

---

## 五、API 設計

| 端點 | 說明 |
|------|------|
| `GET /api/dates` | 可查詢的日期清單（前端日期選單用） |
| `GET /api/industries/flow?date=&investor=` | 當日各類股資金流向，`investor` 可選 all / foreign / trust / dealer |
| `GET /api/industries/{code}/history?days=20` | 單一類股近 N 日資金流向 |
| `GET /api/industries/{code}/stocks?date=` | 該類股當日個股買賣超明細 |
| `GET /api/stocks/ranking?date=&investor=&side=&limit=50` | 個股買超 / 賣超排行 |
| `GET /api/industries/streak?days=5` | 連續買超天數排行 |

---

## 六、前端頁面（單頁 + ECharts，CDN 引入）

1. **類股熱力圖 (treemap)**：面積 = 買賣超金額絕對值，顏色 = 紅買 / 綠賣（台股習慣），可切換外資 / 投信 / 自營 / 合計
2. **類股資金流向排行**：橫向柱狀圖，一眼看出當日資金最集中的前 10 類股
3. **點擊類股**：下方展開該類股個股明細表與近 20 日趨勢線
4. **個股排行表**：當日買超 / 賣超前 50 名，可切換法人別
5. **連續買超榜**：找出法人持續加碼的族群

日期選單預設當日，可回看歷史。

---

## 七、實作階段

| 階段 | 內容 | 產出 |
|------|------|------|
| 一 | 建表、產業別對照、fetcher、單日匯入 | 能成功匯入一天的完整資料 |
| 二 | 回補近一個月 + 聚合計算 | DB 有約 20 個交易日資料 |
| 三 | FastAPI 端點 | 可用 curl 或瀏覽器驗證 JSON |
| 四 | 前端頁面 | 網站可用 |
| 五 | 排程 + README | Windows 工作排程器每日自動更新 |

---

## 八、已知風險與處理方式

| 風險 | 處理 |
|------|------|
| **金額為估算值** | 官方個股資料只給股數，金額以收盤價推算，與券商實際數字會有落差。頁面明確標示「估算」 |
| ETF 混入類股 | `00xxx`、`00400A` 這類無產業別，獨立歸為「ETF」不併入類股統計 |
| TPEx 欄位名稱髒 | 實測欄位 key 有多餘空白與命名不一致（如 `" Foreign Investors...-Total Sell"`），以正規化後的 key 對應並加防呆 |
| 產業別代碼對照 | 不憑印象硬寫，第一步從 API 實際資料抽出所有出現過的代碼，逐一比對官方分類後建表 |
| TWSE 節流 | 回補時每次請求間隔 3 秒，避免被擋 |
| 非交易日 | 以 T86 回應的 `stat` 判斷，非交易日直接跳過並記錄 |
| 重複執行 | 以 `(date, code)` 為主鍵 upsert，`ingest_log` 記錄狀態，可安全重跑 |

---

## 九、後續可擴充方向（不在第一版範圍）

- 資料回補延長至一年以上，做長期類股輪動分析
- 加入融資融券、借券賣出資料交叉比對
- 類股資金流向與類股指數漲跌的相關性分析
- 部署到雲端 (Zeabur / Render) 並改用 PostgreSQL

---

## 十、實作進度

| 階段 | 狀態 | 完成內容 |
|------|------|----------|
| 一 建表與單日匯入 | 完成 | 五張資料表、三個 fetcher、匯入流程，估算金額與官方數字誤差 1.4% |
| 二 歷史回補與聚合 | 完成 | 回補 2026-08-10 ~ 2026-09-10，共 24 個交易日、52370 筆個股資料 |
| 三 REST API | 完成 | 六個端點，含資料完整性標示 |
| 四 前端頁面 | 完成 | Treemap、排行圖、趨勢圖與四張資料表，支援法人別切換與色盲友善配色 |
| 五 排程與文件 | 完成 | daily_job.py 與 README（含 Windows 工作排程器設定） |

### 實作過程中發現、原計畫未預期的問題

1. **櫃買中心 openapi 只有最新一日資料**，歷史回補改用可帶日期的 `zh-tw` 端點；
   上市的 `STOCK_DAY_ALL` 同樣只有當日，歷史收盤價改用 `MI_INDEX`
2. **櫃買中心 TLS 憑證缺少 Subject Key Identifier**，Python 3.13 預設的嚴格
   X509 檢查會拒絕連線，需自訂 SSLContext 關閉該項檢查（保留憑證鏈驗證）
3. **產業別改用 ISIN 對照表**：原計畫用數字代碼再自建中文對照，實際發現 ISIN
   對照表直接提供中文產業名稱，且上市與上櫃共用同一套分類，省去自建對照表
4. **需要以 CFI Code 過濾證券類型**：ISIN 表含大量權證（上市 34066 筆），
   僅收錄普通股、特別股、DR、ETF、ETN；特別股沿用母股產業別
5. **當日資料可能只有單一市場**：上市 16:00 才公布、上櫃 15:30，
   因此在 `ingest_log` 記錄各市場狀態，API 回傳完整性標示，
   前端標註「僅上櫃」並預設選擇最新一個完整交易日

---

## 十一、第一版之後的調整

以下為五個階段完成後，依實際使用回饋所做的變更（2026-09-10 ~ 09-11）。

### 功能調整

| 項目 | 內容 |
|------|------|
| 個股下鑽檢視 | 點擊類股後，treemap 與排行圖切換為該類股的個股資金分布與買賣超排名（第 1 名到最後一名），右上角按鈕返回全類股 |
| 類股內顯示個股 | 類股區塊改為階層式 Treemap，內部依同方向個股的佔比切分面積 |
| 切分檔數分級 | 資金規模前 6 大的類股切 10 檔、第 7 至 14 大切 5 檔，避免小區塊被切到只剩數字片段 |
| 「其他」格規則 | 面積最多佔類股區塊 10%、固定排在右下角、配色與同類股個股一致（買超紅、賣超綠） |
| 連續買賣超排序 | 改為依期間累計金額的絕對值由大到小 |
| 資料完整性標示 | 日期選單標註「僅上櫃」，預設選擇最新一個兩市場都齊全的交易日 |

### 技術問題與解法

1. **ECharts 5.5.1 的 treemap `upperLabel` 在兩層資料下不生效**
   調整 `levels` 索引與 `leafDepth` 均無效，導致類股名稱完全消失。
   最終改為讀取各節點的版面座標（`node.getLayout()`），以 HTML 疊加層
   繪製類股標題於區塊上緣，個股標籤同步下移相同高度避免被遮擋。

2. **treemap 的自動排序無法指定「其他」的位置**
   關閉自動排序（`sort: null`），改由傳入的資料順序決定版面：
   類股層與個股層都先依金額絕對值排序，「其他」固定放在最後，
   因而落在右下角。排行圖則另外依買賣超金額排序，兩者互不影響。

3. **修改前端後瀏覽器仍載入舊快取**
   首頁改由 FastAPI 動態產生，將 CSS 與 JS 的網址加上以檔案更新時間
   產生的版本參數；同時對 `/` 與 `/static/` 回應加上 `Cache-Control: no-store`。

4. **「其他」的檔數欄位新增後未重啟伺服器，導致整格消失**
   前端在取不到檔數時會靜默丟棄該格。已改為只要有剩餘項目就保留格子，
   檔數取不到時顯示為「其他」。

### 面積語意的取捨

類股區塊面積為買賣超淨額（買賣相抵後的結果），內部個股格子的面積則是
該個股在類股內的相對佔比，因此個股金額加總可能大於類股淨額。
「其他」超過 10% 時會被壓縮，此時 tooltip 會註明「格子面積上限 10%，
實際佔比更高」，避免誤讀為等比例。

### 版本控制

專案已推送至 GitHub：<https://github.com/cs1dada/tw-institutional-flow>

`data/stock.db` 不納入版本控制，clone 後執行 `python scripts/init_db.py`
與 `python scripts/backfill.py` 即可自行建立資料。
