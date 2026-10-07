"""主動式 ETF 日報：訊號有多強、誰出手最準。

方法整理自 notes/ETF_STRATEGY.md 第三節，統計區共 7 個指標：

- 被買最兇、被調節最重：各股當日加減碼金額排名
- 有志一同、集體減碼：同一天被 CONSENSUS_COUNT 家以上加碼或減碼
- 資金往哪個族群跑：依產業別加總淨買賣
- 共識升溫或退潮：加碼家數與前一個揭露日比較
- 新進與清倉：持股從 0 變有、從有變 0
- 誰出手最準：近 ACCURACY_DAYS 個揭露日各 ETF 的買進，以金額加權計算至今的報酬
- 訊號分級：金額 × 家數，見 _grade

另外提供申購贖回校正：持股整批同比例變動的部分視為被動買賣，從加減碼中扣除，
做法見 etf_daily._Context.passive_factor。每份日報同時附上校正前 (raw) 與
校正後 (adjusted) 兩組數字。

深度解讀不由程式產生，存放在 data/report_notes/YYYYMMDD.md，有檔案才附上。

本機 API 與靜態匯出共用這裡的函式，兩種模式的格式一致。
"""
from collections import defaultdict

from app import config
from app.services import etf_daily

NOTES_DIR = config.DATA_DIR / "report_notes"
# 「金額大」的門檻 (元)，訊號分級用
BIG_AMOUNT = 3e8
# 有志一同、集體減碼、廣泛共識的家數門檻
CONSENSUS_COUNT = 3
# 誰出手最準的觀察期間 (揭露日數)
ACCURACY_DAYS = 5
# 誰出手最準的最低買進金額，金額太小的報酬沒有參考價值
ACCURACY_MIN_AMOUNT = 1e7
# 各清單保留的筆數
TOP_LIMIT = 15
LIST_LIMIT = 20
MODES = ("adjusted", "raw")

GRADES = {
    "broad": "廣泛共識",
    "concentrated": "集中押注",
    "quiet": "小額共識",
    "sync_sell": "同步減碼",
    "heavy_sell": "集中調節",
}
# 分級的呈現順序，越前面越值得注意
GRADE_ORDER = ["sync_sell", "broad", "concentrated", "heavy_sell", "quiet"]


def _yi(value):
    return round(value / 1e8, 2)


def read_note(date):
    """深度解讀的 Markdown 原文，沒有檔案時回傳 None。"""
    path = NOTES_DIR / f"{date}.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _grade(buy_count, buy_amount, sell_count, sell_amount):
    """金額 × 家數的訊號分級，沒有明顯訊號時回傳 None。

    賣方共識優先於買方，因為同步減碼的警戒等級高於任何買超。
    """
    if sell_count >= CONSENSUS_COUNT:
        return "sync_sell"
    if buy_count >= CONSENSUS_COUNT and buy_amount >= BIG_AMOUNT:
        return "broad"
    if buy_amount >= BIG_AMOUNT:
        return "concentrated"
    if -sell_amount >= BIG_AMOUNT:
        return "heavy_sell"
    if buy_count >= CONSENSUS_COUNT:
        return "quiet"
    return None


