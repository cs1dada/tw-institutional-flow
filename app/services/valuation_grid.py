"""估值趨勢矩陣：前瞻本益比 × 股價相對 60 日均線的位置。

估值：前瞻本益比 = 最新收盤 ÷ 分析師共識 EPS，與所屬環節的合理區間比較，
低於下緣為便宜 (low)、高於上緣為偏貴 (high)，其餘為合理 (fair)。合理區間人工維護在
data/valuation_bands.json。

走勢：收盤相對 60 日均線的距離，高於 +5% 為均線上方 (strong)、
低於 -5% 為均線下方 (repair)，其餘為均線附近 (ma)。

Yahoo 只提供今年與明年兩個會計年度的預估，兩年各判定一次，前端可切換。
分析師少於 MIN_ANALYSTS 位、EPS 為負或沒有預估時，該年度不判定。

EPS 共識沒有歷史可回補，只能從開始抓取那天起每天累積，因此可選的日期以 EPS 快照為準：
每份快照配「快照當天或之前最近一個交易日」的收盤，不會用到事後才知道的共識。
輸出分成索引 (可選日期、題材順序與參數) 與各日期的快照，與題材分類相同。
"""
import json

from app import config
from app.services.themes import load_themes
from app.services.valuation import latest_estimates

BANDS_PATH = config.DATA_DIR / "valuation_bands.json"

MA_DAYS = 60
# 均線至少要有這麼多天的收盤才計算，剛上市或長期停牌的個股不判定位階
MA_MIN_DAYS = 50
ZONE_PCT = 5.0
# 本益比距合理區間邊界在這個百分比以內，標示為邊界股 (股價一動就可能換格)
EDGE_PCT = 3.0
MIN_ANALYSTS = 3
# 只呈現最近兩個會計年度
MAX_YEARS = 2

REL_ORDER = {"high": 0, "mid": 1, "low": 2}


def load_bands():
    with open(BANDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _memberships(themes):
    """每檔股票出現在哪些題材，依分類表順序，供前端依題材篩選。"""
    result = {}
    for theme in themes["themes"]:
        for seg in theme["segments"]:
            for stock in seg["stocks"]:
                names = result.setdefault(stock["code"], [])
                if theme["name"] not in names:
                    names.append(theme["name"])
    return result


def _primary_segments(themes):
    """每檔股票歸屬的環節：關聯度最高者，同等級取分類表中先出現的。"""
    result = {}
    for theme in themes["themes"]:
        for seg in theme["segments"]:
            for stock in seg["stocks"]:
                current = result.get(stock["code"])
                if current is None or REL_ORDER[stock["rel"]] < REL_ORDER[current["rel"]]:
                    result[stock["code"]] = {
                        "key": f"{theme['id']}/{seg['id']}",
                        "theme": theme["name"],
                        "segment": seg["name"],
                        "rel": stock["rel"],
                    }
    return result


def _prices(conn, codes, date):
    """指定交易日的收盤、漲跌幅與季線，回傳 {代號: {...}}。"""
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM daily_price WHERE date <= ? ORDER BY date DESC LIMIT ?", (date, MA_DAYS)
    )]
    if not dates or dates[0] != date:
        return {}
    latest, prev = dates[0], (dates[1] if len(dates) > 1 else None)
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"""
        SELECT code, date, close FROM daily_price
        WHERE date >= ? AND code IN ({marks}) AND close IS NOT NULL
        """,
        (dates[-1], *codes),
    ).fetchall()
    series = {}
    for r in rows:
        series.setdefault(r["code"], {})[r["date"]] = r["close"]
    result = {}
    for code, closes in series.items():
        close = closes.get(latest)
        if close is None:
            continue
        before = closes.get(prev)
        ma = sum(closes.values()) / len(closes) if len(closes) >= MA_MIN_DAYS else None
        result[code] = {
            "close": close,
            "change_pct": round((close / before - 1) * 100, 2) if before else None,
            "ma60": round(ma, 2) if ma else None,
            "dist_ma_pct": round((close / ma - 1) * 100, 2) if ma else None,
        }
    return result


def _zone(dist):
    if dist is None:
        return None
    if dist > ZONE_PCT:
        return "strong"
    if dist < -ZONE_PCT:
        return "repair"
    return "ma"


