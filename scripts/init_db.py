"""初始化資料庫：建立資料表並抓取個股主檔與產業別。"""
import _bootstrap

_bootstrap.setup_logging()

from app.db import init_schema
from app.services.ingest import update_stock_info


def main():
    init_schema()
    print("資料表建立完成")
    total = update_stock_info()
    print(f"個股主檔更新完成，共 {total} 檔")


if __name__ == "__main__":
    main()
