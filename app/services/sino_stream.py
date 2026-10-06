"""期貨逐筆成交訂閱，組成分時走勢。

快照每 10 秒查一次，兩次之間的成交看不到，分時的量也只能用累積量相減推估。
期貨幾乎整天都在交易、成交又密，因此常駐的期貨改用訂閱：Shioaji 每有一筆
成交就推送過來，在記憶體裡組成 1 分 K，量價都是實際成交。

只訂閱固定的幾檔 (config.SINO_STREAM_CODES)，訂一次用到服務關閉，
不隨使用者切換個股而訂閱、退訂，避免頻繁切換被永豐視為過度使用。
個股與指數仍走快照。

交易時段以期交所的規則切分，而不是日曆日：

    日盤   08:45 ~ 13:45
    夜盤   15:00 ~ 次日 05:00，跨過午夜仍算同一段

記憶體裡保留最近的日盤與夜盤各一段，前端可切換日盤、夜盤，或把兩段依時間
接起來看「全日」。第一次訂閱時先以 kbars 補上這兩段已發生的分時，之後才接逐筆成交。

K 線的時間標籤與 kbars 一致，是「該分鐘結束的時刻」：09:00:xx 的成交
屬於 09:01 那一根；收盤那一筆 (13:45:00) 歸在最後一根 13:45。
"""
import logging
import threading
import time
from datetime import datetime, timedelta

from app import config
from app.fetchers import sinotrade

logger = logging.getLogger(__name__)

DAY_START = (8, 45)
DAY_END = (13, 45)
NIGHT_START = (15, 0)
NIGHT_END = (5, 0)

SESSION_LABELS = {"day": "日盤", "night": "夜盤"}

# 補分時要往前查的日數。週一早上要找得到上週五的夜盤
BOOTSTRAP_DAYS = 4

_lock = threading.Lock()
# code -> 狀態，見 _new_state
_states = {}
_started = {"ok": False, "failed_at": 0.0}


def _at(day, hm):
    return datetime(day.year, day.month, day.day, hm[0], hm[1])


def session_of(moment):
    """moment 所屬的交易時段，休市期間回傳剛結束的那一段。

    回傳 (key, kind, start, end)，key 例如 "20261006-night"，夜盤以開盤那天為準。
    """
    day = moment.date()
    hm = (moment.hour, moment.minute)
    if DAY_START <= hm <= DAY_END:
        start_day, kind = day, "day"
    elif hm >= NIGHT_START:
        start_day, kind = day, "night"
    elif hm <= NIGHT_END or hm < DAY_START:
        # 凌晨仍屬前一天開始的夜盤；05:00 到 08:45 之間顯示剛結束的夜盤
        start_day, kind = day - timedelta(days=1), "night"
    else:
        # 13:45 到 15:00 之間顯示剛結束的日盤
        start_day, kind = day, "day"

    if kind == "day":
        start, end = _at(start_day, DAY_START), _at(start_day, DAY_END)
    else:
        start = _at(start_day, NIGHT_START)
        end = _at(start_day + timedelta(days=1), NIGHT_END)
    return f"{start_day:%Y%m%d}-{kind}", kind, start, end


def in_trading_hours(moment):
    """moment 是否在交易時段內 (休市期間沒有成交是正常的，不算斷線)。

    以時段開始那天判斷是否為平日，週六凌晨因此仍算週五的夜盤。
    國定假日沒有另外排除，假日期間會被視為斷線而退回快照，不影響正確性。
    """
    _, _, start, end = session_of(moment)
    return start.weekday() < 5 and start <= moment <= end


def _bar_label(moment, end):
    """成交所屬那一根 K 棒的時間標籤 (該分鐘結束的時刻)。"""
    floor = moment.replace(second=0, microsecond=0)
    return min(floor + timedelta(minutes=1), end)


def _new_state(code):
    return {
        "code": code,
        # 時段 (key, kind, start, end) -> {標籤時刻: [close, volume]}，只留最近的日盤與夜盤各一段
        "sessions": {},
        "last": None,          # 最新一筆成交
        "last_tick_at": None,  # 收到最新一筆的本機時間
        "subscribed_at": None,
        "resubscribed_at": 0.0,
    }


def _prune(sessions):
    """只保留最近的日盤與夜盤各一段。"""
    latest = {}
    for session in sessions:
        kind = session[1]
        if kind not in latest or session[0] > latest[kind][0]:
            latest[kind] = session
    for session in list(sessions):
        if session not in latest.values():
            del sessions[session]


def _bootstrap(state):
    """以 kbars 補上最近的日盤與夜盤已經發生的分時，消耗一次 K 線額度。"""
    now = datetime.now()
    current = session_of(now)
    try:
        rows = sinotrade.fetch_kbars_between(
            state["code"], (now - timedelta(days=BOOTSTRAP_DAYS)).date(), now.date()
        )
    except Exception as exc:
        # 取不到就從空的開始，之後的逐筆成交照樣會接上
        logger.warning("期貨 %s 補分時失敗：%s", state["code"], exc)
        rows = []

    sessions = {}
    for row in rows:
        session = session_of(row["datetime"])
        # key 以「日期-day/night」組成，同一天日盤排在夜盤之前，字串比較即時間先後
        if session[0] <= current[0]:
            sessions.setdefault(session, {})[row["datetime"]] = [row["close"], row["volume"]]
    _prune(sessions)
    state["sessions"] = sessions
    logger.info(
        "期貨 %s 補分時：%s",
        state["code"],
        "、".join(f"{key} {len(bars)} 根" for (key, *_), bars in sorted(sessions.items())) or "無資料",
    )


