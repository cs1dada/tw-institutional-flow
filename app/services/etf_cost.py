"""主動式 ETF 經理人的持倉成本與共識價。

方法整理自 notes/ETF_STRATEGY.md 第一節：

- 每日買賣：同一檔 ETF 相鄰兩個揭露日的股數差，以當日 VWAP (成交金額 ÷ 成交股數) 推估成交價
- 買進均價：觀察期間內每檔 ETF 對同一檔股票的買進金額 ÷ 買進股數
- 等權共識價：各 ETF 買進均價的平均，每家一票
- 資金加權共識價：各 ETF 買進均價以買進金額加權
- 共識價帶：各家買進均價的 25% 到 75% 分位
- 持倉成本：平均成本法，買進增加庫存成本，賣出依當時均價沖銷

限制：
- 第一個快照之前就持有的股數無從得知買進價，以該日收盤價作為起始成本
- 未扣除申購贖回造成的被動買賣
- 分割、股票股利、減資會自動偵測並還原，現金股利的除息缺口不還原
- 只計算台股：以海外股票為主的 ETF 持股基準日跟著海外市場，不納入

本機 API 與靜態匯出共用這裡的函式，兩種模式的格式一致。
"""
from collections import defaultdict

# 觀察期間的交易日數
COST_DAYS = 180
# 持股能對到台股行情的比例低於此值時，視為以海外股票為主的 ETF
DOMESTIC_RATIO = 0.5
# 台股單日漲跌幅限制，超過即可能是公司行動 (留一點緩衝給四捨五入)
PRICE_LIMIT = 0.105
# 持股倍率偏離 1 超過此值才視為公司行動，避免把一般加減碼誤判
SPLIT_THRESHOLD = 0.2


def _domestic_etfs(conn):
    """以台股為主的主動式 ETF。"""
    rows = conn.execute(
        """
        SELECT h.etf_code,
               COUNT(*) AS total,
               SUM(CASE WHEN p.code IS NOT NULL THEN 1 ELSE 0 END) AS matched
        FROM etf_holding AS h
        LEFT JOIN daily_price AS p ON p.code = h.stock_code AND p.date = h.date
        GROUP BY h.etf_code
        """
    ).fetchall()
    return sorted(r["etf_code"] for r in rows if r["total"] and r["matched"] / r["total"] >= DOMESTIC_RATIO)


def _etf_names(conn, codes):
    marks = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT code, name FROM stock_info WHERE code IN ({marks})", codes)
    names = {r["code"]: r["name"] for r in rows}
    return {code: names.get(code) for code in codes}


def _quantile(values, q):
    """線性內插的分位數，與 numpy 預設的算法相同。"""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _round(value, digits=2):
    return None if value is None else round(value, digits)


def _load(conn, etf_codes):
    """讀出計算所需的持股與行情。

    回傳 (all_dates, holdings, prices, names, events)：
    - holdings[etf][date] = {stock_code: shares}，只含有快照的日期
    - prices[(stock_code, date)] = (vwap, close)
    - events[stock_code] = [(date, factor)]，偵測到的公司行動
    """
    marks = ",".join("?" * len(etf_codes))
    holdings = defaultdict(dict)
    names = {}
    for r in conn.execute(
        f"""
        SELECT date, etf_code, stock_code, stock_name, shares
        FROM etf_holding
        WHERE etf_code IN ({marks})
        """,
        etf_codes,
    ):
        holdings[r["etf_code"]].setdefault(r["date"], {})[r["stock_code"]] = r["shares"] or 0
        if r["stock_name"]:
            names[r["stock_code"]] = r["stock_name"]

    start = min(min(dates) for dates in holdings.values())
    prices = {}
    for r in conn.execute(
        f"""
        SELECT p.date, p.code, p.close, p.volume, p.turnover
        FROM daily_price AS p
        WHERE p.date >= ?
          AND p.code IN (SELECT DISTINCT stock_code FROM etf_holding WHERE etf_code IN ({marks}))
        """,
        [start, *etf_codes],
    ):
        vwap = r["turnover"] / r["volume"] if r["volume"] and r["turnover"] else r["close"]
        if vwap:
            prices[(r["code"], r["date"])] = (vwap, r["close"])

    all_dates = sorted(
        r[0] for r in conn.execute("SELECT DISTINCT date FROM daily_price WHERE date >= ?", (start,))
    )
    events = _adjust_corporate_actions(all_dates, holdings, prices)
    return all_dates, holdings, prices, names, events


