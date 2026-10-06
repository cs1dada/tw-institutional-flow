"""主動式 ETF 每日榜單：被買最兇、被賣最重、最擁擠。

方法整理自 notes/ETF_STRATEGY.md 第二節：

- 加減碼：同一檔 ETF 相鄰兩個揭露日的股數差。前一日為零、當日大於零為新進；
  增加為加碼；減少為減碼；歸零為出清
- 公司行動還原：分割、股票股利、減資造成的股數跳動，沿用 etf_cost 的偵測與還原
- 推估金額：股數變化 × 當日 VWAP (成交金額 ÷ 成交股數)
- 被買最兇、被賣最重：買方與賣方分開加總，同一檔股票可能同時出現在兩張榜單
- 最擁擠：被最多檔 ETF 同時持有的個股

每列另附全市場的外資、投信買賣超張數，用來比對主動式 ETF 與其他法人的方向。
「投信」包含所有投信，不只主動式 ETF，兩者不可加總。

限制：
- 只計算台股：以海外股票為主的 ETF 持股基準日跟著海外市場，不納入
- 未扣除申購贖回造成的被動買賣
- ETF 漏抓某一天時，下一個揭露日的變動會包含多天的累積

本機 API 與靜態匯出共用這裡的函式，兩種模式的格式一致。
"""
from collections import defaultdict

from app.services import etf_cost

# 各榜單保留的名次
RANK_LIMIT = 30
SHARES_PER_LOT = 1000


def _round(value, digits=2):
    return None if value is None else round(value, digits)


def _latest_on_or_before(snap_dates, date):
    """排序好的快照日期中，最後一個不晚於 date 的日期。"""
    result = None
    for d in snap_dates:
        if d > date:
            break
        result = d
    return result


def _inst_flows(conn, date):
    """當日全市場的外資與投信買賣超股數。"""
    return {
        r["code"]: (r["foreign_net"], r["trust_net"])
        for r in conn.execute(
            "SELECT code, foreign_net, trust_net FROM inst_trade WHERE date = ?", (date,)
        )
    }


def _lots(shares):
    return None if shares is None else round(shares / SHARES_PER_LOT)