def _on_tick(code, tick):
    if tick["simtrade"] or tick["price"] is None or tick["datetime"] is None:
        return
    moment = tick["datetime"]
    session = session_of(moment)
    with _lock:
        state = _states.get(code)
        if state is None:
            return
        sessions = state["sessions"]
        if session not in sessions:
            if sessions and session[0] < max(sessions)[0]:
                return
            # 訂閱期間進入新的時段，從第一筆成交開始累計，並淘汰同類的上一段
            sessions[session] = {}
            _prune(sessions)
        bars = sessions[session]
        label = _bar_label(moment, session[3])
        bar = bars.get(label)
        if bar is None:
            bars[label] = [tick["price"], tick["volume"]]
        else:
            bar[0] = tick["price"]
            bar[1] += tick["volume"]
        state["last"] = tick
        state["last_tick_at"] = time.time()


def ensure_started():
    """第一次用到時補分時並訂閱，之後一直保持到服務關閉。"""
    codes = config.SINO_STREAM_CODES
    if not codes or _started["ok"]:
        return
    with _lock:
        if _started["ok"] or time.time() - _started["failed_at"] < config.SINO_STREAM_RETRY_SECONDS:
            return
        try:
            for code in codes:
                state = _states.get(code) or _new_state(code)
                _bootstrap(state)
                state["subscribed_at"] = time.time()
                _states[code] = state
            # 補完分時才訂閱，逐筆成交接在 kbars 之後；中間空檔約一秒，量的誤差可忽略
            sinotrade.subscribe_future_ticks(codes, _dispatch)
            _started["ok"] = True
        except Exception as exc:
            logger.warning("期貨訂閱失敗，%d 秒後再試：%s", config.SINO_STREAM_RETRY_SECONDS, exc)
            _started["failed_at"] = time.time()


def _dispatch(tick):
    # 推送的是實際合約 (TXFJ6)，訂閱的是連續合約 (TXFR1)，以前三碼對應
    for code in _states:
        if tick["contract"].startswith(code[:3]):
            _on_tick(code, tick)
            return


def is_streamed(code):
    return code in config.SINO_STREAM_CODES


def _healthy(state, now):
    """交易時段內超過一段時間沒收到成交，視為串流中斷。"""
    if not in_trading_hours(now):
        return True
    reference = state["last_tick_at"] or state["subscribed_at"] or 0
    return time.time() - reference <= config.SINO_STREAM_STALE_SECONDS


def _try_resubscribe(state):
    """串流中斷時重新訂閱，限制頻率避免一直重試。"""
    if time.time() - state["resubscribed_at"] < config.SINO_STREAM_RETRY_SECONDS:
        return
    state["resubscribed_at"] = time.time()
    try:
        sinotrade.subscribe_future_ticks([state["code"]], _dispatch)
        logger.info("期貨 %s 串流中斷，已重新訂閱", state["code"])
    except Exception as exc:
        logger.warning("期貨 %s 重新訂閱失敗：%s", state["code"], exc)


def get_view(code):
    """訂閱中的期貨目前的分時與最新成交；尚未啟動或串流中斷時回傳 None。

    回傳 None 時呼叫端應退回快照的做法。
    """
    if not is_streamed(code):
        return None
    ensure_started()
    now = datetime.now()
    with _lock:
        state = _states.get(code)
        if state is None or not state["sessions"]:
            return None
        if not _healthy(state, now):
            _try_resubscribe(state)
            return None
        by_kind = {}
        for (key, kind, start, end), bars in state["sessions"].items():
            by_kind[kind] = {
                "kind": kind,
                "label": SESSION_LABELS[kind],
                "start": start.strftime("%Y-%m-%d %H:%M"),
                "end": end.strftime("%Y-%m-%d %H:%M"),
                "candles": [
                    {"time": label.strftime("%H:%M"), "close": close, "volume": volume}
                    for label, (close, volume) in sorted(bars.items())
                ],
            }
        if not by_kind:
            return None
        # 預設顯示目前所在的時段；假日等這一段沒有資料時，顯示最近有資料的那一段
        current = session_of(now)[1]
        if current not in by_kind or not by_kind[current]["candles"]:
            filled = [session for session, bars in state["sessions"].items() if bars]
            current = max(filled or state["sessions"])[1]
        return {
            "current": current,
            # 依時間先後排列，前端「全日」直接照順序接起來
            "sessions": sorted(by_kind.values(), key=lambda item: item["start"]),
            "last": dict(state["last"]) if state["last"] else None,
        }
