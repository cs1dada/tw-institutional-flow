"""00631L 槓桿配置回測，產出前端「槓桿配置回測」頁的資料檔。

比較四種配置：
    純 0050      100% 0050
    純 00631L    100% 00631L，買進後不動
    5050         50% 00631L + 50% 短債，00631L 跑出 40%~60% 就再平衡
    442          40% 00631L + 40% 0050 + 20% 短債，
                 00631L 跑出 32%~48% 或短債跑出 14%~26% 就再平衡

另外計算「不再平衡」與「每年再平衡」版本，供頁面說明再平衡的必要性；
以及每月定期定額 1 萬元的結果。

資料來源為 Yahoo Finance 還原收盤價。短債以美國 1~3 年公債 ETF (SHY)
換算台幣代替，因為台灣掛牌的短債 ETF 上市太晚。00631L 在 2015 年 8 月以前的
Yahoo 資料有誤 (還原價格錯誤與單日 -33% 的錯誤跳空)，因此從 2015-09-01 開始。

用法：
    python scripts/backtest_leverage.py
輸出：
    frontend/src/data/leverage_backtest.json (隨前端一起打包)
"""
import json
from datetime import date
from pathlib import Path

import _bootstrap

_bootstrap.setup_logging()

import numpy as np
import pandas as pd
import yfinance as yf

START = "2015-09-01"
FETCH_START = "2015-06-01"
OUTPUT = Path(__file__).resolve().parent.parent / "frontend" / "src" / "data" / "leverage_backtest.json"

# 手續費 0.1425% 打 6 折；賣出另計 ETF 證交稅 0.1%
BUY_COST = 0.001425 * 0.6
SELL_COST = BUY_COST + 0.001
MONTHLY = 10000

ASSETS = ("L", "E", "B")  # 00631L、0050、短債

STRATEGIES = {
    "e100": {"target": {"E": 1.0}, "mode": "none"},
    "l100": {"target": {"L": 1.0}, "mode": "none"},
    "s5050": {"target": {"L": 0.5, "B": 0.5}, "mode": "band", "band": {"L": (0.40, 0.60)}},
    "s442": {"target": {"L": 0.4, "E": 0.4, "B": 0.2}, "mode": "band",
             "band": {"L": (0.32, 0.48), "B": (0.14, 0.26)}},
}

# 對照組：說明再平衡的必要性
VARIANTS = {
    "s5050_none": {"target": {"L": 0.5, "B": 0.5}, "mode": "none"},
    "s5050_annual": {"target": {"L": 0.5, "B": 0.5}, "mode": "annual"},
    "s442_none": {"target": {"L": 0.4, "E": 0.4, "B": 0.2}, "mode": "none"},
    "s442_annual": {"target": {"L": 0.4, "E": 0.4, "B": 0.2}, "mode": "annual"},
}

CRASHES = [
    ("2018 年", "2018-01-01", "2019-01-31"),
    ("2020/3 疫情", "2020-01-01", "2020-04-30"),
    ("2022 年", "2022-01-01", "2022-12-31"),
    ("2024/8", "2024-07-01", "2024-09-30"),
    ("2025/4 關稅", "2025-03-01", "2025-05-31"),
    ("2026/10~11", "2026-10-01", "2026-11-30"),
]


def load_returns():
    """下載價格並整理成三項資產的每日報酬 (台幣計價)。"""
    raw = yf.download(["00631L.TW", "0050.TW", "SHY", "TWD=X"], start=FETCH_START,
                      auto_adjust=True, progress=False)["Close"]
    # 匯率資料偶有錯誤跳點，與前後 21 日中位數差超過 3% 視為錯誤
    fx = raw["TWD=X"].copy()
    median = fx.rolling(21, center=True, min_periods=5).median()
    fx[(fx / median - 1).abs() > 0.03] = np.nan
    fx = fx.ffill()
    prices = pd.DataFrame({"L": raw["00631L.TW"], "E": raw["0050.TW"]}).dropna()
    prices["B"] = (raw["SHY"] * fx).reindex(prices.index).ffill()
    prices = prices.loc[START:]
    return prices.pct_change().fillna(0)


