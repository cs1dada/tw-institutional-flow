"""主動式 ETF 累積趨勢：跨週比較，找出經理人默默加碼或減碼的個股與族群。

單日榜單抓的是「哪一天被大買」，這裡看的是相反的情況：每天買一點、從不上榜，
累積起來卻很可觀。以最新揭露日往前取 2、4、8 週 (每週 5 個揭露日) 三種窗口，
每個窗口輸出：

- 個股：逐週淨額、加碼與減碼天數、單日最大佔比與日期、加碼與減碼的 ETF 檔數、區間股價
- 族群：依證交所產業別與題材分類 (data/themes.json) 加總的逐週淨額

金額的算法：每週 (5 個揭露日) 各 ETF 期初與期末持股相比，以共同持股的股數倍率中位數
扣除申購贖回造成的整批同比例變動 (與 etf_daily.passive_factor 相同的邏輯)，
剩下的股數乘上週末的 VWAP，再把各週加總。不直接用發行單位數換算，
因為申購多以現金交付，經理人之後才分批買進，會把所有持股都算成減碼。

加碼天數與單日最大佔比則取每日校正後的加減碼 (etf_daily.trades)，用來衡量持續性：
單日最大佔比越低，代表加碼分散在越多天，越符合「默默」。
金額夠大、但不符合「默默」條件的個股另外標為集中加碼或集中減碼，
代表資金主要集中在少數幾天進出。

本機 API 與靜態匯出共用這裡的函式，兩種模式的格式一致。
"""
import statistics
from collections import defaultdict

from app.services import etf_daily, themes

# 每週的揭露日數
WEEK_DAYS = 5
# 可選的窗口週數
WINDOW_WEEKS = (2, 4, 8)
# 默默加碼：有加碼的天數至少佔窗口的這個比例，且單日最大佔比低於門檻
STEALTH_MIN_DAY_RATIO = 0.4
STEALTH_MAX_TOP_SHARE = 0.35
# 集中加碼與集中減碼的窗口淨額門檻 (元)，與 etf_report.BIG_AMOUNT 一致
BURST_MIN_AMOUNT = 3e8
# 窗口淨額低於這個金額 (元) 不列入，避免零股與四捨五入的雜訊
MIN_NET_AMOUNT = 1e7
# 各族群附上的主要個股數
GROUP_LEADERS = 3

TAGS = {
    "stealth_buy": "默默加碼",
    "stealth_sell": "默默減碼",
    "burst_buy": "集中加碼",
    "burst_sell": "集中減碼",
    "contrarian_buy": "逆勢加碼",
    "profit_take": "趁高調節",
}


def _yi(value):
    return round(value / 1e8, 2)


def _pct(after, before):
    if not after or not before:
        return None
    return round((after / before - 1) * 100, 2)