class _Context:
    """一次載入全部快照，之後可逐日計算榜單。"""

    def __init__(self, conn):
        self.conn = conn
        self.etf_codes = etf_cost.domestic_etfs(conn)
        self.ready = bool(self.etf_codes)
        if not self.ready:
            return
        all_dates, holdings, prices, names, _ = etf_cost.load_snapshots(conn, self.etf_codes)
        self.holdings = holdings
        self.prices = prices
        self.names = names
        self.etf_names = etf_cost.etf_names(conn, self.etf_codes)
        self.snap_dates = {etf: sorted(snaps) for etf, snaps in holdings.items()}
        self.stock_info = {
            r["code"]: (r["name"], r["industry"])
            for r in conn.execute("SELECT code, name, industry FROM stock_info")
        }
        last = max(dates[-1] for dates in self.snap_dates.values())
        self.trade_dates = [d for d in all_dates if d <= last]
        self.prev_trade = {d: p for p, d in zip(self.trade_dates, self.trade_dates[1:])}

    def available_dates(self):
        """至少一檔 ETF 當日有快照、且有前一個快照可比對的交易日，由新到舊。"""
        if not self.ready:
            return []
        result = []
        for date in reversed(self.trade_dates):
            reported = self._reported(date)
            if reported:
                result.append(
                    {"date": date, "reported": len(reported), "listed": len(self._listed(date))}
                )
        return result

    def _listed(self, date):
        """當日已經有持股資料 (已上市) 的 ETF。"""
        return [e for e in self.etf_codes if self.snap_dates[e] and self.snap_dates[e][0] <= date]

    def _reported(self, date):
        """當日有快照、且有前一個快照可比對的 ETF，回傳 {etf: 前一個快照日}。"""
        result = {}
        for etf in self.etf_codes:
            dates = self.snap_dates[etf]
            if date in self.holdings[etf] and dates[0] < date:
                result[etf] = max(d for d in dates if d < date)
        return result

    def _holding_map(self, date):
        """各 ETF 截至 date 最新快照的持股 {stock: {etf: shares}}。"""
        result = defaultdict(dict)
        if date is None:
            return result
        for etf in self.etf_codes:
            snap = _latest_on_or_before(self.snap_dates[etf], date)
            if snap is None:
                continue
            for stock, shares in self.holdings[etf][snap].items():
                if shares > 0:
                    result[stock][etf] = shares
        return result

    def _stock_name(self, stock):
        name, industry = self.stock_info.get(stock, (None, None))
        return name or self.names.get(stock), industry

    def build(self, date):
        """單一交易日的三張榜單，無法比對時回傳 None。"""
        if not self.ready:
            return None
        reported = self._reported(date)
        if not reported:
            return None

        # stock -> [(etf, shares, amount, type)]
        trades = defaultdict(list)
        for etf, prev_date in reported.items():
            current = self.holdings[etf][date]
            previous = self.holdings[etf][prev_date]
            for stock in set(current) | set(previous):
                before = previous.get(stock, 0)
                after = current.get(stock, 0)
                delta = after - before
                # 還原後的股數可能帶小數，不足一股的差異視為沒有變動
                if abs(delta) < 1:
                    continue
                if before <= 0:
                    kind = "new"
                elif after <= 0:
                    kind = "removed"
                else:
                    kind = "add" if delta > 0 else "reduce"
                price = self.prices.get((stock, date))
                amount = delta * price[0] if price else 0.0
                trades[stock].append((etf, delta, amount, kind))

        flows = _inst_flows(self.conn, date)

        def side_row(stock, rows, opposite):
            name, industry = self._stock_name(stock)
            foreign, trust = flows.get(stock, (None, None))
            price = self.prices.get((stock, date))
            return {
                "code": stock,
                "name": name,
                "industry": industry,
                "close": _round(price[1]) if price else None,
                "vwap": _round(price[0]) if price else None,
                "etf_count": len(rows),
                "new_count": sum(1 for r in rows if r[3] == "new"),
                "shares": round(sum(r[1] for r in rows)),
                "amount": round(sum(r[2] for r in rows)),
                "opposite_count": len(opposite),
                "opposite_amount": round(sum(r[2] for r in opposite)),
                "foreign_lots": _lots(foreign),
                "trust_lots": _lots(trust),
                "etfs": [
                    {"etf_code": e, "shares": round(s), "amount": round(a), "type": k}
                    for e, s, a, k in sorted(rows, key=lambda r: abs(r[2]), reverse=True)
                ],
            }

        buys, sells = [], []
        buy_total = sell_total = 0.0
        for stock, rows in trades.items():
            buy_rows = [r for r in rows if r[1] > 0]
            sell_rows = [r for r in rows if r[1] < 0]
            if buy_rows:
                buys.append(side_row(stock, buy_rows, sell_rows))
                buy_total += sum(r[2] for r in buy_rows)
            if sell_rows:
                sells.append(side_row(stock, sell_rows, buy_rows))
                sell_total += sum(r[2] for r in sell_rows)
        buys.sort(key=lambda r: r["amount"], reverse=True)
        sells.sort(key=lambda r: r["amount"])

        today = self._holding_map(date)
        before = self._holding_map(self.prev_trade.get(date))
        crowded = []
        for stock, held in today.items():
            name, industry = self._stock_name(stock)
            foreign, trust = flows.get(stock, (None, None))
            price = self.prices.get((stock, date))
            shares = sum(held.values())
            crowded.append(
                {
                    "code": stock,
                    "name": name,
                    "industry": industry,
                    "close": _round(price[1]) if price else None,
                    "holders": len(held),
                    "prev_holders": len(before.get(stock, {})),
                    "shares": round(shares),
                    "market_value": round(shares * price[1]) if price else None,
                    "foreign_lots": _lots(foreign),
                    "trust_lots": _lots(trust),
                    "etfs": sorted(held),
                }
            )
        crowded.sort(key=lambda r: (r["holders"], r["market_value"] or 0), reverse=True)

        listed = self._listed(date)
        return {
            "date": date,
            "etfs": [
                {
                    "etf_code": e,
                    "etf_name": self.etf_names.get(e),
                    "reported": e in reported,
                    "prev_date": reported.get(e),
                }
                for e in listed
            ],
            "buy_amt": round(buy_total),
            "sell_amt": round(-sell_total),
            "buys": buys[:RANK_LIMIT],
            "sells": sells[:RANK_LIMIT],
            "crowded": crowded[:RANK_LIMIT],
        }


def build_dates(conn):
    """可查詢的日期與各日已公布的 ETF 檔數。"""
    return {"dates": _Context(conn).available_dates()}


def build_day(conn, date):
    return _Context(conn).build(date)


def build_all(conn, limit=None):
    """匯出用：一次載入後逐日計算，回傳 (dates_payload, {date: payload})。"""
    ctx = _Context(conn)
    dates = ctx.available_dates()
    if limit:
        dates = dates[:limit]
    days = {}
    for item in dates:
        payload = ctx.build(item["date"])
        if payload is not None:
            days[item["date"]] = payload
    return {"dates": dates}, days