def target_weights(target):
    return np.array([target.get(k, 0.0) for k in ASSETS])


def out_of_band(weights, band):
    return any(not (lo <= weights[ASSETS.index(k)] <= hi) for k, (lo, hi) in band.items())


def run_lump(returns, spec):
    """單筆投入，期初 1 元。回傳每日淨值與再平衡次數。"""
    target = target_weights(spec["target"])
    weights = target.copy()
    value = 1.0
    values = []
    trades = 0
    last_year = None
    for day, row in returns.iterrows():
        holdings = weights * value * (1 + row[list(ASSETS)].values)
        value = holdings.sum()
        weights = holdings / value
        need = (spec["mode"] == "annual" and last_year is not None and day.year != last_year) \
            or (spec["mode"] == "band" and out_of_band(weights, spec["band"]))
        if need:
            diff = target - weights
            value *= 1 - (np.clip(diff, 0, None) * BUY_COST + np.clip(-diff, 0, None) * SELL_COST).sum()
            weights = target.copy()
            trades += 1
        last_year = day.year
        values.append(value)
    return pd.Series(values, index=returns.index), trades


def run_dca(returns, spec, sell=True):
    """每月第一個交易日投入 MONTHLY 元，新資金優先補比重偏低的資產。
    sell=False 時不賣出，只靠新資金調整比重。"""
    target = target_weights(spec["target"])
    holdings = np.zeros(len(ASSETS))
    units = 0.0
    invested = 0.0
    flows = []
    values, navs, inv = [], [], []
    last_month = None
    for day, row in returns.iterrows():
        holdings = holdings * (1 + row[list(ASSETS)].values)
        value = holdings.sum()
        if day.month != last_month:
            nav = value / units if units > 0 else 1.0
            cash = MONTHLY * (1 - BUY_COST)
            gap = np.clip(target * (value + cash) - holdings, 0, None)
            holdings = holdings + (gap / gap.sum() * cash if gap.sum() > 0 else target * cash)
            units += MONTHLY / nav
            invested += MONTHLY
            flows.append((day, -MONTHLY))
            last_month = day.month
        value = holdings.sum()
        if sell and spec["mode"] == "band" and out_of_band(holdings / value, spec["band"]):
            diff = target * value - holdings
            cost = (np.clip(diff, 0, None) * BUY_COST + np.clip(-diff, 0, None) * SELL_COST).sum()
            holdings = target * (value - cost)
        value = holdings.sum()
        values.append(value)
        navs.append(value / units)
        inv.append(invested)
    index = returns.index
    return pd.Series(values, index), pd.Series(navs, index), pd.Series(inv, index), flows


def xirr(flows, end_day, end_value):
    """以二分法求內部報酬率 (年化)。"""
    cash_flows = flows + [(end_day, end_value)]
    first = cash_flows[0][0]

    def npv(rate):
        return sum(c / (1 + rate) ** ((d - first).days / 365.25) for d, c in cash_flows)

    lo, hi = -0.9, 2.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return mid


def longest_underwater(series):
    """創新高前最長的天數。"""
    drawdown = series / series.cummax() - 1
    longest = 0
    start = None
    for day, dd in drawdown.items():
        if dd < 0:
            start = start or day
            longest = max(longest, (day - start).days)
        else:
            start = None
    return longest


def summary(series, trades, years):
    daily = series.pct_change().dropna()
    cagr = series.iloc[-1] ** (1 / years) - 1
    vol = daily.std() * np.sqrt(252)
    downside = daily[daily < 0].std() * np.sqrt(252)
    mdd = (series / series.cummax() - 1).min()
    return {
        "final": round(series.iloc[-1], 4),
        "cagr": round(cagr, 4),
        "vol": round(vol, 4),
        "mdd": round(mdd, 4),
        "sharpe": round(cagr / vol, 2),
        "sortino": round(cagr / downside, 2),
        "calmar": round(cagr / abs(mdd), 2),
        "underwater_days": longest_underwater(series),
        "rebalances": trades,
    }