class _Context:
    def __init__(self, conn):
        self.daily = etf_daily._Context(conn)
        self.ready = self.daily.ready
        if not self.ready:
            return
        # 由舊到新的揭露日
        self.dates = [item["date"] for item in reversed(self.daily.available_dates())]
        self.stock_theme = defaultdict(list)
        for theme in themes.load_themes()["themes"]:
            for seg in theme["segments"]:
                for stock in seg["stocks"]:
                    if theme["name"] not in self.stock_theme[stock["code"]]:
                        self.stock_theme[stock["code"]].append(theme["name"])

    def _snapshot_on_or_before(self, etf, date):
        dates = [d for d in self.daily.snap_dates[etf] if d <= date]
        return dates[-1] if dates else None

    def _week_trades(self, start, end):
        """start 收盤到 end 收盤之間各 ETF 的主動加減碼，回傳 {stock: {etf: 金額}}。"""
        result = defaultdict(dict)
        for etf in self.daily.etf_codes:
            before_date = self._snapshot_on_or_before(etf, start)
            after_date = self._snapshot_on_or_before(etf, end)
            # 期初還沒上市 (沒有快照) 時，建倉不算加碼
            if not before_date or not after_date or before_date == after_date:
                continue
            before = self.daily.holdings[etf][before_date]
            after = self.daily.holdings[etf][after_date]
            ratios = [after[s] / n for s, n in before.items() if n > 0 and after.get(s, 0) > 0]
            factor = 1.0
            if len(ratios) >= etf_daily.PASSIVE_MIN_STOCKS:
                median = statistics.median(ratios)
                if abs(median - 1) >= etf_daily.PASSIVE_MIN_MOVE:
                    factor = median
            for stock in set(before) | set(after):
                held_before = before.get(stock, 0)
                held_after = after.get(stock, 0)
                if held_before <= 0 or held_after <= 0:
                    delta = held_after - held_before
                else:
                    delta = held_after - held_before * factor
                    noise = max(etf_daily.SHARES_PER_LOT, held_before * factor * etf_daily.PASSIVE_NOISE_RATIO)
                    if factor != 1.0 and abs(delta) < noise:
                        continue
                if abs(delta) < 1:
                    continue
                price = self.daily.prices.get((stock, end))
                if price:
                    result[stock][etf] = delta * price[0]
        return result

    def _daily_net(self, dates):
        """窗口內每日各股的淨加減碼金額，回傳 {stock: {date: 金額}}。"""
        result = defaultdict(dict)
        for date in dates:
            trades, _ = self.daily.trades(date, adjusted=True)
            for stock, rows in trades.items():
                result[stock][date] = sum(r[2] for r in rows)
        return result

    def _close(self, stock, date):
        price = self.daily.prices.get((stock, date))
        return price[1] if price else None

    def build_window(self, weeks):
        days = weeks * WEEK_DAYS
        if len(self.dates) < days + 1:
            return None
        window = self.dates[-days:]
        base = self.dates[-days - 1]
        # 各週的起訖：前一週的最後一天為本週的期初
        bounds = [base] + window[WEEK_DAYS - 1::WEEK_DAYS]
        week_ranges = [
            {"start": window[i * WEEK_DAYS], "end": window[(i + 1) * WEEK_DAYS - 1]} for i in range(weeks)
        ]

        weekly = defaultdict(lambda: [0.0] * weeks)
        etf_net = defaultdict(lambda: defaultdict(float))
        for i in range(weeks):
            for stock, by_etf in self._week_trades(bounds[i], bounds[i + 1]).items():
                for etf, amount in by_etf.items():
                    weekly[stock][i] += amount
                    etf_net[stock][etf] += amount

        daily = self._daily_net(window)
        end = window[-1]
        stocks = []
        for stock in set(weekly) | set(daily):
            series = weekly.get(stock, [0.0] * weeks)
            net = sum(series)
            if abs(net) < MIN_NET_AMOUNT:
                continue
            by_day = daily.get(stock, {})
            buys = [v for v in by_day.values() if v > 0]
            sells = [v for v in by_day.values() if v < 0]
            same_side = {d: v for d, v in by_day.items() if v > 0} if net > 0 else {d: v for d, v in by_day.items() if v < 0}
            top_date = max(same_side, key=lambda d: abs(same_side[d])) if same_side else None
            top_share = abs(same_side[top_date]) / abs(sum(same_side.values())) if top_date else None
            name, industry = self.daily._stock_name(stock)
            by_etf = etf_net.get(stock, {})
            buyers = sorted((e for e, v in by_etf.items() if v > 0), key=lambda e: -by_etf[e])
            sellers = sorted((e for e, v in by_etf.items() if v < 0), key=lambda e: by_etf[e])
            change = _pct(self._close(stock, end), self._close(stock, base))
            row = {
                "code": stock,
                "name": name,
                "industry": industry,
                "themes": self.stock_theme.get(stock, []),
                "net_amt": _yi(net),
                "weekly": [_yi(v) for v in series],
                "buy_days": len(buys),
                "sell_days": len(sells),
                "top_day_share": None if top_share is None else round(top_share, 3),
                "top_day": top_date,
                "top_day_amt": _yi(same_side[top_date]) if top_date else None,
                "buyers": buyers,
                "sellers": sellers,
                "close": self._close(stock, end),
                "change_pct": change,
            }
            row["tags"] = _tags(row, days)
            stocks.append(row)
        stocks.sort(key=lambda r: -abs(r["net_amt"]))

        return {
            "weeks": weeks,
            "days": days,
            "base_date": base,
            "start": window[0],
            "end": end,
            "week_ranges": week_ranges,
            "stocks": stocks,
            "groups": {
                "industry": _groups(stocks, lambda r: [r["industry"]] if r["industry"] else [], weeks),
                "theme": _groups(stocks, lambda r: r["themes"], weeks),
            },
        }