class _Report:
    def __init__(self, conn):
        self.ctx = etf_daily._Context(conn)
        self.ready = self.ctx.ready
        if not self.ready:
            return
        self.dates = [item["date"] for item in self.ctx.available_dates()]
        # 由新到舊，往後一格就是前一個揭露日
        self.prev_report = dict(zip(self.dates, self.dates[1:]))
        self.industry_of = {code: info[1] for code, info in self.ctx.stock_info.items()}

    def _stock(self, code):
        name, industry = self.ctx._stock_name(code)
        return {"code": code, "name": name, "industry": industry}

    def _sides(self, date, adjusted):
        """各股當日的買方與賣方彙總 {stock: {...}}。"""
        trades, _ = self.ctx.trades(date, adjusted=adjusted)
        result = {}
        for stock, rows in trades.items():
            buys = [r for r in rows if r[1] > 0]
            sells = [r for r in rows if r[1] < 0]
            result[stock] = {
                "buy_count": len(buys),
                "buy_amount": sum(r[2] for r in buys),
                "buy_etfs": [r[0] for r in sorted(buys, key=lambda r: -r[2])],
                "sell_count": len(sells),
                "sell_amount": sum(r[2] for r in sells),
                "sell_etfs": [r[0] for r in sorted(sells, key=lambda r: r[2])],
                "rows": rows,
            }
        return result

    def _row(self, stock, side, extra=None):
        row = self._stock(stock)
        row.update(
            {
                "buy_count": side["buy_count"],
                "buy_amt": _yi(side["buy_amount"]),
                "sell_count": side["sell_count"],
                "sell_amt": _yi(side["sell_amount"]),
                "net_amt": _yi(side["buy_amount"] + side["sell_amount"]),
                "buy_etfs": side["buy_etfs"],
                "sell_etfs": side["sell_etfs"],
            }
        )
        if extra:
            row.update(extra)
        return row

    def _accuracy(self, date, adjusted):
        """近 ACCURACY_DAYS 個揭露日內各 ETF 的買進，以金額加權計算到 date 收盤的報酬。"""
        index = self.dates.index(date)
        window = self.dates[index:index + ACCURACY_DAYS]
        per_etf = defaultdict(lambda: {"amount": 0.0, "value": 0.0, "stocks": defaultdict(float)})
        for day in window:
            trades, _ = self.ctx.trades(day, adjusted=adjusted)
            for stock, rows in trades.items():
                price = self.ctx.prices.get((stock, date))
                if not price:
                    continue
                close = price[1]
                for etf, shares, amount, _ in rows:
                    if shares <= 0 or amount <= 0:
                        continue
                    item = per_etf[etf]
                    item["amount"] += amount
                    item["value"] += shares * close
                    item["stocks"][stock] += amount
        result = []
        for etf, item in per_etf.items():
            if item["amount"] < ACCURACY_MIN_AMOUNT:
                continue
            top = sorted(item["stocks"].items(), key=lambda kv: -kv[1])[:3]
            result.append(
                {
                    "etf_code": etf,
                    "etf_name": self.ctx.etf_names.get(etf),
                    "buy_amt": _yi(item["amount"]),
                    "return_pct": round((item["value"] / item["amount"] - 1) * 100, 2),
                    "stock_count": len(item["stocks"]),
                    "top_stocks": [{**self._stock(code), "amt": _yi(amt)} for code, amt in top],
                }
            )
        result.sort(key=lambda r: r["return_pct"], reverse=True)
        return {"days": len(window), "from": window[-1], "items": result}

    def _mode(self, date, adjusted):
        sides = self._sides(date, adjusted)
        prev_date = self.prev_report.get(date)
        prev_sides = self._sides(prev_date, adjusted) if prev_date else {}

        buy_total = sum(s["buy_amount"] for s in sides.values())
        sell_total = sum(s["sell_amount"] for s in sides.values())

        buyers = sorted((k for k, s in sides.items() if s["buy_count"]), key=lambda k: -sides[k]["buy_amount"])
        sellers = sorted((k for k, s in sides.items() if s["sell_count"]), key=lambda k: sides[k]["sell_amount"])

        consensus_buys = sorted(
            (k for k, s in sides.items() if s["buy_count"] >= CONSENSUS_COUNT),
            key=lambda k: (-sides[k]["buy_count"], -sides[k]["buy_amount"]),
        )
        consensus_sells = sorted(
            (k for k, s in sides.items() if s["sell_count"] >= CONSENSUS_COUNT),
            key=lambda k: (-sides[k]["sell_count"], sides[k]["sell_amount"]),
        )

        # 族群：產業別淨買賣，另列買賣金額最大的個股
        industries = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "stocks": []})
        for stock, side in sides.items():
            industry = self.industry_of.get(stock) or "其他"
            item = industries[industry]
            item["buy"] += side["buy_amount"]
            item["sell"] += side["sell_amount"]
            item["stocks"].append((stock, side["buy_amount"] + side["sell_amount"]))
        industry_rows = []
        for name, item in industries.items():
            net = item["buy"] + item["sell"]
            ordered = sorted(item["stocks"], key=lambda kv: -kv[1] if net >= 0 else kv[1])
            industry_rows.append(
                {
                    "industry": name,
                    "buy_amt": _yi(item["buy"]),
                    "sell_amt": _yi(item["sell"]),
                    "net_amt": _yi(net),
                    "stock_count": len(item["stocks"]),
                    "leaders": [{**self._stock(code), "net_amt": _yi(amt)} for code, amt in ordered[:3]],
                }
            )
        industry_rows.sort(key=lambda r: r["net_amt"], reverse=True)

        # 共識升溫或退潮：只比較有前一個揭露日的情況
        warming, cooling = [], []
        if prev_date:
            for stock in set(sides) | set(prev_sides):
                now = sides.get(stock, {}).get("buy_count", 0)
                before = prev_sides.get(stock, {}).get("buy_count", 0)
                diff = now - before
                if abs(diff) < 2 and not (now >= CONSENSUS_COUNT and before == 0) and not (
                    before >= CONSENSUS_COUNT and now == 0
                ):
                    continue
                side = sides.get(stock) or {
                    "buy_count": 0, "buy_amount": 0.0, "buy_etfs": [],
                    "sell_count": 0, "sell_amount": 0.0, "sell_etfs": [],
                }
                row = self._row(stock, side, {"prev_buy_count": before, "diff": diff})
                (warming if diff > 0 else cooling).append(row)
            warming.sort(key=lambda r: (-r["diff"], -r["buy_amt"]))
            cooling.sort(key=lambda r: (r["diff"], r["sell_amt"]))

        # 新進與清倉
        new_positions, exits = [], []
        for stock, side in sides.items():
            for etf, shares, amount, kind in side["rows"]:
                if kind not in ("new", "removed"):
                    continue
                row = {**self._stock(stock), "etf_code": etf, "lots": round(shares / 1000), "amt": _yi(amount)}
                (new_positions if kind == "new" else exits).append(row)
        new_positions.sort(key=lambda r: -r["amt"])
        exits.sort(key=lambda r: r["amt"])

        # 訊號分級
        signals = []
        for stock, side in sides.items():
            grade = _grade(side["buy_count"], side["buy_amount"], side["sell_count"], side["sell_amount"])
            if grade:
                signals.append(self._row(stock, side, {"grade": grade}))
        signals.sort(key=lambda r: (GRADE_ORDER.index(r["grade"]), -abs(r["net_amt"])))

        return {
            "buy_amt": _yi(buy_total),
            "sell_amt": _yi(sell_total),
            "net_amt": _yi(buy_total + sell_total),
            "top_buys": [self._row(k, sides[k]) for k in buyers[:TOP_LIMIT]],
            "top_sells": [self._row(k, sides[k]) for k in sellers[:TOP_LIMIT]],
            "consensus_buys": [self._row(k, sides[k]) for k in consensus_buys[:LIST_LIMIT]],
            "consensus_sells": [self._row(k, sides[k]) for k in consensus_sells[:LIST_LIMIT]],
            "industries": industry_rows,
            "warming": warming[:LIST_LIMIT],
            "cooling": cooling[:LIST_LIMIT],
            "new_positions": new_positions[:LIST_LIMIT],
            "new_count": len(new_positions),
            "exits": exits[:LIST_LIMIT],
            "exit_count": len(exits),
            "signals": signals[:LIST_LIMIT * 2],
            "accuracy": self._accuracy(date, adjusted),
        }

    def _etfs(self, date):
        """各 ETF 的揭露狀況與申購贖回影響。"""
        reported = self.ctx._reported(date)
        raw, _ = self.ctx.trades(date)
        adjusted, factors = self.ctx.trades(date, adjusted=True)

        def net(trades, etf):
            return sum(r[2] for rows in trades.values() for r in rows if r[0] == etf)

        result = []
        for etf in self.ctx._listed(date):
            prev = reported.get(etf)
            item = {
                "etf_code": etf,
                "etf_name": self.ctx.etf_names.get(etf),
                "reported": prev is not None,
                "prev_date": prev,
            }
            if prev:
                change = self.ctx.unit_change(etf, date, prev)
                raw_net, active_net = net(raw, etf), net(adjusted, etf)
                item.update(
                    {
                        "unit_change_pct": None if change is None else round(change * 100, 2),
                        "passive_factor": round(factors.get(etf, 1.0), 4),
                        "raw_net_amt": _yi(raw_net),
                        "active_net_amt": _yi(active_net),
                        "passive_amt": _yi(raw_net - active_net),
                    }
                )
            result.append(item)
        return result

    def build(self, date):
        if not self.ready or date not in self.dates:
            return None
        return {
            "date": date,
            "prev_date": self.prev_report.get(date),
            "thresholds": {
                "big_amount_yi": _yi(BIG_AMOUNT),
                "consensus_count": CONSENSUS_COUNT,
                "accuracy_days": ACCURACY_DAYS,
            },
            "grades": GRADES,
            "etfs": self._etfs(date),
            "modes": {mode: self._mode(date, mode == "adjusted") for mode in MODES},
            "note": read_note(date),
        }

    def dates_payload(self):
        if not self.ready:
            return {"dates": []}
        return {
            "dates": [
                {**item, "has_note": (NOTES_DIR / f"{item['date']}.md").exists()}
                for item in self.ctx.available_dates()
            ]
        }


def build_dates(conn):
    """可查詢的日期、各日已公布的 ETF 檔數與是否有深度解讀。"""
    return _Report(conn).dates_payload()


def build_day(conn, date):
    return _Report(conn).build(date)


def build_all(conn, limit=None):
    """匯出用：一次載入後逐日計算，回傳 (dates_payload, {date: payload})。"""
    report = _Report(conn)
    dates = report.dates_payload()
    if limit:
        dates["dates"] = dates["dates"][:limit]
    days = {}
    for item in dates["dates"]:
        payload = report.build(item["date"])
        if payload is not None:
            days[item["date"]] = payload
    return dates, days
