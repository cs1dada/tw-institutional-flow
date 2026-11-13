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


# 與頁面相同的判斷門檻：千張大戶比例變化 (百分點)、股東人數變化 (%)
BIG_THRESHOLD = 0.5
RETAIL_IN_PCT = 3
RETAIL_OUT_PCT = -1.5
# 往回比較的週數 (排行的 4 週、12 週累計) 與回測往後看的週數
WINDOWS = (4, 12)
# 位階以近一年 (52 週) 為範圍，資料少於 8 週時不計算
RANK_WEEKS = 52
RANK_MIN_WEEKS = 8
# 連續增加或減少達這個週數，回測時當作一個訊號
STREAK_SIGNAL = 3


class History:
    """所有週次的彙總指標，一次載入後供逐週計算共用。

    個股走勢、累計變化、連續週數、位階與回測都要跨週比較，
    逐週查資料庫太慢，因此一次讀出第 12~17 級，在記憶體中計算。
    """

    def __init__(self, conn):
        self.conn = conn
        # 由舊到新
        self.weeks = [w["date"] for w in reversed(weeks(conn))]
        self.index = {d: i for i, d in enumerate(self.weeks)}
        self.data = {}
        levels = {}
        for r in conn.execute(
            "SELECT date, code, level, people, shares, pct FROM holder_dist WHERE level >= ?",
            (min(BIG400_LEVELS),),
        ):
            levels.setdefault((r["code"], r["date"]), {})[r["level"]] = (r["people"], r["shares"], r["pct"])
        for (code, date), lv in levels.items():
            total = lv.get(TOTAL_LEVEL)
            if not total or not total[0]:
                continue
            big = lv.get(BIG_LEVEL, (0, 0, 0.0))
            self.data.setdefault(code, {})[date] = {
                "holders": total[0],
                "big_pct": big[2],
                "big_shares": big[1],
                "big400_pct": sum(lv.get(i, (0, 0, 0.0))[2] for i in BIG400_LEVELS),
            }
        self._closes = {}
        self._inst = {}
        row = conn.execute("SELECT MIN(date) AS d FROM inst_trade").fetchone()
        self.inst_since = row["d"] if row else None

    def closes(self, date):
        """(交易日, {code: 收盤})，同一週只查一次"""
        if date not in self._closes:
            self._closes[date] = _closes(self.conn, date)
        return self._closes[date]

    def back(self, date, k):
        """往前第 k 週的資料日，超出範圍回傳 None"""
        i = self.index[date] - k
        return self.weeks[i] if i >= 0 else None

    def forward(self, date, k):
        i = self.index[date] + k
        return self.weeks[i] if i < len(self.weeks) else None

    def inst_lots(self, prev_date, date):
        """兩個資料日之間三大法人的買賣超合計 (張)，法人資料不涵蓋這段期間時回傳 None"""
        key = (prev_date, date)
        if key not in self._inst:
            start, _ = self.closes(prev_date)
            end, _ = self.closes(date)
            if not start or not end or not self.inst_since or self.inst_since > start:
                self._inst[key] = None
            else:
                self._inst[key] = {
                    r["code"]: round(r["net"] / 1000)
                    for r in self.conn.execute(
                        "SELECT code, SUM(total_net) AS net FROM inst_trade WHERE date > ? AND date <= ? GROUP BY code",
                        (start, end),
                    )
                }
        return self._inst[key]

    def big_diff(self, code, date, k=1):
        """千張大戶比例在 k 週內的變化 (百分點)，缺任一週時回傳 None"""
        before = self.back(date, k)
        series = self.data.get(code, {})
        if before is None or date not in series or before not in series:
            return None
        return round(series[date]["big_pct"] - series[before]["big_pct"], 2)

    def holders_pct(self, code, date, k=1):
        before = self.back(date, k)
        series = self.data.get(code, {})
        if before is None or date not in series or before not in series or not series[before]["holders"]:
            return None
        return round((series[date]["holders"] / series[before]["holders"] - 1) * 100, 2)

    def price_pct(self, code, date, k):
        """k 週內的股價漲跌 (%)，k 為負數時表示往後 k 週"""
        other = self.back(date, k) if k > 0 else self.forward(date, -k)
        if other is None:
            return None
        now, then = self.closes(date)[1].get(code), self.closes(other)[1].get(code)
        if not now or not then:
            return None
        return round((now / then - 1) * 100, 2) if k > 0 else round((then / now - 1) * 100, 2)

    def streak(self, code, date):
        """千張大戶比例連續增加 (正數) 或減少 (負數) 的週數，以 date 為最後一週"""
        count = 0
        current = date
        while True:
            diff = self.big_diff(code, current)
            if diff is None:
                return count
            if diff > 0 and count >= 0:
                count += 1
            elif diff < 0 and count <= 0:
                count -= 1
            else:
                return count
            current = self.back(current, 1)

    def rank(self, code, date, key):
        """目前數值在近一年中的位置 (0 為最低、100 為最高)，資料不足時回傳 None"""
        series = self.data.get(code, {})
        start = max(0, self.index[date] - RANK_WEEKS + 1)
        values = [series[d][key] for d in self.weeks[start:self.index[date] + 1] if d in series]
        if len(values) < RANK_MIN_WEEKS:
            return None
        low, high = min(values), max(values)
        return 50 if high == low else round((series[date][key] - low) / (high - low) * 100)


