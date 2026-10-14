"""股票題材分類。

分類表 data/themes.json 由人工維護，分成三層：題材 → 環節 → 個股。
一檔股票可以出現在多個題材或環節，每次出現各自標註關聯度：

- high：主要營收來自這個環節
- mid：有相當比重，但不是唯一主力
- low：沾得上邊，比重小或仍在起步

輸出分成兩份，分類結構只有一份，數字依日期各一份，切換日期時只需下載當日的小檔：

- 結構：分類表、個股名稱與證交所產業別、可選的揭露日
- 當日數字：收盤、漲跌幅、被幾檔主動式 ETF 持有，以及 ETF 有持有、但分類表還沒收錄的個股

本機 API 與靜態匯出共用這裡的函式，兩種模式的格式一致。
"""
import json

from app import config
from app.services.etf_cost import domestic_etfs

THEMES_PATH = config.DATA_DIR / "themes.json"


def load_themes():
    with open(THEMES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _classified_codes(themes):
    return {s["code"] for theme in themes["themes"] for seg in theme["segments"] for s in seg["stocks"]}


def _stock_info(conn):
    return {r["code"]: (r["name"], r["industry"]) for r in conn.execute("SELECT code, name, industry FROM stock_info")}


class _Context:
    """一次載入以台股為主的 ETF 與揭露日，逐日計算時共用。"""

    def __init__(self, conn):
        self.conn = conn
        self.etfs = domestic_etfs(conn)
        self.marks = ",".join("?" * len(self.etfs))
        self.dates = []
        if self.etfs:
            # 只列出同一天也有收盤行情的揭露日
            self.dates = [
                (r["date"], r["etf_count"])
                for r in conn.execute(
                    f"""
                    SELECT h.date, COUNT(DISTINCT h.etf_code) AS etf_count
                    FROM etf_holding AS h
                    WHERE h.etf_code IN ({self.marks})
                      AND EXISTS (SELECT 1 FROM daily_price AS p WHERE p.date = h.date)
                    GROUP BY h.date
                    ORDER BY h.date DESC
                    """,
                    self.etfs,
                )
            ]
        self.etf_count = dict(self.dates)

    def prices(self, date):
        """當日收盤與相對前一個交易日的漲跌幅，回傳 (前一交易日, {代號: (收盤, 漲跌幅%)})。"""
        row = self.conn.execute("SELECT MAX(date) AS date FROM daily_price WHERE date < ?", (date,)).fetchone()
        prev_date = row["date"]
        prev = {}
        if prev_date:
            prev = {r["code"]: r["close"] for r in self.conn.execute(
                "SELECT code, close FROM daily_price WHERE date = ?", (prev_date,)
            )}
        result = {}
        for r in self.conn.execute("SELECT code, close FROM daily_price WHERE date = ?", (date,)):
            before = prev.get(r["code"])
            # 停牌或無成交時收盤為空，漲跌幅一併留空
            change = (r["close"] / before - 1) * 100 if r["close"] and before else None
            result[r["code"]] = (r["close"], None if change is None else round(change, 2))
        return prev_date, result

    def holders(self, date):
        """當日各股被幾檔主動式 ETF 持有與合計持股市值，回傳 {代號: (檔數, 市值)}。"""
        rows = self.conn.execute(
            f"""
            SELECT h.stock_code AS code,
                   COUNT(DISTINCT h.etf_code) AS holders,
                   SUM(h.shares * p.close) AS value
            FROM etf_holding AS h
            LEFT JOIN daily_price AS p ON p.code = h.stock_code AND p.date = h.date
            WHERE h.date = ? AND h.etf_code IN ({self.marks})
            GROUP BY h.stock_code
            """,
            (date, *self.etfs),
        ).fetchall()
        return {r["code"]: (r["holders"], r["value"] or 0.0) for r in rows}


def build_structure(conn):
    """分類結構與可選的揭露日。"""
    themes = load_themes()
    info = _stock_info(conn)
    ctx = _Context(conn)
    return {
        "updated": themes["updated"],
        "relevance": themes["relevance"],
        "dates": [{"date": date, "etf_count": count} for date, count in ctx.dates],
        "themes": themes["themes"],
        "stocks": {
            code: {"name": info.get(code, (None, None))[0], "industry": info.get(code, (None, None))[1]}
            for code in sorted(_classified_codes(themes))
        },
    }


def _build_snapshot(ctx, date, classified, info):
    prev_date, prices = ctx.prices(date)
    holders = ctx.holders(date)
    stocks = {}
    for code in classified | set(holders):
        close, change = prices.get(code, (None, None))
        held, value = holders.get(code, (0, 0.0))
        stocks[code] = {"close": close, "change_pct": change, "etf_holders": held, "etf_value": round(value)}
    unclassified = sorted(
        (code for code in holders if code not in classified and code in info),
        key=lambda code: -holders[code][1],
    )
    return {
        "date": date,
        "prev_date": prev_date,
        "etf_count": ctx.etf_count[date],
        "stocks": stocks,
        "unclassified": [{"code": code, "name": info[code][0], "industry": info[code][1]} for code in unclassified],
    }


def build_snapshot(conn, date):
    """單一揭露日的數字，日期不在可選範圍內時回傳 None。"""
    ctx = _Context(conn)
    if date not in ctx.etf_count:
        return None
    return _build_snapshot(ctx, date, _classified_codes(load_themes()), _stock_info(conn))


def build_all(conn, limit=None):
    """匯出用：回傳 (結構, {日期: 當日數字})，只保留最近 limit 個揭露日。"""
    structure = build_structure(conn)
    if limit:
        structure["dates"] = structure["dates"][:limit]
    ctx = _Context(conn)
    classified = set(structure["stocks"])
    info = _stock_info(conn)
    snapshots = {item["date"]: _build_snapshot(ctx, item["date"], classified, info) for item in structure["dates"]}
    return structure, snapshots