def main():
    returns = load_returns()
    first, last = returns.index[0], returns.index[-1]
    years = (last - first).days / 365.25

    curves = {}
    stats = {}
    for key, spec in {**STRATEGIES, **VARIANTS}.items():
        curves[key], trades = run_lump(returns, spec)
        stats[key] = summary(curves[key], trades, years)
    main_keys = list(STRATEGIES)
    equity = pd.DataFrame({k: curves[k] for k in main_keys})

    # 週資料給圖表用，最後一天一定保留
    weekly = equity.resample("W-FRI").last().dropna()
    weekly.loc[last] = equity.iloc[-1]
    weekly = weekly[~weekly.index.duplicated(keep="last")].sort_index()

    yearly_end = equity.resample("YE").last()
    yearly = yearly_end.pct_change()
    yearly.iloc[0] = yearly_end.iloc[0] - 1

    crashes = []
    for label, a, b in CRASHES:
        seg = equity.loc[a:b]
        if seg.empty:
            continue
        crashes.append({"label": label, **{k: round((seg[k] / seg[k].cummax() - 1).min(), 4) for k in main_keys}})

    holding = {}
    for years_held in (1, 3, 5):
        n = 252 * years_held
        total = (equity.shift(-n) / equity - 1).dropna()
        annual = (1 + total) ** (1 / years_held) - 1
        holding[str(years_held)] = {
            k: {
                "worst": round(annual[k].min(), 4),
                "median": round(annual[k].median(), 4),
                "best": round(annual[k].max(), 4),
                "loss_prob": round((total[k] < 0).mean(), 4),
                "beat_0050": None if k == "e100" else round((total[k] > total["e100"]).mean(), 4),
            }
            for k in main_keys
        }

    dca = {}
    dca_specs = {k: (STRATEGIES[k], True) for k in main_keys}
    dca_specs["s5050_nosell"] = (STRATEGIES["s5050"], False)
    dca_specs["s442_nosell"] = (STRATEGIES["s442"], False)
    for key, (spec, sell) in dca_specs.items():
        value, nav, inv, flows = run_dca(returns, spec, sell)
        dca[key] = {
            "invested": round(inv.iloc[-1]),
            "final": round(value.iloc[-1]),
            "multiple": round(value.iloc[-1] / inv.iloc[-1], 2),
            "xirr": round(xirr(flows, last, value.iloc[-1]), 4),
            "nav_mdd": round((nav / nav.cummax() - 1).min(), 4),
            "max_loss_amount": round((value - value.cummax()).min()),
            "worst_book": round((value / inv - 1).min(), 4),
        }

    payload = {
        "generated_at": date.today().isoformat(),
        "start": first.strftime("%Y-%m-%d"),
        "end": last.strftime("%Y-%m-%d"),
        "years": round(years, 1),
        "monthly": MONTHLY,
        "stats": stats,
        "curve": {
            "dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
            **{k: [round(v, 4) for v in weekly[k]] for k in main_keys},
        },
        "yearly": [
            {"year": int(y.year), **{k: round(yearly.loc[y, k], 4) for k in main_keys}}
            for y in yearly.index
        ],
        "crashes": crashes,
        "holding": holding,
        "dca": dca,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"已輸出 {OUTPUT} ({first.date()} ~ {last.date()}，{years:.1f} 年)")
    for key in main_keys:
        s = stats[key]
        print(f"  {key:6s} 年化 {s['cagr']:.1%}  最大回撤 {s['mdd']:.1%}  再平衡 {s['rebalances']} 次")


if __name__ == "__main__":
    main()