def _adjust_corporate_actions(all_dates, holdings, prices):
    """還原分割、股票股利、減資造成的股數與股價跳動。

    台股漲跌幅限制為 10%，收盤價變動超過限制、且各 ETF 的持股同步以相近倍率變動，
    即視為公司行動。倍率取各 ETF 持股變化倍率的中位數，並把事件之前的股數乘上倍率、
    股價除以倍率，換算成最新的股本單位。現金股利的除息缺口在漲跌幅限制內，不做還原。

    直接修改傳入的 holdings 與 prices，回傳偵測到的事件。
    """
    prev_date = {d: p for p, d in zip(all_dates, all_dates[1:])}
    events = defaultdict(list)  # stock -> [(date, factor)]
    stocks = {stock for snapshots in holdings.values() for day in snapshots.values() for stock in day}
    for stock in stocks:
        for date, prev in prev_date.items():
            today, before = prices.get((stock, date)), prices.get((stock, prev))
            if not today or not before or not today[1] or not before[1]:
                continue
            if abs(today[1] / before[1] - 1) <= PRICE_LIMIT:
                continue
            ratios = []
            for snapshots in holdings.values():
                held_before = snapshots.get(prev, {}).get(stock)
                held_today = snapshots.get(date, {}).get(stock)
                if held_before and held_today:
                    ratios.append(held_today / held_before)
            if not ratios:
                continue
            factor = sorted(ratios)[len(ratios) // 2]
            if abs(factor - 1) >= SPLIT_THRESHOLD:
                events[stock].append((date, factor))

    for stock, stock_events in events.items():
        def factor_after(date):
            result = 1.0
            for event_date, factor in stock_events:
                if date < event_date:
                    result *= factor
            return result

        for snapshots in holdings.values():
            for date, day in snapshots.items():
                if stock in day:
                    day[stock] = day[stock] * factor_after(date)
        for date in all_dates:
            key = (stock, date)
            if key in prices:
                f = factor_after(date)
                prices[key] = (prices[key][0] / f, prices[key][1] / f)
    return events


def _simulate(all_dates, holdings, prices, window_start):
    """逐日推進每檔 ETF 的庫存，記錄成本與買賣。

    回傳 (positions, trades)：
    - positions[(stock, etf)][date] = (shares, cost)，觀察期間內每個交易日的庫存
    - trades[stock] = [(date, etf, shares, price)]，觀察期間內的買賣，shares 為正是買進
    """
    positions = defaultdict(dict)
    trades = defaultdict(list)
    for etf_code, snapshots in holdings.items():
        snap_dates = sorted(snapshots)
        first = snap_dates[0]
        state = {}  # stock -> [shares, cost]
        prev = {}
        for date in all_dates:
            if date < first:
                continue
            current = snapshots.get(date)
            if current is not None:
                for stock in set(prev) | set(current):
                    delta = current.get(stock, 0) - prev.get(stock, 0)
                    price = prices.get((stock, date))
                    if date == first:
                        # 起始庫存的買進價不明，以當日收盤價作為成本
                        if price and current.get(stock):
                            state[stock] = [current[stock], current[stock] * price[1]]
                        continue
                    if delta == 0 or price is None:
                        continue
                    shares, cost = state.get(stock, [0, 0.0])
                    if delta > 0:
                        state[stock] = [shares + delta, cost + delta * price[0]]
                    elif shares > 0:
                        sold = min(-delta, shares)
                        remain = shares - sold
                        state[stock] = [remain, cost * remain / shares if remain else 0.0]
                    if date >= window_start:
                        trades[stock].append((date, etf_code, delta, price[0]))
                prev = current
            if date >= window_start:
                for stock, (shares, cost) in state.items():
                    if shares > 0:
                        positions[(stock, etf_code)][date] = (shares, cost)
    return positions, trades


def _consensus(trades):
    """以觀察期間的買進計算各家均價與共識價。"""
    per_etf = defaultdict(lambda: [0.0, 0])  # etf -> [amount, shares]
    for _, etf_code, shares, price in trades:
        if shares > 0:
            per_etf[etf_code][0] += shares * price
            per_etf[etf_code][1] += shares
    if not per_etf:
        return None
    avgs = {etf: amt / sh for etf, (amt, sh) in per_etf.items()}
    amounts = {etf: amt for etf, (amt, _) in per_etf.items()}
    total_amt = sum(amounts.values())
    values = list(avgs.values())
    return {
        "buyer_avg": {etf: _round(v) for etf, v in avgs.items()},
        "equal": _round(sum(values) / len(values)),
        "weighted": _round(sum(avgs[e] * amounts[e] for e in avgs) / total_amt),
        "band": [_round(_quantile(values, 0.25)), _round(_quantile(values, 0.75))],
    }


def compute(conn, days=COST_DAYS):
    """計算觀察期間內所有個股的經理人成本。

    回傳 (summary, details)，details 以股票代號為鍵，供個股疊圖使用。
    尚無持股資料時回傳 (None, {})。
    """
    etf_codes = _domestic_etfs(conn)
    if not etf_codes:
        return None, {}
    all_dates, holdings, prices, names, events = _load(conn, etf_codes)
    last = max(max(dates) for dates in holdings.values())
    all_dates = [d for d in all_dates if d <= last]
    window = all_dates[-days:]
    positions, trades = _simulate(all_dates, holdings, prices, window[0])

    stock_info = {
        r["code"]: (r["name"], r["industry"])
        for r in conn.execute("SELECT code, name, industry FROM stock_info")
    }
    etf_names = _etf_names(conn, etf_codes)

    by_stock = defaultdict(list)
    for (stock, etf_code), series in positions.items():
        by_stock[stock].append((etf_code, series))

    daily = {d: [0.0, 0.0] for d in window}  # date -> [買進金額, 賣出金額]
    for stock_trades in trades.values():
        for date, _, shares, price in stock_trades:
            daily[date][0 if shares > 0 else 1] += abs(shares) * price

    items = []
    details = {}
    for stock in sorted(set(by_stock) | set(trades)):
        stock_trades = trades.get(stock, [])
        buys = [t for t in stock_trades if t[2] > 0]
        consensus = _consensus(stock_trades)
        holders = sorted(e for e, s in by_stock.get(stock, []) if last in s)
        if not buys and not holders:
            continue

        close = [_round(prices[(stock, d)][1]) if (stock, d) in prices else None for d in window]
        lines = {}
        total_shares = [0] * len(window)
        total_cost = [0.0] * len(window)
        for etf_code, series in sorted(by_stock.get(stock, [])):
            line = []
            for i, d in enumerate(window):
                if d in series:
                    shares, cost = series[d]
                    line.append(_round(cost / shares))
                    total_shares[i] += shares
                    total_cost[i] += cost
                else:
                    line.append(None)
            lines[etf_code] = line
        overall = [_round(c / s) if s else None for c, s in zip(total_cost, total_shares)]

        name, industry = stock_info.get(stock, (None, None))
        latest_close = next((v for v in reversed(close) if v is not None), None)
        items.append(
            {
                "code": stock,
                "name": name or names.get(stock),
                "industry": industry,
                "close": latest_close,
                "holders": len(holders),
                "buyers": len({t[1] for t in buys}),
                "buy_count": len(buys),
                "buy_shares": round(sum(t[2] for t in buys)),
                "buy_amt": round(sum(t[2] * t[3] for t in buys)),
                "sell_amt": round(sum(-t[2] * t[3] for t in stock_trades if t[2] < 0)),
                "cost": overall[-1],
                "equal": consensus["equal"] if consensus else None,
                "weighted": consensus["weighted"] if consensus else None,
                "band": consensus["band"] if consensus else None,
            }
        )
        details[stock] = {
            "code": stock,
            "name": name or names.get(stock),
            "dates": window,
            "close": close,
            "cost_lines": lines,
            "overall_cost": overall,
            "trade_fields": ["date", "etf_code", "shares", "price"],
            "trades": [[d, e, round(s), _round(p)] for d, e, s, p in stock_trades],
            "events": [
                {"date": d, "factor": _round(f, 4)} for d, f in events.get(stock, []) if d >= window[0]
            ],
            "consensus": consensus,
        }

    items.sort(key=lambda r: r["buy_amt"], reverse=True)
    summary = {
        "date": last,
        "start": window[0],
        "days": len(window),
        "etfs": [{"etf_code": e, "etf_name": etf_names[e]} for e in etf_codes],
        "daily": [
            {"date": d, "buy_amt": round(daily[d][0]), "sell_amt": round(daily[d][1])} for d in window
        ],
        "items": items,
    }
    return summary, details


def build_summary(conn, days=COST_DAYS):
    summary, _ = compute(conn, days)
    return summary


def build_detail(conn, code, days=COST_DAYS):
    _, details = compute(conn, days)
    return details.get(code)
