"""把前端的建置產物複製到 docs/，供 GitHub Pages 託管。

職責切分：

    npm run build (frontend)  ->  dist/      前端的「殼」
    scripts/deploy_web.py     ->  docs/      把殼放進去
    scripts/export_static.py  ->  docs/data/ 每日更新的資料

殼只有在改動前端程式碼時才需要重跑，因此 GitHub Actions 的每日更新
只會執行 export_static.py，不需要 Node.js。

用法：
    cd frontend && npm run build
    python scripts/deploy_web.py
"""
import shutil
import sys

import _bootstrap

_bootstrap.setup_logging()

from app import config

DIST_DIR = config.BASE_DIR / "dist"
DOCS_DIR = config.BASE_DIR / "docs"

# 這些是 docs/ 裡不屬於前端建置產物的東西，不可刪除
KEEP = {"data", ".nojekyll"}
KEEP_SUFFIXES = {".png"}


def keep(path):
    """README 使用的截圖與資料目錄要保留。

    PWA 的圖示同樣是 .png，但它們每次都會從 dist/ 重新複製過來，
    因此保留與否都不影響結果。
    """
    if path.name in KEEP:
        return True
    return path.suffix.lower() in KEEP_SUFFIXES and path.is_file()


def clean_shell():
    """移除上一版的殼，避免帶 hash 的舊 assets 無限累積。"""
    removed = 0
    for path in DOCS_DIR.iterdir():
        if keep(path):
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed += 1
    return removed


def copy_shell():
    copied = 0
    for src in DIST_DIR.rglob("*"):
        if src.is_dir():
            continue
        dst = DOCS_DIR / src.relative_to(DIST_DIR)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied += 1
    return copied


def main():
    if not DIST_DIR.exists():
        print("找不到 dist/，請先在 frontend 目錄執行 npm run build", file=sys.stderr)
        sys.exit(1)

    index = DIST_DIR / "index.html"
    if not index.exists():
        print("dist/ 內沒有 index.html，建置可能未完成", file=sys.stderr)
        sys.exit(1)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    removed = clean_shell()
    copied = copy_shell()

    # GitHub Pages 預設會用 Jekyll 處理，底線開頭的檔案會被忽略
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    data_dir = DOCS_DIR / "data"
    data_count = len(list(data_dir.rglob("*.json"))) if data_dir.exists() else 0

    print(f"移除舊的殼 {removed} 項，複製 {copied} 個檔案到 {DOCS_DIR}")
    print(f"資料檔保留 {data_count} 個")
    if not data_count:
        print("docs/data 目前是空的，請執行 python scripts/export_static.py")


main()