def _judge(close, estimate, band):
    """單一年度的本益比與判定。不判定時 valuation 為 None，並以 reason 說明原因。"""
    if not estimate:
        return {"pe": None, "eps": None, "analysts": None, "valuation": None, "reason": "no_estimate"}
    eps, analysts = estimate["eps_avg"], estimate["analysts"]
    base = {"eps": round(eps, 2) if eps is not None else None, "analysts": analysts}
    if eps is None or eps <= 0:
        return {**base, "pe": None, "valuation": None, "reason": "negative_eps"}
    pe = close / eps
    item = {**base, "pe": round(pe, 2), "valuation": None, "reason": None, "near_edge": False}
    if (analysts or 0) < MIN_ANALYSTS:
        item["reason"] = "few_analysts"
        return item
    if not band:
        item["reason"] = "no_band"
        return item
    low, high = band
    item["valuation"] = "low" if pe < low else "high" if pe > high else "fair"
    item["near_edge"] = any(abs(pe / edge - 1) * 100 <= EDGE_PCT for edge in (low, high))
    return item


def snapshot_dates(conn):
    """可選的日期，新到舊：[{"date": 收盤日, "estimate_date": EPS 快照日}]。

    同一個收盤日對到多份快照時 (例如週末也有抓)，取最新的一份。
    """
    pairs = {}
    for (estimate_date,) in conn.execute("SELECT DISTINCT date FROM eps_estimate ORDER BY date"):
        row = conn.execute("SELECT MAX(date) FROM daily_price WHERE date <= ?", (estimate_date,)).fetchone()
        if row and row[0]:
            pairs[row[0]] = estimate_date
    return [{"date": d, "estimate_date": pairs[d]} for d in sorted(pairs, reverse=True)]


def build_index(conn):
    """可選日期、題材順序 (與題材分類頁相同) 與判定參數。"""
    themes = load_themes()
    return {
        "dates": snapshot_dates(conn),
        "themes": [theme["name"] for theme in themes["themes"]],
        "bands_updated": load_bands().get("updated"),
        "ma_days": MA_DAYS,
        "zone_pct": ZONE_PCT,
        "edge_pct": EDGE_PCT,
        "min_analysts": MIN_ANALYSTS,
    }


def _build_snapshot(conn, date, estimate_date, themes, bands):
    segments = _primary_segments(themes)
    memberships = _memberships(themes)
    codes = sorted(segments)
    names = {r["code"]: r["name"] for r in conn.execute("SELECT code, name FROM stock_info")}
    prices = _prices(conn, codes, date)
    estimates = latest_estimates(conn, codes, as_of=estimate_date)

    # 以多數個股都有的年度為準，避免少數會計年度不同的個股多出一欄
    year_counts = {}
    for item in estimates.values():
        for year in item["years"]:
            year_counts[year] = year_counts.get(year, 0) + 1
    years = sorted(sorted(year_counts, key=lambda y: -year_counts[y])[:MAX_YEARS])

    stocks = []
    for code in codes:
        seg = segments[code]
        price = prices.get(code)
        if price is None:
            continue
        band = bands["stocks"].get(code) or bands["segments"].get(seg["key"])
        estimate = estimates.get(code, {"date": None, "years": {}})
        stocks.append({
            "code": code,
            "name": names.get(code),
            "theme": seg["theme"],
            "segment": seg["segment"],
            "themes": memberships[code],
            **price,
            "zone": _zone(price["dist_ma_pct"]),
            "band": band,
            "band_source": "stock" if code in bands["stocks"] else "segment",
            "years": {str(y): _judge(price["close"], estimate["years"].get(y), band) for y in years},
        })
    return {
        "date": date,
        "estimate_date": estimate_date,
        "years": [str(y) for y in years],
        "stocks": stocks,
    }


def build_snapshot(conn, date):
    """單一日期的矩陣，日期不在可選範圍內時回傳 None。"""
    pairs = {item["date"]: item["estimate_date"] for item in snapshot_dates(conn)}
    if date not in pairs:
        return None
    return _build_snapshot(conn, date, pairs[date], load_themes(), load_bands())


def build_all(conn, limit=None):
    """匯出用：回傳 (索引, {日期: 快照})，只保留最近 limit 個日期。"""
    index = build_index(conn)
    if limit:
        index["dates"] = index["dates"][:limit]
    themes, bands = load_themes(), load_bands()
    snapshots = {
        item["date"]: _build_snapshot(conn, item["date"], item["estimate_date"], themes, bands)
        for item in index["dates"]
    }
    return index, snapshots
