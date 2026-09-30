# 資料表說明

資料庫為 SQLite，檔案位於 `data/stock.db`，結構定義在 `app/db.py` 的 `SCHEMA`。

用 DBeaver 之類的工具連線時，選 SQLite 驅動並指向該檔案即可，沒有帳號密碼。
資料庫使用 WAL 模式，`data/` 下的 `stock.db-wal` 與 `stock.db-shm` 是同一組檔案，
複製或備份時要三個一起帶走。

---

## 共通約定

| 項目 | 約定 |
|------|------|
| 日期 | 一律為 `YYYYMMDD` 的**文字**格式（例：`20260917`），不是 date 型別，可直接用字串比較與排序 |
| 市場別 | `TWSE` 為上市、`TPEX` 為上櫃 |
| 股數 | 交易所原始資料的單位是**股**，不是張（1 張 = 1000 股） |
| 金額 | 資料庫一律存**元**，換算成億元由前端處理 |
| 買賣超 | 正值為買超、負值為賣超 |

---

## stock_info — 個股主檔

代號、名稱、市場別與產業別的對照表。類股分類、ETF 判斷都以這張表為準。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `code` | TEXT | 股票代號，主鍵 |
| `name` | TEXT | 股票名稱 |
| `market` | TEXT | `TWSE` 或 `TPEX` |
| `industry` | TEXT | 產業別（中文），無法分類者為「未分類」 |
| `is_etf` | INTEGER | 1 表示 ETF。ETF 在類股頁會歸入虛擬類別「ETF」，不混進一般產業 |
| `updated_at` | TEXT | 這筆資料的更新時間 |

**來源**：證交所 ISIN 對照表（`isin.twse.com.tw`），由 `scripts/init_db.py` 寫入。
產業別只有這份對照表有，因此每週更新一次即可。

**索引**：`idx_stock_info_industry (industry)`

---

## daily_price — 每日收盤行情

個股的開高低收與成交量值，是**個股 K 線圖的資料來源**。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | TEXT | 交易日，與 `code` 合為主鍵 |
| `code` | TEXT | 股票代號 |
| `open` | REAL | 開盤價 |
| `high` | REAL | 最高價 |
| `low` | REAL | 最低價 |
| `close` | REAL | 收盤價 |
| `volume` | INTEGER | 成交股數（不是張數） |
| `turnover` | INTEGER | 成交金額（元） |

**來源**：證交所 `MI_INDEX` 與櫃買 `otc` 的每日收盤行情。

`open` / `high` / `low` 是後來才加入的欄位（`app/db.py` 的 `MIGRATIONS`）。
兩家交易所的回應本來就含這三欄，只是早期沒有解析。既有資料需要跑一次
`scripts/backfill_ohlc.py` 補齊，之後每天的 `scripts/ingest_day.py` 會自動帶入。

查詢 K 線時要濾掉開高低為 NULL 的列，那是補齊之前的舊資料，畫不出 K 棒。

---

## inst_trade — 個股三大法人買賣超

這個專案的核心資料，類股資金流向就是由它聚合而來。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | TEXT | 交易日，與 `code` 合為主鍵 |
| `code` | TEXT | 股票代號 |
| `market` | TEXT | `TWSE` 或 `TPEX` |
| `foreign_net` | INTEGER | 外資買賣超**股數**（含外資自營商） |
| `trust_net` | INTEGER | 投信買賣超股數 |
| `dealer_self_net` | INTEGER | 自營商（自行買賣）股數 |
| `dealer_hedge_net` | INTEGER | 自營商（避險）股數 |
| `dealer_net` | INTEGER | 自營商合計 = 自行買賣 + 避險 |
| `total_net` | INTEGER | 三大法人合計股數 |
| `close` | REAL | 當日收盤價，估算金額用 |
| `foreign_amt` | REAL | 外資買賣超**金額**（元） |
| `trust_amt` | REAL | 投信買賣超金額 |
| `dealer_amt` | REAL | 自營商買賣超金額 |
| `total_amt` | REAL | 三大法人買賣超金額 |

**來源**：證交所 `T86` 與櫃買 `dailyTrade`。

**金額是估算值**。交易所只公布買賣超股數，不公布成交均價，因此金額一律以
`股數 × 當日收盤價` 推估。法人不可能全部以收盤價成交，所以這個數字與真實金額
有落差，用於比較規模大小仍然成立，但不該當成精確金額引用。

以 2026-09-17 的台積電為例：外資買超 4,794,190 股、收盤 2425 元，
`foreign_amt` 就是 4,794,190 × 2425 = 116.26 億。

**索引**：`idx_inst_trade_date (date)`

---

## industry_daily — 類股每日資金流向

