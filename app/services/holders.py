"""集保股權分散：每週的大戶與散戶持股變化。

資料來自集保的股權分散表 (holder_dist)，每檔每週 17 列。這裡把級距彙總成三個指標：

- 千張大戶：第 15 級 (1,000,001 股以上)
- 400 張以上：第 12~15 級
- 50 張以下：第 1~8 級 (1~50,000 股)

集保依身分歸戶，外資、投信、ETF 的帳戶各算一人，多半落在千張大戶，
因此千張大戶不等於自然人大戶；股東人數與 50 張以下的比例才是比較直接的散戶訊號。

資料來源有兩種：

- 開放資料：每週最新一份的全市場檔案，由每日排程下載 (ingest_latest)
- 手動補查：過去的週次只能從集保網站逐檔查詢，以瀏覽器查好後存成
  data/holders_manual/{YYYYMMDD}.json 並納入版控，排程執行時再匯入 (import_manual)

本機 API 與靜態匯出共用這裡的函式，兩種模式的格式一致。
"""
import json
import logging

from app import config
from app.fetchers import tdcc
from app.services.themes import classified_codes, load_themes

logger = logging.getLogger(__name__)

MANUAL_DIR = config.DATA_DIR / "holders_manual"

LEVEL_LABELS = {
    1: "1-999",
    2: "1,000-5,000",
    3: "5,001-10,000",
    4: "10,001-15,000",
    5: "15,001-20,000",
    6: "20,001-30,000",
    7: "30,001-40,000",
    8: "40,001-50,000",
    9: "50,001-100,000",
    10: "100,001-200,000",
    11: "200,001-400,000",
    12: "400,001-600,000",
    13: "600,001-800,000",
    14: "800,001-1,000,000",
    15: "1,000,001 以上",
    16: "差異數調整",
    17: "合計",
}
BIG_LEVEL = 15
BIG400_LEVELS = range(12, 16)
SMALL_LEVELS = range(1, 9)
TOTAL_LEVEL = 17


def save_week(conn, date, rows):
    """寫入一週的股權分散，rows 為 (code, level, people, shares, pct)。同一週重複匯入時覆蓋。"""
    conn.executemany(
        """
        INSERT INTO holder_dist (date, code, level, people, shares, pct)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, code, level) DO UPDATE SET
            people = excluded.people, shares = excluded.shares, pct = excluded.pct
        """,
        [(date, *row) for row in rows],
    )
    conn.commit()
    return len({row[0] for row in rows})


def _codes_of(conn, date):
    return {r[0] for r in conn.execute(
        "SELECT code FROM holder_dist WHERE date = ? AND level = ?", (date, TOTAL_LEVEL)
    )}


def ingest_latest(conn):
    """下載開放資料的最新一週並寫入，回傳 {date: 檔數}。

    開放資料每週才更新一次，每天執行時多半是已經匯入過的同一週，
    檔數相同就略過，不重複寫入。
    """
    result = {}
    for date, rows in tdcc.fetch_latest().items():
        codes = {row[0] for row in rows}
        if len(_codes_of(conn, date)) >= len(codes):
            result[date] = 0
            continue
        result[date] = save_week(conn, date, rows)
    return result


def import_manual(conn):
    """匯入 data/holders_manual/ 中資料庫還沒有的個股，回傳 {date: 檔數}。

    檔案格式為 {代號: [[級距, 人數, 股數, 比例], ...]}，合計固定放在第 17 級。
    """
    result = {}
    if not MANUAL_DIR.exists():
        return result
    for path in sorted(MANUAL_DIR.glob("*.json")):
        date = path.stem
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        existing = _codes_of(conn, date)
        rows = [
            (code, int(lv), int(people), int(shares), float(pct))
            for code, levels in data.items() if code not in existing
            for lv, people, shares, pct in levels
        ]
        if rows:
            result[date] = save_week(conn, date, rows)
    return result


def weeks(conn):
    return [
        {"date": r["date"], "stock_count": r["stock_count"]}
        for r in conn.execute(
            """
            SELECT date, COUNT(DISTINCT code) AS stock_count
            FROM holder_dist WHERE level = ?
            GROUP BY date ORDER BY date DESC
            """,
            (TOTAL_LEVEL,),
        )
    ]


def _summaries(conn, date, code=None):
    """某一週各股的彙總指標 {code: {...}}，指定 code 時只算那一檔。"""
    sql = "SELECT code, level, people, shares, pct FROM holder_dist WHERE date = ?"
    params = [date]
    if code:
        sql += " AND code = ?"
        params.append(code)
    levels = {}
    for r in conn.execute(sql, params):
        levels.setdefault(r["code"], {})[r["level"]] = (r["people"], r["shares"], r["pct"])
    result = {}
    for stock, lv in levels.items():
        total = lv.get(TOTAL_LEVEL)
        if not total or not total[0]:
            continue
        get = lambda i, k: lv.get(i, (0, 0, 0.0))[k]  # noqa: E731
        result[stock] = {
            "holders": total[0],
            "avg_lots": round(total[1] / total[0] / 1000, 2),
            "big_pct": round(get(BIG_LEVEL, 2), 2),
            "big_people": get(BIG_LEVEL, 0),
            "big400_pct": round(sum(get(i, 2) for i in BIG400_LEVELS), 2),
            "small_pct": round(sum(get(i, 2) for i in SMALL_LEVELS), 2),
            "small_people": sum(get(i, 0) for i in SMALL_LEVELS),
        }
    return result


