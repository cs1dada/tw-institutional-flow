# 使用者追蹤、登入與收費規劃

記錄日期：2026-11-17

## 目標

1. 先知道網站的流量，以及是誰在看
2. 之後可能收費

## 現況限制

- 網站部署在 GitHub Pages (<https://cs1dada.github.io/tw-institutional-flow/>)，是純靜態站，沒有後端
- GitHub repo 為公開 (PUBLIC)
- 資料檔 `docs/data/*.json` 任何人都能直接以網址下載，也能在 repo 看到
- 因此只在前端加登入，只能記錄「誰來過」，無法真的擋住未登入者

## 分三個階段進行

每個階段都能沿用到下一個階段，不需要打掉重做。

### 第一階段：流量統計 (不需登入)

- 採用 Google Analytics 4 (GA4)，免費，在 `index.html` 加入 script 即可，GitHub Pages 照常使用
- 可看到各分頁瀏覽數、停留時間、來源、裝置，作為日後判斷哪些功能值得收費的依據
- 前端已從 hash 路由 (`#/index`) 改為一般網址 (`/index`)，GA 可直接讀到實際頁面，
  切換分頁由 GA 加強型評估的「根據瀏覽記錄事件進行網頁變更」自動記錄 (請保持開啟)
- 只在 `cs1dada.github.io` 啟用，本機開發與 FastAPI 版不送資料
- 備選：Cloudflare Web Analytics (同樣免費，不使用 cookie)

**待辦**

- [x] 自行建立 GA4 帳號與資源，評估 ID 為 `G-4B6209S0EB`
- [x] 前端接上 GA4 (`frontend/src/utils/analytics.ts`)
- [ ] 部署上線，到 GA「報表 > 即時」確認有資料

### 第二階段：Google 登入，知道是誰在看

- 採用 Supabase (免費方案)
  - 內建 Google 登入，前端加一個登入按鈕即可
  - 內建 Postgres 資料庫，記錄使用者 (email、首次登入時間、最後登入時間、登入次數)，可在 Supabase 後台查看
  - 日後收費時在同一張表加上訂閱狀態欄位即可，不需換系統
- 傾向「選擇性登入」：大部分內容不登入也能看，登入後才有額外功能 (例如自選股、通知)
  - 強制登入會讓流量下降
  - 選擇性登入有利於累積流量，也方便日後區分免費與付費內容

**待辦**

- [ ] 決定強制登入或選擇性登入
- [ ] 自行註冊 Supabase 並建立專案
- [ ] 在 Google Cloud Console 建立 OAuth client ID
- [ ] 前端加入登入按鈕，登入時寫入使用者紀錄

### 第三階段：收費 (資料真正受保護)

- 付費功能的資料不再放 `docs/data/`，改放 Supabase Storage 或資料庫，以權限規則 (RLS) 限制只有付費會員能讀取
- 免費部分可繼續留在 GitHub Pages
- 金流候選：綠界、Stripe
- 視情況將 repo 改為私有，避免資料從 GitHub 取得

## 其他評估過的方案

| 方案 | 能看到誰登入 | 真的擋住未登入者 | 備註 |
|------|-------------|----------------|------|
| 前端 Google 登入加記錄 (Apps Script 寫入 Google Sheet) | 可以 | 不行 | 最簡單，但無法延伸到收費 |
| Cloudflare Pages 加 Cloudflare Access | 可以 (後台有登入紀錄) | 可以，整站連資料檔都擋 | 50 人內免費，需換部署目標與網址；適合固定名單，不適合對外收費 |
| Firebase Hosting 加 Firebase Auth | 可以 | 部分 (資料需改放 Firestore) | 改動最大 |

## 尚未決定

- 本機 FastAPI 版 (`localhost:8000`) 是否也需要登入，或只處理線上版
- 第二階段要強制登入還是選擇性登入