由 `inst_trade` 依 `stock_info.industry` 聚合而成的衍生資料，不是原始資料。
重跑匯入會整批重算。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | TEXT | 交易日，與 `industry` 合為主鍵 |
| `industry` | TEXT | 產業別 |
| `foreign_amt` | REAL | 該類股的外資買賣超金額合計（元） |
| `trust_amt` | REAL | 投信合計 |
| `dealer_amt` | REAL | 自營商合計 |
| `total_amt` | REAL | 三大法人合計 |
| `buy_count` | INTEGER | 該類股中三大法人買超的家數 |
| `sell_count` | INTEGER | 賣超家數 |
| `stock_count` | INTEGER | 該類股有資料的總家數 |

`buy_count` + `sell_count` 不一定等於 `stock_count` —— 買賣超為零的個股兩邊都不算。

**索引**：`idx_industry_daily_date (date)`

---

## index_daily — 大盤指數日線

供大盤指數 K 線圖使用。目前只存發行量加權股價指數（`index_code` 為 `TAIEX`）。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | TEXT | 交易日，與 `index_code` 合為主鍵 |
| `index_code` | TEXT | 指數代碼，目前只有 `TAIEX` |
| `open` | REAL | 開盤指數 |
| `high` | REAL | 最高指數 |
| `low` | REAL | 最低指數 |
| `close` | REAL | 收盤指數 |
| `volume` | INTEGER | 全市場成交股數 |
| `turnover` | INTEGER | 全市場成交金額（元） |
| `change` | REAL | 漲跌**點數** |

**來源**：證交所 `MI_5MINS_HIST`（開高低收）與 `FMTQIK`（成交量值），
兩支都是**以月為單位**回傳，因此 `scripts/ingest_index.py` 是按月抓取。

週線與月線不存在資料庫裡，由前端從日線聚合（見 `frontend/src/utils/indexBars.ts`）。

**索引**：`idx_index_daily_code (index_code, date)`

---

## etf_holding — 主動式 ETF 持股明細

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | TEXT | 淨值日，與 `etf_code`、`stock_code` 合為主鍵 |
| `etf_code` | TEXT | ETF 代號（主動式 ETF 的規則是 00 開頭、A 結尾） |
| `stock_code` | TEXT | 持股的股票代號 |
| `stock_name` | TEXT | 持股名稱（取自投信官網，未必與 `stock_info` 完全一致） |
| `shares` | INTEGER | 持有股數 |
| `weight` | REAL | 佔淨值比重（%） |

**來源**：各投信官網，由 `scripts/ingest_etf.py` 抓取。

**只能從開始抓取之日累積**。投信官網只提供當日持股，沒有歷史查詢，
錯過的日期無法回補，這是這張表與其他表最大的差別。
日期以投信的**淨值日**為準，可能落後交易日一到兩天。

**索引**：`idx_etf_holding_date (date)`、`idx_etf_holding_stock (stock_code)`

---

## etf_snapshot — 主動式 ETF 每日規模

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | TEXT | 淨值日，與 `etf_code` 合為主鍵 |
| `etf_code` | TEXT | ETF 代號 |
| `issuer` | TEXT | 投信代碼（例：`nomura`、`cathay`） |
| `nav` | REAL | 每單位淨值（元） |
| `aum` | REAL | 基金規模（元） |
| `units` | INTEGER | 流通單位數 |
| `holding_count` | INTEGER | 該日成功取得的持股檔數 |
| `updated_at` | TEXT | 抓取時間 |

`holding_count` 兼作抓取狀態：為 0 代表那天的持股沒抓到，
`etf_holding` 裡不會有對應的資料。

---

## future_daily — 期貨每日行情

期貨的開高低收，供期貨 K 線圖使用。個股在 `daily_price`，期貨在這裡，兩者分開。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | TEXT | 交易日 |
| `commodity` | TEXT | 商品代碼：`TMF` 微型臺指、`TX` 臺股期貨、`MTX` 小型臺指 |
| `contract_month` | TEXT | 到期月份，例如 `202610` |
| `session` | TEXT | `regular` 日盤、`afterhours` 盤後盤（夜盤） |
| `open` `high` `low` `close` | REAL | 開高低收 |
| `settlement` | REAL | 結算價，盤後時段沒有 |
| `volume` | INTEGER | 成交**口數**（不是股數，也沒有成交金額） |
| `open_interest` | INTEGER | 未沖銷契約數，盤後時段沒有 |

主鍵為 `(date, commodity, contract_month, session)`。

**來源**：期交所「每日交易行情下載」（`taifex.com.tw/cht/3/futDataDown`），
免費、不需認證。單次查詢**最多一個月**（實測 31 天可過、62 天會回「日期時間錯誤」），
因此 `scripts/backfill_futures.py` 是按月推進，回補三年只要 36 個請求。

三件解析上要注意的事：

