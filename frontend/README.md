# 前端 (Vue 3 + TypeScript)

原本的前端是單一 `app.js` (約 2400 行原生 JavaScript)，位於 `app/static/`。
這個目錄是遷移到 Vue 的新版，兩者在遷移期間並存：舊版仍是正式運作的版本，
新版逐頁搬移，每搬完一頁就對照舊版確認輸出一致。

## 遷移進度

四個頁面都已搬完，每一頁都以相同流程分別抓取新舊兩版的畫面輸出並逐項比對：

| 頁面 | 比對項目 | 結果 |
|------|----------|------|
| 大盤指數 K 線 | 30 項 (3 種週期) | 全部一致 |
| 類股資金流向 | 34 項 (2 種法人別) | 全部一致 |
| 主動式 ETF | 33 項 | 全部一致 |
| 盤中觀察 | 入口隱藏與錯誤處理 | 正常 |

盤中觀察預設為關閉 (後端的 `INTRADAY_ENABLED`)，關閉時側邊欄不顯示入口。

舊版尚未移除，切換正式部署前仍可隨時對照。

## 開發

需要同時啟動後端與前端：

```bash
# 終端機 1：後端 API (專案根目錄)
python -m uvicorn app.main:app --port 8000

# 終端機 2：前端 (本目錄)
npm install
npm run dev
```

瀏覽器開啟 <http://localhost:5173>。Vite 會把 `/api` 轉發到 8000，
因此前端看到的資料與舊版完全相同。

## 建置

```bash
npm run build      # 型別檢查 + 打包，輸出到 ../dist
npm run typecheck  # 只做型別檢查
```

`vite.config.ts` 的 `base` 設為 `/tw-institutional-flow/`，
因為 GitHub Pages 的網址含 repo 名稱，資源用絕對路徑會少一層而失效。

## 雙模式

沿用舊版的設計：同一套前端邏輯，只有資料來源不同。

| 模式 | 觸發方式 | 資料來源 |
|------|----------|----------|
| `api` | `npm run dev` (`.env.development`) | FastAPI 的 `/api/*` |
| `static` | `npm run build` (`.env.production`) | 預先匯出的 `data/*.json` |

模式由 `index.html` 注入 `window.APP_MODE`，實際判斷在 `src/api/dataSource.ts`。

## 目錄

```
src/
  api/dataSource.ts     雙模式資料來源與快取
  types/index.ts        後端回傳的資料結構
  utils/
    format.ts           日期與金額格式化
    theme.ts            從 CSS 變數讀出圖表用的色彩
    echarts.ts          ECharts 按需引入 (沒有這個圖表會是空白)
    indexBars.ts        指數 K 棒的聚合與計算，全部是純函式
  components/SideNav.vue
  views/
    IndexChartView.vue  大盤指數 K 線
    PendingView.vue     尚未遷移的頁面
```

`src/styles/style.css` 目前是從 `app/static/style.css` 複製而來，
遷移完成後舊版移除，這份成為唯一來源。

## 路由

使用 hash 模式 (`#/index`)。GitHub Pages 只會送檔案，
history 模式直接開啟 `/etf` 這類路徑會得到 404。