def _extra_fields(history, code, date, prev_date):
    """排行用的跨週指標：累計變化、連續週數、位階、中實戶與法人買賣超"""
    series = history.data.get(code, {})
    now, prev = series.get(date), series.get(prev_date)
    extra = {}
    for k in WINDOWS:
        extra[f"big_diff_{k}w"] = history.big_diff(code, date, k)
        extra[f"holders_pct_{k}w"] = history.holders_pct(code, date, k)
        extra[f"price_pct_{k}w"] = history.price_pct(code, date, k)
    extra["streak"] = history.streak(code, date)
    extra["big_rank"] = history.rank(code, date, "big_pct")
    extra["holders_rank"] = history.rank(code, date, "holders")
    # 400~1000 張的中實戶：千張大戶裡混了大量法人帳戶，這一層比較接近本土大戶與主力
    if now and prev:
        extra["mid_pct"] = round(now["big400_pct"] - now["big_pct"], 2)
        extra["mid_diff"] = round((now["big400_pct"] - now["big_pct"]) - (prev["big400_pct"] - prev["big_pct"]), 2)
        extra["big_lots_diff"] = round((now["big_shares"] - prev["big_shares"]) / 1000)
    inst = history.inst_lots(prev_date, date) if prev_date else None
    extra["inst_lots"] = inst.get(code, 0) if inst is not None else None
    # 全市場的週檔有上千列，沒有值的欄位不輸出，頁面把缺少的欄位當成沒有資料
    return {key: value for key, value in extra.items() if value is not None}


def build_week(conn, date, history=None):
    """一週的全市場個股 (不含 ETF)，附與前一週相比的變化、跨週指標與週漲跌。

    history 為 History 物件，逐週匯出時共用同一份，避免每週重新載入。
    """
    all_weeks = [w["date"] for w in weeks(conn)]
    if date not in all_weeks:
        return None
    index = all_weeks.index(date)
    prev_date = all_weeks[index + 1] if index + 1 < len(all_weeks) else None
    history = history or History(conn)

    now = _summaries(conn, date)
    before = _summaries(conn, prev_date) if prev_date else {}
    trade_date, closes = history.closes(date)
    _, prev_closes = history.closes(prev_date) if prev_date else (None, {})
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
            **_extra_fields(history, code, date, prev_date),
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


SIGNALS = (
    ("big_up", "大戶在收"),
    ("big_down", "大戶在賣"),
    ("retail_in", "散戶湧入"),
    ("retail_out", "散戶離開"),
    ("streak_up", f"大戶連續 {STREAK_SIGNAL} 週以上增加"),
    ("streak_down", f"大戶連續 {STREAK_SIGNAL} 週以上減少"),
    ("gather", "大戶收、散戶走"),
    ("scatter", "大戶賣、散戶接"),
)