1. **價差契約要排除**。到期月份出現 `202609/202610` 這種是 calendar spread，
   報的是兩個月份的價差，混進 K 線會完全失真。
2. **日盤與夜盤要分開**。夜盤（`afterhours`）是另一段行情，與日盤混在一起 K 棒會錯。
3. **近月不必推算結算日**。已結算的契約不會再出現在當日資料裡，
   同一天取 `MIN(contract_month)` 就是近月。

商品的歷史長度取決於上市日，例如微型臺指期貨是 2024-07-29 才上市，
再怎麼回補也不會有更早的資料。

查近月日 K：

```sql
SELECT date, contract_month, open, high, low, close, volume, open_interest
FROM future_daily f
WHERE commodity = 'TMF' AND session = 'regular'
  AND contract_month = (
      SELECT MIN(contract_month) FROM future_daily
      WHERE date = f.date AND commodity = f.commodity AND session = 'regular'
  )
ORDER BY date DESC
LIMIT 60;
```

**索引**：`idx_future_daily_lookup (commodity, session, date, contract_month)`

---

## ingest_log — 每日匯入狀態

記錄哪一天、哪個市場已經匯入過，`scripts/backfill.py` 以此判斷要不要略過。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | TEXT | 交易日，與 `market` 合為主鍵 |
| `market` | TEXT | `TWSE` 或 `TPEX` |
| `status` | TEXT | `ok`（有資料）、`no_data`（非交易日）、`error`（失敗） |
| `row_count` | INTEGER | 匯入筆數 |
| `message` | TEXT | 錯誤訊息，成功時為空 |
| `updated_at` | TEXT | 匯入時間 |

一個交易日要兩市場都是 `ok` 或 `no_data` 才算完成，因此 `backfill.py` 的判斷是
`GROUP BY date HAVING COUNT(*) = 2`。

`scripts/backfill_ohlc.py` **不寫這張表** —— 它只補開高低，與法人資料的匯入狀態無關。

---

## 資料涵蓋範圍的差異

各表的起始日期不同，查詢時要留意：

| 資料表 | 涵蓋範圍取決於 |
|--------|----------------|
| `daily_price` | `backfill_ohlc.py` 回補了多久（開高低更是只有補過的日期才有） |
| `inst_trade`、`industry_daily` | `backfill.py` 回補了多久 |
| `index_daily` | `ingest_index.py` 回補了幾個月 |
| `future_daily` | `backfill_futures.py` 回補了多久，以及該商品的上市日 |
| `etf_holding`、`etf_snapshot` | 開始每日抓取的那天，無法回補 |

要查目前的實際範圍：

```sql
SELECT 'daily_price' AS t, MIN(date), MAX(date), COUNT(*) FROM daily_price
UNION ALL SELECT 'inst_trade', MIN(date), MAX(date), COUNT(*) FROM inst_trade
UNION ALL SELECT 'index_daily', MIN(date), MAX(date), COUNT(*) FROM index_daily
UNION ALL SELECT 'etf_holding', MIN(date), MAX(date), COUNT(*) FROM etf_holding;
```

只看開高低補到哪裡：

```sql
SELECT MIN(date), MAX(date), COUNT(DISTINCT date)
FROM daily_price WHERE open IS NOT NULL;
```

---

## 常用查詢

**某檔個股的日 K**

```sql
SELECT date, open, high, low, close, turnover / 1e8 AS turnover_yi
FROM daily_price
WHERE code = '2330' AND open IS NOT NULL
ORDER BY date DESC
LIMIT 60;
```

**某日的類股資金流向排行**

```sql
SELECT industry, total_amt / 1e8 AS amt_yi, buy_count, sell_count, stock_count
FROM industry_daily
WHERE date = '20260917'
ORDER BY total_amt DESC;
```

**某日外資買超前二十名**

```sql
SELECT t.code, s.name, s.industry,
       t.foreign_net / 1000 AS lots, t.foreign_amt / 1e8 AS amt_yi, t.close
FROM inst_trade t
JOIN stock_info s ON s.code = t.code
WHERE t.date = '20260917'
ORDER BY t.foreign_amt DESC
LIMIT 20;
```

**某檔個股近期的法人連續買賣超**

```sql
SELECT date, total_net / 1000 AS lots, total_amt / 1e8 AS amt_yi, close
FROM inst_trade
WHERE code = '2330'
ORDER BY date DESC
LIMIT 20;
```

**主動式 ETF 的最新前十大持股**

```sql
SELECT h.etf_code, h.stock_code, h.stock_name, h.shares, h.weight
FROM etf_holding h
WHERE h.date = (SELECT MAX(date) FROM etf_holding)
  AND h.etf_code = '00999A'
ORDER BY h.weight DESC
LIMIT 10;
```
