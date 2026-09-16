"""匯出靜態網站到 docs/，供 GitHub Pages 託管。

資料來源仍是 data/stock.db，本腳本只是把查詢結果預先算好存成 JSON，
讓沒有伺服器的 GitHub Pages 也能呈現同樣的內容。
與後端 API 呼叫同一組 dataset 函式，因此兩種模式的資料格式一致。

用法：
    python scripts/export_static.py
    python scripts/export_static.py 30      # 只匯出最近 30 個交易日
"""
import json
import shutil
import sys

import _bootstrap

_bootstrap.setup_logging()

from app import config
from app.db import connect
from app.services import dataset

DOCS_DIR = config.BASE_DIR / "docs"
DATA_DIR = DOCS_DIR / "data"
# 預設匯出的交易日數，避免 repo 無限膨脹
DEFAULT_DAYS = 60
# 需要一併複製到 docs 的前端檔案
ASSETS = ["app.js", "style.css"]


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    return path.stat().st_size


def asset_version():
    files = [config.STATIC_DIR / name for name in ASSETS]
    return str(int(max(path.stat().st_mtime for path in files)))


def export_page():
    """把 index.html 轉為靜態版：相對路徑、寫死版本號與模式。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{v}}", asset_version())
    html = html.replace("{{mode}}", "static")
    # GitHub Pages 的網址含 repo 名稱，絕對路徑會少一層而失效
    html = html.replace('href="/static/', 'href="')
    html = html.replace('src="/static/', 'src="')
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8", newline="\n")

    for name in ASSETS:
        shutil.copyfile(config.STATIC_DIR / name, DOCS_DIR / name)
    vendor_src = config.STATIC_DIR / "vendor"
    vendor_dst = DOCS_DIR / "vendor"
    vendor_dst.mkdir(parents=True, exist_ok=True)
    for path in vendor_src.iterdir():
        if path.is_file():
            shutil.copyfile(path, vendor_dst / path.name)

    # 關閉 GitHub Pages 的 Jekyll 處理，純粹當作檔案託管
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")


def check_not_shrinking(target_dates, force):
    """避免以較少的資料覆蓋既有輸出。

    線上資料由 GitHub Actions 維護，其資料庫與本機各自獨立且通常較完整。
    若在本機匯出後推送，會讓線上的交易日數倒退，且不易察覺。
    """
    existing = sorted(path.stem for path in (DATA_DIR / "day").glob("*.json"))
    if not existing or len(target_dates) >= len(existing):
        return True
    print(f"既有輸出有 {len(existing)} 個交易日（{existing[0]} ~ {existing[-1]}），")
    print(f"本次只會產生 {len(target_dates)} 個（{target_dates[-1]} ~ {target_dates[0]}）。")
    print()
    print("線上資料由 GitHub Actions 維護，其資料庫通常比本機完整。")
    print("若這是刻意為之，請加上 --force 再執行：")
    print("    python scripts/export_static.py --force")
    if force:
        print()
        print("已指定 --force，繼續覆蓋。")
        return True
    return False


def main():
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    days = int(args[0]) if args else DEFAULT_DAYS
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    conn = connect()
    try:
        meta = dataset.build_meta(conn)
        target_dates = [item["date"] for item in meta["dates"][:days]]
        # meta 只保留實際匯出的日期，避免前端選到沒有檔案的日子
        meta["dates"] = [item for item in meta["dates"] if item["date"] in set(target_dates)]
        meta["exported_days"] = len(target_dates)

        if not check_not_shrinking(target_dates, force):
            return

        total = write_json(DATA_DIR / "meta.json", meta)
        print(f"meta.json  {total / 1024:.1f} KB")

        day_bytes = 0
        for date_str in target_dates:
            payload = dataset.build_day(conn, date_str)
            if payload is None:
                continue
            day_bytes += write_json(DATA_DIR / "day" / f"{date_str}.json", payload)
        print(f"day/*.json  {len(target_dates)} 檔，共 {day_bytes / 1024 / 1024:.2f} MB")

        size = write_json(DATA_DIR / "history.json", dataset.build_history(conn))
        print(f"history.json  {size / 1024:.1f} KB")

        size = write_json(DATA_DIR / "etf.json", dataset.build_etf(conn))
        print(f"etf.json  {size / 1024:.1f} KB")

        size = write_json(DATA_DIR / "index.json", dataset.build_index(conn))
        print(f"index.json  {size / 1024:.1f} KB")
    finally:
        conn.close()

    export_page()
    print(f"靜態網站已輸出至 {DOCS_DIR}")


if __name__ == "__main__":
    main()