def _closes(conn, date):
    """資料日當天 (或之前最近一個交易日) 的收盤價。"""
    row = conn.execute("SELECT MAX(date) AS d FROM daily_price WHERE date <= ?", (date,)).fetchone()
    if not row or not row["d"]:
        return None, {}
    trade_date = row["d"]
    return trade_date, {r["code"]: r["close"] for r in conn.execute(
        "SELECT code, close FROM daily_price WHERE date = ?", (trade_date,)
    )}


def _close_of(conn, code, date):
    """單一個股在資料日當天 (或之前最近一個交易日) 的收盤價。"""
    row = conn.execute(
        "SELECT close FROM daily_price WHERE code = ? AND date <= ? ORDER BY date DESC LIMIT 1", (code, date)
    ).fetchone()
    return row["close"] if row else None


def _diff(now, before, key):
    if before is None:
        return None
    return round(now[key] - before[key], 2)


def build_index(conn):
    return {"weeks": weeks(conn)}


def build_week(conn, date):
    """一週的全市場個股 (不含 ETF)，附與前一週相比的變化與週漲跌。"""
    all_weeks = [w["date"] for w in weeks(conn)]
    if date not in all_weeks:
        return None
    index = all_weeks.index(date)
    prev_date = all_weeks[index + 1] if index + 1 < len(all_weeks) else None

    now = _summaries(conn, date)
    before = _summaries(conn, prev_date) if prev_date else {}
    trade_date, closes = _closes(conn, date)
    _, prev_closes = _closes(conn, prev_date) if prev_date else (None, {})
    theme_codes = classified_codes(load_themes())
    info = {
        r["code"]: (r["name"], r["industry"])
        for r in conn.execute("SELECT code, name, industry FROM stock_info WHERE is_etf = 0")
    }

    # 只輸出有前一週可比較的個股，靜態檔才不會被沒有變化的上千檔撐大；
    # 沒有前一週的檔數另外記在 uncompared，頁面用來說明為什麼範圍切換後檔數沒變
    rows = []
    uncompared = 0
    for code, item in now.items():
        if code not in info:
            continue
        prev = before.get(code)
        if prev is None:
            uncompared += 1
            continue
        close, prev_close = closes.get(code), prev_closes.get(code)
        rows.append({
            "code": code,
            "name": info[code][0],
            "industry": info[code][1],
            "theme": code in theme_codes,
            "holders": item["holders"],
            "big_pct": item["big_pct"],
            "holders_diff": item["holders"] - prev["holders"],
            "holders_pct": round((item["holders"] / prev["holders"] - 1) * 100, 2),
            "big_diff": _diff(item, prev, "big_pct"),
            "price_pct": round((close / prev_close - 1) * 100, 2) if close and prev_close else None,
        })
    rows.sort(key=lambda r: r["code"])
    return {
        "date": date,
        "prev_date": prev_date,
        "trade_date": trade_date,
        "stock_count": len(now),
        "uncompared": uncompared,
        "rows": rows,
    }


def build_stock(conn, code):
    """單一個股的逐週走勢與最新兩週的完整級距。"""
    dates = [r["date"] for r in conn.execute(
        "SELECT DISTINCT date FROM holder_dist WHERE code = ? ORDER BY date", (code,)
    )]
    if not dates:
        return None
    series = []
    for date in dates:
        item = _summaries(conn, date, code).get(code)
        if not item:
            continue
        series.append({"date": date, **item, "close": _close_of(conn, code, date)})

    def levels(date):
        return [
            {"level": r["level"], "label": LEVEL_LABELS.get(r["level"], str(r["level"])),
             "people": r["people"], "shares": r["shares"], "pct": r["pct"]}
            for r in conn.execute(
                "SELECT level, people, shares, pct FROM holder_dist WHERE date = ? AND code = ? ORDER BY level",
                (date, code),
            )
        ]

    name = conn.execute("SELECT name FROM stock_info WHERE code = ?", (code,)).fetchone()
    return {
        "code": code,
        "name": name["name"] if name else None,
        "series": series,
        "latest": {"date": dates[-1], "levels": levels(dates[-1])},
        "previous": {"date": dates[-2], "levels": levels(dates[-2])} if len(dates) > 1 else None,
    }


def stock_codes(conn):
    """有股權分散資料的個股 (不含 ETF)，靜態匯出時逐檔產生走勢檔。"""
    return [r[0] for r in conn.execute(
        """
        SELECT DISTINCT h.code FROM holder_dist AS h
        JOIN stock_info AS s ON s.code = h.code AND s.is_etf = 0
        WHERE h.level = ? ORDER BY h.code
        """,
        (TOTAL_LEVEL,),
    )]


def merge_stock(old, new):
    """以既有的個股走勢檔為底合併，保留資料庫沒有的週次。

    開放資料只有最新一週，線上排程的資料庫存在 Actions 快取裡，快取被清掉後舊週次查不回來，
    因此逐週走勢以已提交的靜態檔為準：同一週以資料庫為準，資料庫沒有的週次沿用舊檔。
    級距明細只保留資料庫有的最新兩週。
    """
    if not old or not isinstance(old.get("series"), list):
        return new
    if new is None:
        return old
    merged = {item["date"]: item for item in old["series"] if isinstance(item, dict) and "date" in item}
    merged.update({item["date"]: item for item in new["series"]})
    return {**new, "series": [merged[d] for d in sorted(merged)]}