def _signals(history, code, date):
    """某一週符合的訊號，判斷方式與頁面的排行、解讀相同"""
    big = history.big_diff(code, date)
    retail = history.holders_pct(code, date)
    if big is None or retail is None:
        return []
    hits = []
    if big >= BIG_THRESHOLD:
        hits.append("big_up")
    if big <= -BIG_THRESHOLD:
        hits.append("big_down")
    if retail >= RETAIL_IN_PCT:
        hits.append("retail_in")
    if retail <= RETAIL_OUT_PCT:
        hits.append("retail_out")
    streak = history.streak(code, date)
    if streak >= STREAK_SIGNAL:
        hits.append("streak_up")
    if streak <= -STREAK_SIGNAL:
        hits.append("streak_down")
    if big >= BIG_THRESHOLD and retail <= 0:
        hits.append("gather")
    if big <= -BIG_THRESHOLD and retail >= 1:
        hits.append("scatter")
    return hits


def _stats(returns):
    """[報酬, ...] 的樣本數、平均、中位數與上漲比例。

    平均容易被少數飆股拉高，中位數比較接近一般情況，兩者都列出。
    """
    if not returns:
        return {"count": 0, "avg": None, "median": None, "win": None}
    ordered = sorted(returns)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "count": len(returns),
        "avg": round(sum(returns) / len(returns), 2),
        "median": round(median, 2),
        "win": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
    }


def _backtest(history, codes):
    """訊號出現後 4 週、12 週的股價表現，與同期所有題材股相比。

    以每一週為起點，對每檔題材股判斷訊號，再看之後 k 週的漲跌。
    對照組是同一批週次的全部題材股，超額報酬才看得出訊號有沒有用。
    """
    horizons = WINDOWS
    buckets = {key: {k: [] for k in horizons} for key, _ in SIGNALS}
    baseline = {k: [] for k in horizons}
    for date in history.weeks:
        for code in codes:
            hits = _signals(history, code, date)
            if not hits and history.big_diff(code, date) is None:
                continue
            for k in horizons:
                ret = history.price_pct(code, date, -k)
                if ret is None:
                    continue
                baseline[k].append(ret)
                for key in hits:
                    buckets[key][k].append(ret)
    base = {k: _stats(baseline[k]) for k in horizons}
    rows = []
    for key, label in SIGNALS:
        row = {"key": key, "label": label}
        for k in horizons:
            stats = _stats(buckets[key][k])
            for name in ("count", "avg", "median", "win"):
                row[f"{name}_{k}w"] = stats[name]
            # 超額以中位數相減，不受少數飆股影響
            row[f"excess_{k}w"] = (
                round(stats["median"] - base[k]["median"], 2)
                if stats["median"] is not None and base[k]["median"] is not None else None
            )
        rows.append(row)
    return {
        "horizons": list(horizons),
        "baseline": {f"{name}_{k}w": base[k][name] for k in horizons for name in ("count", "avg", "median", "win")},
        "rows": rows,
    }


def _heatmap(history, themes):
    """各題材每週的千張大戶比例平均變化，看大戶在題材之間的輪動"""
    dates = [d for d in history.weeks if history.back(d, 1)]
    result = []
    for theme in themes["themes"]:
        codes = {s["code"] for seg in theme["segments"] for s in seg["stocks"]}
        values = []
        counts = []
        for date in dates:
            diffs = [d for d in (history.big_diff(code, date) for code in codes) if d is not None]
            values.append(round(sum(diffs) / len(diffs), 2) if diffs else None)
            counts.append(len(diffs))
        result.append({"id": theme["id"], "name": theme["name"], "values": values, "counts": counts})
    return {"weeks": dates, "themes": result}


def build_analysis(conn, history=None):
    """題材股的訊號回測與題材輪動熱力圖。

    只用題材股：過去的週次只補查了題材股，其他個股從開放資料開始才有逐週資料。
    題材分類是現在的名單，不是當時的名單，回測結果會有一些後見之明。
    """
    history = history or History(conn)
    themes = load_themes()
    codes = sorted(classified_codes(themes))
    return {
        "weeks": len(history.weeks),
        "first_week": history.weeks[0] if history.weeks else None,
        "last_week": history.weeks[-1] if history.weeks else None,
        "stock_count": sum(1 for c in codes if c in history.data),
        "thresholds": {
            "big": BIG_THRESHOLD,
            "retail_in": RETAIL_IN_PCT,
            "retail_out": RETAIL_OUT_PCT,
            "streak": STREAK_SIGNAL,
        },
        "backtest": _backtest(history, codes),
        "heatmap": _heatmap(history, themes),
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