def _tags(row, days):
    tags = []
    net, change, share = row["net_amt"], row["change_pct"], row["top_day_share"]
    steady = share is not None and share < STEALTH_MAX_TOP_SHARE
    if net > 0 and steady and row["buy_days"] >= days * STEALTH_MIN_DAY_RATIO:
        tags.append("stealth_buy")
    if net < 0 and steady and row["sell_days"] >= days * STEALTH_MIN_DAY_RATIO:
        tags.append("stealth_sell")
    if not tags and abs(net) >= _yi(BURST_MIN_AMOUNT):
        tags.append("burst_buy" if net > 0 else "burst_sell")
    if change is not None and net > 0 and change < 0:
        tags.append("contrarian_buy")
    if change is not None and net < 0 and change > 0:
        tags.append("profit_take")
    return tags


def _groups(stocks, keys_of, weeks):
    """依產業別或題材加總，一檔股票屬於多個題材時全額計入每個題材。"""
    groups = defaultdict(lambda: {"weekly": [0.0] * weeks, "stocks": []})
    for row in stocks:
        for key in keys_of(row):
            group = groups[key]
            for i, value in enumerate(row["weekly"]):
                group["weekly"][i] += value
            group["stocks"].append(row)
    result = []
    for name, group in groups.items():
        net = sum(group["weekly"])
        members = sorted(group["stocks"], key=lambda r: -r["net_amt"] if net >= 0 else r["net_amt"])
        result.append(
            {
                "name": name,
                "net_amt": round(net, 2),
                "weekly": [round(v, 2) for v in group["weekly"]],
                "buy_weeks": sum(1 for v in group["weekly"] if v > 0),
                "sell_weeks": sum(1 for v in group["weekly"] if v < 0),
                "stock_count": len(members),
                "buy_count": sum(1 for r in members if r["net_amt"] > 0),
                "sell_count": sum(1 for r in members if r["net_amt"] < 0),
                "leaders": [
                    {"code": r["code"], "name": r["name"], "net_amt": r["net_amt"]} for r in members[:GROUP_LEADERS]
                ],
            }
        )
    result.sort(key=lambda r: -abs(r["net_amt"]))
    return result


def build(conn):
    """以最新揭露日為終點的三種窗口，資料不足時回傳 None。"""
    ctx = _Context(conn)
    if not ctx.ready or not ctx.dates:
        return None
    windows = {}
    for weeks in WINDOW_WEEKS:
        payload = ctx.build_window(weeks)
        if payload is not None:
            windows[str(weeks)] = payload
    if not windows:
        return None
    return {
        "date": ctx.dates[-1],
        "week_days": WEEK_DAYS,
        "thresholds": {
            "stealth_min_day_ratio": STEALTH_MIN_DAY_RATIO,
            "stealth_max_top_share": STEALTH_MAX_TOP_SHARE,
            "burst_min_yi": _yi(BURST_MIN_AMOUNT),
            "min_net_yi": _yi(MIN_NET_AMOUNT),
        },
        "tags": TAGS,
        "etf_names": {code: ctx.daily.etf_names.get(code) for code in ctx.daily.etf_codes},
        "windows": windows,
    }
