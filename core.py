#!/usr/bin/env python3
"""
ICT/SMC Backtest v50.2-h1-live — core module.

Changes vs v50.1-diag:
- add diagnostic CLI param: no_dw_levels
- add experimental live filter: require_prev_ldn_sweep
- live filter blocks only trade entry attempts
- does not block bar processing / sweep diagnostics
- adds debug counter: h1_blocked_entries
"""
import os
from datetime import timedelta
import pandas as pd
import numpy as np

__version__ = "v50.2-h1-live"

# ============================================================
# CONFIG
# ============================================================
DATA_DIR = "./data"
SYMBOL_MAP = {
    "EURUSD": "EURUSD_M5.csv",
    "GBPUSD": "GBPUSD_M15.csv",
    "BTCUSD": "BTCUSD_M15.csv",
    "ETHUSD": "ETHUSD_M15.csv",
}
DATA_TZ_OFFSET_HOURS = 3
PIP_SIZE = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "BTCUSD": 1.0,
    "ETHUSD": 0.1,
}
CONTRACT_SIZE = {
    "EURUSD": 100_000,
    "GBPUSD": 100_000,
    "BTCUSD": 1,
    "ETHUSD": 1,
}
LOOKBACK_BY_TF = {
    "M1": 120,
    "M5": 48,
    "M15": 48,
    "M30": 48,
    "H1": 24,
    "H4": 12,
    "D1": 5,
}
TF_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}
ALFAFOREX_SPECS = {
    "EURUSD": {
        "spread_pip": 1.4,
        "limit_stop_level_pip": 0.7,
        "swap_long_pip": -0.70,
        "swap_short_pip": 0.00,
        "contract_size": 100_000,
    },
    "GBPUSD": {
        "spread_pip": 2.1,
        "limit_stop_level_pip": 1.1,
        "swap_long_pip": -0.55,
        "swap_short_pip": -0.25,
        "contract_size": 100_000,
    },
}
ALFAFOREX_OPEN_HOUR_MSK = 2
ALFAFOREX_CLOSE_HOUR_MSK = 23
ALFAFOREX_CLOSE_MIN_MSK = 55

MIN_TRADES_FOR_VALID = 1
FULL_TRADES_FOR_SCORE = 3
SCORE_PENALTY_POWER = 1.5
PF_CAP = 5.0
DEFAULT_LOT = 0.1

KZ_PRELONDON_START_MSK = 7
KZ_PRELONDON_END_MSK = 9
KZ_LONDON_START_MSK = 9
KZ_LONDON_END_MSK = 12
KZ_NY_START_MSK = 15
KZ_NY_END_MSK = 18

MAX_USES_PER_LEVEL = 2
LIMIT_VALID_BARS = 10
BOS_MIN_BREAK_PIP = 2.0
CHOCH_WAIT_BARS = 20
DEFAULT_CHOCH_LOOKBACK = 20
MAX_SL_PER_DAY = 2
MAX_ORDERS_PER_ENTRY = 2
ENTRY_TYPE = "fvg"
LIMIT_DELAY_BARS = 0
MIN_SL_REALISTIC_PIP = 20
MAX_SL_REALISTIC_PIP = 60
MIN_RR = 1.5
MAX_RR = 2.5
RR_STEP = 0.5
SL_BUFFER_PIP_RANGE = (5, 20)
MIN_SL_PIP_RANGE = (5, 12)
DEFAULT_FVG_SELECT = "first"
DEFAULT_FVG_ENTRY_EDGE = "mid"
DEFAULT_CHOCH_MODE = "swing"
DEFAULT_SIGNAL_MAX_AGE_BARS = 60
DEFAULT_BOS_COOLDOWN_BARS = 3
DEFAULT_SWEEP_PRIORITY_BARS = 20
DEFAULT_SWEEP_ATTEMPT_COOLDOWN_BARS = 1
DEFAULT_MAX_FVG_AGE_BARS = 12
DEFAULT_MAX_SPREAD_PCT_OF_SL = 0.12
DEFAULT_MAX_SL_REVERSAL_PIP = 25
DEFAULT_FORCE_CLOSE_EOD = False

IDL_IDH_NAMES = {"BOS_IDL", "BOS_IDH"}
LEVEL_PRIORITY = {
    "PDH": 1, "PDL": 1,
    "PWH": 2, "PWL": 2,
    "PMH": 3, "PML": 3,
    "AsianH": 4, "AsianL": 4,
    "LondonH": 5, "LondonL": 5,
    "NYH": 6, "NYL": 6,
}
_PRECOMPUTE_CACHE = {}


def get_level_priority(name: str) -> int:
    if name in LEVEL_PRIORITY:
        return LEVEL_PRIORITY[name]
    if name.startswith("BOS_"):
        return 10
    return 99


def fmt_msk(ts) -> str:
    if ts is None or pd.isna(ts):
        return "—"
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def fmt_msk_short(ts, base_date) -> str:
    if ts is None or pd.isna(ts):
        return "—"
    msk = pd.Timestamp(ts) + pd.Timedelta(hours=3)
    if msk.date() == base_date:
        return msk.strftime("%H:%M")
    return msk.strftime("%Y-%m-%d %H:%M")


def is_weekend(day_date) -> bool:
    return pd.Timestamp(day_date).weekday() >= 5


# ============================================================
# SESSION SWEEP DIAGNOSTICS
# ============================================================
SESSION_LDN_START_MSK = 9
SESSION_LDN_END_MSK = 12
SESSION_NY_START_MSK = 15
SESSION_NY_END_MSK = 18


def session_from_msk_hour(hour_msk: int) -> str:
    if SESSION_LDN_START_MSK <= hour_msk < SESSION_LDN_END_MSK:
        return "LDN"
    if SESSION_NY_START_MSK <= hour_msk < SESSION_NY_END_MSK:
        return "NY"
    return "OTHER"


def register_sweep_event(
    event_day,
    event_hour_msk: int,
    level_name: str,
    level_price: float,
    is_upper: bool,
    counted_uids: set,
    day_stats: dict,
) -> None:
    session = session_from_msk_hour(event_hour_msk)
    if session == "OTHER":
        return

    uid = (
        event_day,
        session,
        str(level_name),
        round(float(level_price), 8),
        bool(is_upper),
    )
    if uid in counted_uids:
        return
    counted_uids.add(uid)

    d = day_stats.setdefault(event_day, {"LDN": 0, "NY": 0})
    d[session] += 1


# ============================================================
# 1. DATA LOAD
# ============================================================
def load_data(symbol: str, start: str, end: str,
              timeframe: str = "M5",
              data_file: str = None) -> pd.DataFrame:
    if data_file:
        path = data_file
    else:
        if symbol not in SYMBOL_MAP:
            raise ValueError(f"Unknown symbol: {symbol}")
        path = os.path.join(DATA_DIR, SYMBOL_MAP[symbol])

    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    print(f"Загрузка {symbol} ({timeframe}) из {path}...")
    print(f"  Часовой пояс данных: MSK (UTC+{DATA_TZ_OFFSET_HOURS}) → UTC")

    df = pd.read_csv(path, parse_dates=["datetime"])
    required_cols = {"datetime", "open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")

    df = df.rename(columns={"datetime": "time"})
    df = df.sort_values("time").reset_index(drop=True)
    df["time"] = df["time"] - pd.Timedelta(hours=DATA_TZ_OFFSET_HOURS)
    df["time"] = df["time"].dt.tz_localize("UTC")
    df = df[df["volume"] > 0].reset_index(drop=True)

    if len(df) > 1:
        median_delta = df["time"].diff().median()
        median_minutes = median_delta.total_seconds() / 60.0
        expected_minutes = TF_MINUTES.get(timeframe)
        print(f"  Обнаруженный шаг данных: ~{median_minutes:.1f} мин")
        if expected_minutes is not None:
            tolerance = max(1.0, expected_minutes * 0.25)
            if abs(median_minutes - expected_minutes) > tolerance:
                print(
                    f"  ⚠️  ВНИМАНИЕ: указан timeframe={timeframe} "
                    f"(ожидается ~{expected_minutes} мин), "
                    f"но реальный шаг данных ~{median_minutes:.1f} мин. "
                    f"Скрипт не делает ресемплинг."
                )

    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    if start_ts >= end_ts:
        raise ValueError(f"start ({start}) >= end ({end})")

    df = df[(df["time"] >= start_ts) & (df["time"] <= end_ts)].reset_index(drop=True)
    if len(df) == 0:
        full_df = pd.read_csv(path, usecols=["datetime"])
        raise ValueError(
            "\nНе найдено свечей в периоде "
            f"{start} — {end} (UTC).\n"
            f"Доступно (MSK): {full_df['datetime'].iloc[0]} — "
            f"{full_df['datetime'].iloc[-1]}"
        )

    print(f"  Итог: {len(df):,} свечей (UTC) | "
          f"{df['time'].iloc[0]} — {df['time'].iloc[-1]}")
    return df


# ============================================================
# 2. PRECOMPUTE LEVELS
# ============================================================
def _session_maps(df: pd.DataFrame, mask: pd.Series):
    grp = df[mask].groupby("date").agg(
        high=("high", "max"),
        low=("low", "min")
    )
    if grp.empty:
        return {}, {}
    return grp["high"].to_dict(), grp["low"].to_dict()


def precompute_levels(df: pd.DataFrame) -> pd.DataFrame:
    print("  Предрасчёт уровней ликвидности (все времена — UTC)...")
    df = df.copy()
    df["date"] = df["time"].dt.date
    df["hour"] = df["time"].dt.hour
    df["year_week"] = df["time"].dt.strftime("%Y-%W")
    df["year_month"] = df["time"].dt.strftime("%Y-%m")

    day_high = df.groupby("date")["high"].max().to_dict()
    day_low = df.groupby("date")["low"].min().to_dict()
    week_high = df.groupby("year_week")["high"].max().to_dict()
    week_low = df.groupby("year_week")["low"].min().to_dict()
    month_high = df.groupby("year_month")["high"].max().to_dict()
    month_low = df.groupby("year_month")["low"].min().to_dict()

    asian_high_map, asian_low_map = _session_maps(df, df["hour"] < 8)
    london_high_map, london_low_map = _session_maps(df, (df["hour"] >= 6) & (df["hour"] < 9))
    ny_high_map, ny_low_map = _session_maps(df, (df["hour"] >= 12) & (df["hour"] < 15))

    df["day_high"] = df["date"].map(day_high)
    df["day_low"] = df["date"].map(day_low)
    df["week_high"] = df["year_week"].map(week_high)
    df["week_low"] = df["year_week"].map(week_low)
    df["month_high"] = df["year_month"].map(month_high)
    df["month_low"] = df["year_month"].map(month_low)
    df["asian_high"] = df["date"].map(asian_high_map)
    df["asian_low"] = df["date"].map(asian_low_map)
    df["london_high"] = df["date"].map(london_high_map)
    df["london_low"] = df["date"].map(london_low_map)
    df["ny_high"] = df["date"].map(ny_high_map)
    df["ny_low"] = df["date"].map(ny_low_map)

    df["idl_dyn"] = np.nan
    df["idh_dyn"] = np.nan

    for date, group in df.groupby("date"):
        idx = group.index
        df.loc[idx, "idl_dyn"] = group["low"].cummin().shift(1)
        df.loc[idx, "idh_dyn"] = group["high"].cummax().shift(1)

    return df


# ============================================================
# 3. PRECOMPUTE CHOCH / FVG
# ============================================================
def precompute_indicators(df: pd.DataFrame, choch_lookback: int, choch_mode: str) -> dict:
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    is_swing_high = np.zeros(n, dtype=bool)
    is_swing_low = np.zeros(n, dtype=bool)

    for k in range(1, n - 1):
        if high[k] > high[k - 1] and high[k] > high[k + 1]:
            is_swing_high[k] = True
        if low[k] < low[k - 1] and low[k] < low[k + 1]:
            is_swing_low[k] = True

    choch_signal = np.zeros(n, dtype=np.int8)

    if choch_mode == "swing":
        last_high = 0.0
        last_low = 0.0
        has_high = False
        has_low = False

        for i in range(n):
            if i > 0:
                if is_swing_high[i - 1]:
                    last_high = high[i - 1]
                    has_high = True
                if is_swing_low[i - 1]:
                    last_low = low[i - 1]
                    has_low = True

            if has_high and close[i] > last_high:
                choch_signal[i] = 1
            elif has_low and close[i] < last_low:
                choch_signal[i] = -1
    else:
        for i in range(n):
            start = max(0, i - choch_lookback)
            count_high = 0
            count_low = 0
            last_high = 0.0
            last_low = 0.0
            has_high = False
            has_low = False

            for k in range(start, i):
                if is_swing_high[k]:
                    count_high += 1
                    last_high = high[k]
                    has_high = True
                if is_swing_low[k]:
                    count_low += 1
                    last_low = low[k]
                    has_low = True

            if count_high >= 1 and has_high and close[i] > last_high:
                choch_signal[i] = 1
            elif count_low >= 1 and has_low and close[i] < last_low:
                choch_signal[i] = -1

    fvg_top_upper = np.full(n, np.nan, dtype=float)
    fvg_bot_upper = np.full(n, np.nan, dtype=float)
    fvg_size_upper = np.zeros(n, dtype=float)
    fvg_top_lower = np.full(n, np.nan, dtype=float)
    fvg_bot_lower = np.full(n, np.nan, dtype=float)
    fvg_size_lower = np.zeros(n, dtype=float)

    for k in range(1, n - 1):
        if low[k - 1] > high[k + 1]:
            top = low[k - 1]
            bot = high[k + 1]
            size = top - bot
            fvg_top_upper[k] = top
            fvg_bot_upper[k] = bot
            fvg_size_upper[k] = size

        if high[k - 1] < low[k + 1]:
            top = low[k + 1]
            bot = high[k - 1]
            size = top - bot
            fvg_top_lower[k] = top
            fvg_bot_lower[k] = bot
            fvg_size_lower[k] = size

    return {
        "choch_signal": choch_signal,
        "fvg_top_upper": fvg_top_upper,
        "fvg_bot_upper": fvg_bot_upper,
        "fvg_size_upper": fvg_size_upper,
        "fvg_top_lower": fvg_top_lower,
        "fvg_bot_lower": fvg_bot_lower,
        "fvg_size_lower": fvg_size_lower,
    }


def get_precomputed(df: pd.DataFrame, choch_lookback: int, choch_mode: str) -> dict:
    if len(df) == 0:
        raise ValueError("Empty DataFrame for precompute_indicators")
    key = (
        len(df),
        str(df["time"].iloc[0]),
        str(df["time"].iloc[-1]),
        int(choch_lookback),
        str(choch_mode),
    )
    if key not in _PRECOMPUTE_CACHE:
        _PRECOMPUTE_CACHE[key] = precompute_indicators(df, choch_lookback, choch_mode)
    return _PRECOMPUTE_CACHE[key]


def find_choch_in_window_pre(choch_signal: np.ndarray,
                             start_idx: int,
                             is_upper: bool,
                             max_wait: int,
                             strict_after: bool,
                             current_idx: int,
                             choch_mode: str = "swing"):
    begin = start_idx + 1 if strict_after else start_idx
    last_allowed = current_idx if choch_mode == "swing" else current_idx - 1
    end = min(start_idx + max_wait, last_allowed, len(choch_signal) - 1)
    if begin > end:
        return None, 0

    for k in range(begin, end + 1):
        s = int(choch_signal[k])
        if is_upper and s == -1:
            return k, -1
        if (not is_upper) and s == 1:
            return k, 1
    return None, 0


def find_fvg_after_idx_pre(pre: dict,
                           start_idx: int,
                           is_upper: bool,
                           lookback: int,
                           current_idx: int,
                           select: str = "first",
                           min_size: float = 0.0):
    n = len(pre["fvg_size_upper"])
    end = min(start_idx + lookback, current_idx - 1, n - 2)
    if end <= start_idx:
        return None, None

    if is_upper:
        tops = pre["fvg_top_upper"]
        bots = pre["fvg_bot_upper"]
        sizes = pre["fvg_size_upper"]
    else:
        tops = pre["fvg_top_lower"]
        bots = pre["fvg_bot_lower"]
        sizes = pre["fvg_size_lower"]

    if select == "first":
        for k in range(start_idx + 1, end + 1):
            s = sizes[k]
            if s >= min_size and not np.isnan(tops[k]):
                return (tops[k], bots[k]), k
        return None, None

    best_size = 0.0
    best_idx = None
    for k in range(start_idx + 1, end + 1):
        s = sizes[k]
        if s >= min_size and s > best_size:
            best_size = s
            best_idx = k

    if best_idx is None:
        return None, None
    return (tops[best_idx], bots[best_idx]), best_idx


# ============================================================
# 4. STRATEGY FUNCTIONS
# ============================================================
def find_sweep_arr(high_arr, low_arr, close_arr, i, level, is_upper, buffer_abs, lookback):
    start = max(0, i - lookback)
    best_idx = None
    best_extreme = None

    if is_upper:
        threshold = level + buffer_abs
        for k in range(start, i + 1):
            if high_arr[k] > threshold and close_arr[k] < threshold:
                if best_extreme is None or high_arr[k] > best_extreme:
                    best_extreme = high_arr[k]
                    best_idx = k
    else:
        threshold = level - buffer_abs
        for k in range(start, i + 1):
            if low_arr[k] < threshold and close_arr[k] > threshold:
                if best_extreme is None or low_arr[k] < best_extreme:
                    best_extreme = low_arr[k]
                    best_idx = k

    return best_idx


def get_killzone(hour_msk, params):
    if not params.get("use_kz", False):
        return True

    in_prelondon = (
        params.get("kz_prelondon_on", False)
        and params["kz_prelondon_start_msk"] <= hour_msk < params["kz_prelondon_end_msk"]
    )
    in_london = (
        params.get("kz_london_on", True)
        and params["kz_london_start_msk"] <= hour_msk < params["kz_london_end_msk"]
    )
    in_ny = (
        params.get("kz_ny_on", True)
        and params["kz_ny_start_msk"] <= hour_msk < params["kz_ny_end_msk"]
    )
    return in_prelondon or in_london or in_ny


def to_msk_hour(hour_utc: int) -> int:
    return (hour_utc + 3) % 24


def try_limit_order(high_arr, low_arr, placed_idx, entry, is_upper, valid_bars, n):
    start = placed_idx + 1
    end = min(start + valid_bars, n)
    for k in range(start, end):
        if is_upper:
            if high_arr[k] >= entry:
                return k
        else:
            if low_arr[k] <= entry:
                return k
    return None


def simulate_trade_idx(high_arr, low_arr, close_arr, msk_dates,
                       start_idx, entry, sl, tp, is_upper,
                       max_bars, n, force_close_eod=False):
    end = min(start_idx + max_bars, n)

    if force_close_eod and msk_dates is not None:
        if start_idx + 1 < n and msk_dates[start_idx + 1] != msk_dates[start_idx]:
            return 0, start_idx

    for k in range(start_idx + 1, end):
        if is_upper:
            if high_arr[k] >= sl:
                return -1, k
            if low_arr[k] <= tp:
                return 1, k
        else:
            if low_arr[k] <= sl:
                return -1, k
            if high_arr[k] >= tp:
                return 1, k

        if force_close_eod and msk_dates is not None:
            if k + 1 < n and msk_dates[k + 1] != msk_dates[k]:
                return 0, k

    return None, None


def compute_profit(result, entry, sl, tp, is_upper, contract_size, lot,
                   spread_abs, swap_abs, exit_price=None):
    if result == 1:
        move = abs(tp - entry)
        profit = move * contract_size * lot
    elif result == -1:
        move = abs(sl - entry)
        profit = -move * contract_size * lot
    else:
        if exit_price is None:
            exit_price = entry
        move = (exit_price - entry) if not is_upper else (entry - exit_price)
        profit = move * contract_size * lot

    profit -= spread_abs * contract_size * lot
    profit += swap_abs * contract_size * lot
    return profit


# ============================================================
# 5. DEDUPLICATION
# ============================================================
def deduplicate_levels(levels, pip_size):
    if not levels:
        return levels, 0

    by_price = {}
    for name, price, is_upper in levels:
        price_key = (round(price / pip_size), is_upper)
        by_price.setdefault(price_key, []).append((name, price, is_upper))

    deduped = []
    cnt = 0
    for group in by_price.values():
        if len(group) == 1:
            deduped.append(group[0])
        else:
            group.sort(key=lambda x: get_level_priority(x[0]))
            deduped.append(group[0])
            cnt += len(group) - 1

    return deduped, cnt


def release_sweep_block(key, pending_sweeps, sweep_block_until, sweep_block_owner):
    p = pending_sweeps.get(key)
    if p is None:
        return
    d = p.get("block_dir")
    if d is not None and sweep_block_owner.get(d) == key:
        sweep_block_until[d] = -10**9
        sweep_block_owner[d] = None


# ============================================================
# 6. OPEN TRADE
# ============================================================
def try_open_trade(i, name, level, is_upper, source_type,
                   source_idx, source_extreme,
                   high_arr, low_arr, close_arr, times, msk_dates,
                   params, pip_size, contract_size,
                   min_fvg_abs, sl_buffer_abs, min_sl_abs,
                   min_sl_realistic_abs, max_sl_realistic_abs,
                   limit_stop_pip, spread_abs, swap_long_pip, swap_short_pip,
                   used_entries, max_orders_per_entry,
                   limit_bars, stats, pre,
                   signal_max_age):
    if i - source_idx > signal_max_age:
        stats["stale_signal"] += 1
        return None, "stale_signal"

    choch_idx, _ = find_choch_in_window_pre(
        pre["choch_signal"],
        source_idx,
        is_upper,
        max_wait=params.get("choch_wait_bars", CHOCH_WAIT_BARS),
        strict_after=params.get("choch_strict_after", False),
        current_idx=i,
        choch_mode=params.get("choch_mode", DEFAULT_CHOCH_MODE),
    )
    if choch_idx is None:
        stats["choch_not_found"] += 1
        return None, "choch_not_found"

    stats["choch_ok"] += 1

    if i - choch_idx < 2:
        stats["fvg_not_ready"] += 1
        return None, "fvg_not_ready"

    fvg, fvg_idx = find_fvg_after_idx_pre(
        pre,
        choch_idx,
        is_upper,
        params["fvg_lookback"],
        current_idx=i,
        select=params.get("fvg_select", DEFAULT_FVG_SELECT),
        min_size=min_fvg_abs,
    )
    if fvg is None:
        stats["fvg_not_found"] += 1
        return None, "fvg_not_found"

    max_fvg_age = params.get("max_fvg_age_bars", DEFAULT_MAX_FVG_AGE_BARS)
    if i - fvg_idx > max_fvg_age:
        stats["fvg_too_old"] += 1
        return None, "fvg_too_old"

    stats["fvgs"] += 1

    edge = params.get("fvg_entry_edge", DEFAULT_FVG_ENTRY_EDGE)
    if edge == "proximal":
        entry_fvg = fvg[1] if is_upper else fvg[0]
    elif edge == "distal":
        entry_fvg = fvg[0] if is_upper else fvg[1]
    else:
        entry_fvg = (fvg[0] + fvg[1]) / 2.0

    entry_type = params.get("entry_type", ENTRY_TYPE)
    if entry_type == "fvg":
        entry = entry_fvg
    elif entry_type == "sweep50":
        sweep_50 = (source_extreme + close_arr[source_idx]) / 2.0
        entry = sweep_50
    elif entry_type == "fvg_or_sweep50":
        sweep_50 = (source_extreme + close_arr[source_idx]) / 2.0
        current_price_tmp = close_arr[i]
        if is_upper:
            entry = (
                min(entry_fvg, sweep_50)
                if abs(entry_fvg - current_price_tmp) < abs(sweep_50 - current_price_tmp)
                else sweep_50
            )
        else:
            entry = (
                max(entry_fvg, sweep_50)
                if abs(entry_fvg - current_price_tmp) < abs(sweep_50 - current_price_tmp)
                else sweep_50
            )
    else:
        entry = entry_fvg

    current_price = close_arr[i]
    min_dist = limit_stop_pip * pip_size

    if is_upper:
        if entry < current_price + min_dist:
            stats["wrong_side_limit"] += 1
            return None, "wrong_side_limit"
    else:
        if entry > current_price - min_dist:
            stats["wrong_side_limit"] += 1
            return None, "wrong_side_limit"

    if is_upper:
        sl_source = source_extreme + sl_buffer_abs
        sl_size_source = sl_source - entry
        sl_fvg = fvg[0] + sl_buffer_abs
        sl_size_fvg = sl_fvg - entry
    else:
        sl_source = source_extreme - sl_buffer_abs
        sl_size_source = entry - sl_source
        sl_fvg = fvg[1] - sl_buffer_abs
        sl_size_fvg = entry - sl_fvg

    max_sl_reversal_pip = params.get("max_sl_reversal_pip", DEFAULT_MAX_SL_REVERSAL_PIP)
    if name in IDL_IDH_NAMES and max_sl_reversal_pip > 0:
        effective_max_sl_abs = max_sl_reversal_pip * pip_size
    else:
        effective_max_sl_abs = max_sl_realistic_abs

    if sl_size_source < min_sl_realistic_abs:
        if (sl_size_fvg >= min_sl_realistic_abs
                and sl_size_fvg <= effective_max_sl_abs):
            sl = sl_fvg
            sl_size = sl_size_fvg
            use_source_sl = False
            stats["sl_fallback_used"] += 1
        else:
            stats["sl_rejected_all"] += 1
            return None, "sl_rejected_all"
    elif sl_size_source > effective_max_sl_abs:
        stats["sl_rejected_wide"] += 1
        return None, "sl_rejected_wide"
    else:
        sl = sl_source
        sl_size = sl_size_source
        use_source_sl = True

    tp = (entry - sl_size * params["rr"]) if is_upper else (entry + sl_size * params["rr"])

    if sl_size <= 0 or sl_size < min_sl_abs:
        stats["min_sl_skip"] += 1
        return None, "min_sl_skip"

    if sl_size < min_sl_realistic_abs:
        stats["min_sl_realistic_skip"] += 1
        return None, "min_sl_realistic_skip"

    if sl_size > effective_max_sl_abs:
        stats["max_sl_realistic_skip"] += 1
        return None, "max_sl_realistic_skip"

    max_spread_pct = params.get("max_spread_pct_of_sl", DEFAULT_MAX_SPREAD_PCT_OF_SL)
    if max_spread_pct > 0 and spread_abs > sl_size * max_spread_pct:
        stats["spread_pct_skip"] += 1
        return None, "spread_pct_skip"

    if abs(entry - current_price) < min_dist:
        stats["limit_stop_violation"] += 1
        return None, "limit_stop_violation"

    price_key = (round(entry / pip_size), is_upper)
    fvg_key = ("FVG", fvg_idx, is_upper)

    if used_entries.get(fvg_key, 0) >= 1:
        stats["duplicate_entry"] += 1
        return None, "duplicate_entry"

    existing_price = used_entries.get(price_key)
    if existing_price is not None and max_orders_per_entry > 0:
        count = existing_price[0]
        if count >= max_orders_per_entry:
            stats["duplicate_entry"] += 1
            return None, "duplicate_entry"

    required_place_idx = fvg_idx + params.get("limit_delay_bars", LIMIT_DELAY_BARS)
    if required_place_idx > i:
        stats["sequence_not_ready"] += 1
        return None, "sequence_not_ready"

    limit_placed_idx = i
    n = len(high_arr)
    fill_idx = try_limit_order(
        high_arr, low_arr, limit_placed_idx, entry, is_upper, limit_bars, n
    )
    if fill_idx is None:
        stats["limit_not_filled"] += 1
        return None, "limit_not_filled"

    force_close_eod = params.get("force_close_eod", DEFAULT_FORCE_CLOSE_EOD)
    result, close_idx = simulate_trade_idx(
        high_arr,
        low_arr,
        close_arr,
        msk_dates,
        fill_idx,
        entry,
        sl,
        tp,
        is_upper,
        500,
        n,
        force_close_eod=force_close_eod,
    )
    if result is None:
        stats["no_result"] += 1
        return None, "no_result"

    if result == 0:
        stats["eod_closed"] += 1

    fill_time = pd.Timestamp(times[fill_idx])
    close_time = pd.Timestamp(times[close_idx])

    if result == 0:
        days_held = 0
        swap_abs = 0.0
        exit_price = float(close_arr[close_idx])
    else:
        days_held = max(0, (close_time.date() - fill_time.date()).days)
        swap_pip = swap_long_pip if not is_upper else swap_short_pip
        swap_abs = swap_pip * days_held * pip_size
        exit_price = None

    profit = compute_profit(
        result, entry, sl, tp, is_upper,
        contract_size, params["lot"], spread_abs, swap_abs,
        exit_price=exit_price
    )

    limit_dur_min = int(
        (times[fill_idx] - times[limit_placed_idx]) / np.timedelta64(1, 'm')
    )
    sl_pips = round(sl_size / pip_size, 1)
    tp_pips = round(abs(tp - entry) / pip_size, 1)

    return {
        "time": pd.Timestamp(times[i]),
        "level": name,
        "source_type": source_type,
        "source_time": pd.Timestamp(times[source_idx]),
        "choch_time": pd.Timestamp(times[choch_idx]),
        "fvg_time": pd.Timestamp(times[fvg_idx]),
        "fvg_idx": fvg_idx,
        "fvg_age_bars": i - fvg_idx,
        "fill_idx": fill_idx,
        "limit_placed_time": pd.Timestamp(times[limit_placed_idx]),
        "fill_time": fill_time,
        "close_time": close_time,
        "direction": "SELL" if is_upper else "BUY",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "exit_price": exit_price,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "result": result,
        "profit": profit,
        "days_held": days_held,
        "limit_dur_min": limit_dur_min,
        "entry_type": entry_type,
        "fvg_entry_edge": edge,
        "sl_used_source": use_source_sl,
        "sl_type": "source" if use_source_sl else "fvg",
        "spread_cost": spread_abs * contract_size * params["lot"],
        "swap_cost": swap_abs * contract_size * params["lot"],
    }, None


# ============================================================
# 7. BACKTEST
# ============================================================
def backtest(df, params, pip_size, contract_size, start_idx=50, end_idx=None,
             debug=False, print_trades=False):
    if end_idx is None:
        end_idx = len(df) - 1

    lot = params["lot"]
    balance = params["deposit"]
    equity = []
    trades = []

    uses = {}
    bos_levels = {}
    used_entries = {}
    last_bos_attempt = {}
    pending_sweeps = {}
    finalized_sweeps = {}
    best_sweep_extreme = {}
    sweep_block_until = {"BUY": -10**9, "SELL": -10**9}
    sweep_block_owner = {"BUY": None, "SELL": None}

    orders_today = 0
    sl_today = 0
    current_day = None
    last_day = None
    static_levels = []
    sl_day_blocked = False
    sl_limit_counted_today = False

    day_sweep_stats = {}
    counted_sweep_uids = set()
    prev_trading_day = None

    min_fvg_abs = params["min_fvg_pip"] * pip_size
    sl_buffer_abs = params["sl_buffer_pip"] * pip_size
    min_sl_abs = params["min_sl_pip"] * pip_size
    min_sl_realistic_abs = params.get("min_sl_realistic_pip", MIN_SL_REALISTIC_PIP) * pip_size
    max_sl_realistic_abs = params.get("max_sl_realistic_pip", MAX_SL_REALISTIC_PIP) * pip_size
    max_uses = params.get("max_uses_per_level", MAX_USES_PER_LEVEL)
    limit_bars = params.get("limit_valid_bars", LIMIT_VALID_BARS)
    bos_break = BOS_MIN_BREAK_PIP * pip_size
    choch_wait = params.get("choch_wait_bars", CHOCH_WAIT_BARS)
    choch_strict = params.get("choch_strict_after", False)
    choch_lookback = params.get("choch_lookback", DEFAULT_CHOCH_LOOKBACK)
    choch_mode = params.get("choch_mode", DEFAULT_CHOCH_MODE)
    max_sl_per_day = params.get("max_sl_per_day", MAX_SL_PER_DAY)
    max_orders_per_entry = params.get("max_orders_per_entry", MAX_ORDERS_PER_ENTRY)
    entry_type = params.get("entry_type", ENTRY_TYPE)
    limit_delay_bars = params.get("limit_delay_bars", LIMIT_DELAY_BARS)
    sweep_lookback = params.get("sweep_lookback", 48)
    signal_max_age = params.get("signal_max_age_bars", DEFAULT_SIGNAL_MAX_AGE_BARS)
    bos_cooldown = params.get("bos_cooldown_bars", DEFAULT_BOS_COOLDOWN_BARS)
    sweep_priority_bars = params.get("sweep_priority_bars", DEFAULT_SWEEP_PRIORITY_BARS)
    sweep_attempt_cooldown = params.get("sweep_attempt_cooldown_bars", DEFAULT_SWEEP_ATTEMPT_COOLDOWN_BARS)
    force_close_eod = params.get("force_close_eod", DEFAULT_FORCE_CLOSE_EOD)
    use_bos = params.get("use_bos", True)

    spec = ALFAFOREX_SPECS.get(params.get("symbol", "EURUSD"), ALFAFOREX_SPECS["EURUSD"])
    spread_pip = spec["spread_pip"]
    limit_stop_pip = spec["limit_stop_level_pip"]
    swap_long_pip = spec["swap_long_pip"]
    swap_short_pip = spec["swap_short_pip"]
    spread_abs = spread_pip * pip_size

    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)
    idl_arr = df["idl_dyn"].to_numpy(dtype=float)
    idh_arr = df["idh_dyn"].to_numpy(dtype=float)
    times = df["time"].values
    dates = df["date"].values

    msk_dates = None
    if force_close_eod:
        msk_dates = (pd.to_datetime(times) + pd.Timedelta(hours=DATA_TZ_OFFSET_HOURS)).date

    pre = get_precomputed(df, choch_lookback, choch_mode)

    stats = {
        "sweeps": 0,
        "bos": 0,
        "idl_dyn": 0,
        "idh_dyn": 0,
        "idl_reversal": 0,
        "idh_reversal": 0,
        "choch_ok": 0,
        "choch_not_found": 0,
        "fvgs": 0,
        "fvg_not_found": 0,
        "fvg_not_ready": 0,
        "fvg_too_old": 0,
        "fvg_size_skip": 0,
        "min_sl_skip": 0,
        "min_sl_realistic_skip": 0,
        "max_sl_realistic_skip": 0,
        "sl_fallback_used": 0,
        "sl_rejected_all": 0,
        "sl_rejected_wide": 0,
        "spread_pct_skip": 0,
        "eod_closed": 0,
        "limit_not_filled": 0,
        "no_result": 0,
        "duplicate_entry": 0,
        "limit_stop_violation": 0,
        "wrong_side_limit": 0,
        "sequence_not_ready": 0,
        "stale_signal": 0,
        "rejected_cooldown": 0,
        "blocked_by_pending_sweep": 0,
        "retry_sweep": 0,
        "sweep_permanent_reject": 0,
        "rejected_used": 0,
        "rejected_extreme": 0,
        "rejected_duplicate": 0,
        "kz_skip": 0,
        "weekend_skip": 0,
        "sl_limit_days": 0,
        "levels_total": 0,
        "levels_skipped_by_hour": 0,
        "bos_created": 0,
        "bos_skipped_same": 0,
        "deduped_total": 0,
        "bos_idl_replaced": 0,
        "bos_idh_replaced": 0,
        "h1_blocked_entries": 0,
    }

    permanent_reasons = {
        "stale_signal",
        "wrong_side_limit",
        "limit_stop_violation",
        "sl_rejected_all",
        "sl_rejected_wide",
        "min_sl_skip",
        "min_sl_realistic_skip",
        "max_sl_realistic_skip",
        "spread_pct_skip",
        "duplicate_entry",
        "no_result",
        "fvg_too_old",
    }

    sweep_by_level = {}
    trades_by_level = {}
    bos_by_level = {}
    total_swap_cost = 0.0
    total_spread_cost = 0.0

    def _attach_sweep_flags(trade_obj, trade_day, trade_hour_msk):
        cur = day_sweep_stats.get(trade_day, {"LDN": 0, "NY": 0})
        prev = (
            day_sweep_stats.get(prev_trading_day, {"LDN": 0, "NY": 0})
            if prev_trading_day is not None
            else {"LDN": 0, "NY": 0}
        )

        trade_obj["entry_session"] = session_from_msk_hour(trade_hour_msk)
        trade_obj["had_london_sweep_today"] = bool(cur.get("LDN", 0) > 0)
        trade_obj["had_ny_sweep_today"] = bool(cur.get("NY", 0) > 0)
        trade_obj["current_day_had_both_sweeps"] = bool(
            cur.get("LDN", 0) > 0 and cur.get("NY", 0) > 0
        )
        trade_obj["prev_day_had_london_sweep"] = bool(prev.get("LDN", 0) > 0)
        trade_obj["prev_day_had_ny_sweep"] = bool(prev.get("NY", 0) > 0)
        trade_obj["prev_day_had_both_sweeps"] = bool(
            prev.get("LDN", 0) > 0 and prev.get("NY", 0) > 0
        )
        trade_obj["london_sweep_count_today"] = int(cur.get("LDN", 0))
        trade_obj["ny_sweep_count_today"] = int(cur.get("NY", 0))
        trade_obj["prev_day_london_sweep_count"] = int(prev.get("LDN", 0))
        trade_obj["prev_day_ny_sweep_count"] = int(prev.get("NY", 0))

    for i in range(start_idx, end_idx):
        t = pd.Timestamp(times[i])
        day = dates[i]
        hour_utc = t.hour
        hour_msk = to_msk_hour(hour_utc)
        minute_msk = t.minute

        if is_weekend(day):
            equity.append(balance)
            stats["weekend_skip"] += 1
            continue

        weekday = pd.Timestamp(day).weekday()
        if weekday == 0 and hour_msk < ALFAFOREX_OPEN_HOUR_MSK:
            equity.append(balance)
            continue

        if weekday == 4 and (
            hour_msk > ALFAFOREX_CLOSE_HOUR_MSK
            or (hour_msk == ALFAFOREX_CLOSE_HOUR_MSK and minute_msk > ALFAFOREX_CLOSE_MIN_MSK)
        ):
            equity.append(balance)
            continue

        if day != current_day:
            if current_day is not None:
                prev_trading_day = current_day
            current_day = day

            orders_today = 0
            sl_today = 0
            sl_day_blocked = False
            sl_limit_counted_today = False

            uses.clear()
            bos_levels.clear()
            used_entries.clear()
            last_bos_attempt.clear()
            pending_sweeps.clear()
            finalized_sweeps.clear()
            best_sweep_extreme.clear()
            sweep_block_until = {"BUY": -10**9, "SELL": -10**9}
            sweep_block_owner = {"BUY": None, "SELL": None}

            if max_sl_per_day > 0 and sl_today >= max_sl_per_day:
                sl_day_blocked = True
                if not sl_limit_counted_today:
                    stats["sl_limit_days"] += 1
                    sl_limit_counted_today = True

        if orders_today >= params["max_orders_day"]:
            equity.append(balance)
            continue

        if not get_killzone(hour_msk, params):
            stats["kz_skip"] += 1
            equity.append(balance)
            continue

        if last_day != day:
            last_day = day
            static_levels = []

            prev_date = day - timedelta(days=1)
            while is_weekend(prev_date):
                prev_date -= timedelta(days=1)

            prev_row = df[df["date"] == prev_date]
            if len(prev_row) > 0:
                pdh = prev_row["day_high"].iloc[0]
                pdl = prev_row["day_low"].iloc[0]
                if pd.notna(pdh):
                    static_levels.append(("PDH", pdh, True, 0))
                if pd.notna(pdl):
                    static_levels.append(("PDL", pdl, False, 0))

            cur_week = t.strftime("%Y-%W")
            prev_week_rows = df[df["year_week"] < cur_week]
            if len(prev_week_rows) > 0:
                last_week = prev_week_rows["year_week"].max()
                pwh = prev_week_rows[prev_week_rows["year_week"] == last_week]["week_high"].iloc[0]
                pwl = prev_week_rows[prev_week_rows["year_week"] == last_week]["week_low"].iloc[0]
                if pd.notna(pwh):
                    static_levels.append(("PWH", pwh, True, 0))
                if pd.notna(pwl):
                    static_levels.append(("PWL", pwl, False, 0))

            cur_month = t.strftime("%Y-%m")
            prev_month_rows = df[df["year_month"] < cur_month]
            if len(prev_month_rows) > 0:
                last_month = prev_month_rows["year_month"].max()
                pmh = prev_month_rows[prev_month_rows["year_month"] == last_month]["month_high"].iloc[0]
                pml = prev_month_rows[prev_month_rows["year_month"] == last_month]["month_low"].iloc[0]
                if pd.notna(pmh):
                    static_levels.append(("PMH", pmh, True, 0))
                if pd.notna(pml):
                    static_levels.append(("PML", pml, False, 0))

            cur_day_rows = df[df["date"] == day]
            if len(cur_day_rows) > 0:
                asian_h = cur_day_rows["asian_high"].iloc[0]
                asian_l = cur_day_rows["asian_low"].iloc[0]
                london_h = cur_day_rows["london_high"].iloc[0]
                london_l = cur_day_rows["london_low"].iloc[0]
                ny_h = cur_day_rows["ny_high"].iloc[0]
                ny_l = cur_day_rows["ny_low"].iloc[0]

                if pd.notna(asian_h):
                    static_levels.append(("AsianH", asian_h, True, 8))
                if pd.notna(asian_l):
                    static_levels.append(("AsianL", asian_l, False, 8))
                if pd.notna(london_h):
                    static_levels.append(("LondonH", london_h, True, 9))
                if pd.notna(london_l):
                    static_levels.append(("LondonL", london_l, False, 9))
                if pd.notna(ny_h):
                    static_levels.append(("NYH", ny_h, True, 15))
                if pd.notna(ny_l):
                    static_levels.append(("NYL", ny_l, False, 15))

            # --- DIAG: no_dw_levels ---
            if params.get("no_dw_levels", False):
                _dw_names = {"PDL", "PDH", "PWL", "PWH", "PMH", "PML"}
                static_levels = [x for x in static_levels if x[0] not in _dw_names]

            idl_dyn = idl_arr[i]
            idh_dyn = idh_arr[i]
            prev_idl = idl_arr[i - 1] if i > 0 else np.nan
            prev_idh = idh_arr[i - 1] if i > 0 else np.nan

            if not np.isnan(idl_dyn):
                if np.isnan(prev_idl) or idl_dyn < prev_idl - bos_break:
                    old_keys = [k for k in bos_levels if k[0] == "BOS_IDL"]
                    for k in old_keys:
                        del bos_levels[k]
                    stats["bos_idl_replaced"] += 1
                    bos_levels[("BOS_IDL", round(float(idl_dyn), 8))] = (
                        float(idl_dyn),
                        False,
                        i,
                        float(idl_dyn)
                    )
                    stats["bos_created"] += 1
                    bos_by_level["BOS_IDL"] = bos_by_level.get("BOS_IDL", 0) + 1

            if not np.isnan(idh_dyn):
                if np.isnan(prev_idh) or idh_dyn > prev_idh + bos_break:
                    old_keys = [k for k in bos_levels if k[0] == "BOS_IDH"]
                    for k in old_keys:
                        del bos_levels[k]
                    stats["bos_idh_replaced"] += 1
                    bos_levels[("BOS_IDH", round(float(idh_dyn), 8))] = (
                        float(idh_dyn),
                        True,
                        i,
                        float(idh_dyn)
                    )
                    stats["bos_created"] += 1
                    bos_by_level["BOS_IDH"] = bos_by_level.get("BOS_IDH", 0) + 1

            for name, level, is_upper, min_hour in static_levels:
                if hour_utc < min_hour:
                    continue
                c = close_arr[i]
                level = float(level)
                if is_upper:
                    if c > level + bos_break:
                        bos_key = (f"BOS_{name}", round(level, 8))
                        if bos_key not in bos_levels:
                            bos_levels[bos_key] = (
                                level,
                                True,
                                i,
                                level
                            )
                            stats["bos_created"] += 1
                            bos_by_level[f"BOS_{name}"] = bos_by_level.get(f"BOS_{name}", 0) + 1
                        else:
                            stats["bos_skipped_same"] += 1
                else:
                    if c < level - bos_break:
                        bos_key = (f"BOS_{name}", round(level, 8))
                        if bos_key not in bos_levels:
                            bos_levels[bos_key] = (
                                level,
                                False,
                                i,
                                level
                            )
                            stats["bos_created"] += 1
                            bos_by_level[f"BOS_{name}"] = bos_by_level.get(f"BOS_{name}", 0) + 1
                        else:
                            stats["bos_skipped_same"] += 1

        active_levels = []
        for name, level, is_upper, min_hour in static_levels:
            if hour_utc < min_hour:
                stats["levels_skipped_by_hour"] += 1
                continue
            active_levels.append((name, float(level), is_upper))

        for bos_key, val in bos_levels.items():
            bos_price, is_upper_bos, created_idx, _source_extreme = val
            if bos_key[0] in IDL_IDH_NAMES:
                continue
            active_levels.append((bos_key[0], float(bos_price), is_upper_bos))

        active_levels, cnt_deduped = deduplicate_levels(active_levels, pip_size)
        stats["deduped_total"] += cnt_deduped

        trade_opened = False

        if not sl_day_blocked:
            for name, level, is_upper in active_levels:
                if level <= 0:
                    continue

                key = (name, round(float(level), 8))

                if uses.get(key, 0) >= max_uses:
                    if key in pending_sweeps:
                        release_sweep_block(key, pending_sweeps, sweep_block_until, sweep_block_owner)
                        finalized_sweeps[key] = pending_sweeps[key]["sweep_idx"]
                        del pending_sweeps[key]
                    continue

                sweep_idx = find_sweep_arr(
                    high_arr,
                    low_arr,
                    close_arr,
                    i,
                    level,
                    is_upper,
                    params["sweep_buffer_pip"] * pip_size,
                    sweep_lookback
                )
                if sweep_idx is None:
                    continue

                if sweep_idx <= finalized_sweeps.get(key, -999):
                    stats["rejected_duplicate"] += 1
                    continue

                sweep_extreme = float(high_arr[sweep_idx] if is_upper else low_arr[sweep_idx])
                pending = pending_sweeps.get(key)

                if pending is None:
                    prev_best = best_sweep_extreme.get(key)
                    if prev_best is not None:
                        if is_upper and sweep_extreme <= prev_best:
                            stats["rejected_extreme"] += 1
                            continue
                        if (not is_upper) and sweep_extreme >= prev_best:
                            stats["rejected_extreme"] += 1
                            continue

                    best_sweep_extreme[key] = sweep_extreme
                    expected_dir = "BUY" if not is_upper else "SELL"
                    opposite_dir = "SELL" if expected_dir == "BUY" else "BUY"
                    block_until_i = i + sweep_priority_bars
                    if block_until_i >= sweep_block_until[opposite_dir]:
                        sweep_block_until[opposite_dir] = block_until_i
                        sweep_block_owner[opposite_dir] = key

                    pending_sweeps[key] = {
                        "sweep_idx": sweep_idx,
                        "extreme": sweep_extreme,
                        "created_i": i,
                        "last_attempt_i": -999,
                        "attempts": 0,
                        "name": name,
                        "level": level,
                        "is_upper": is_upper,
                        "block_dir": opposite_dir,
                    }
                    stats["sweeps"] += 1
                    sweep_by_level[name] = sweep_by_level.get(name, 0) + 1
                    stats["levels_total"] += 1

                    _sweep_ts = pd.Timestamp(times[sweep_idx])
                    register_sweep_event(
                        dates[sweep_idx],
                        to_msk_hour(_sweep_ts.hour),
                        name,
                        level,
                        is_upper,
                        counted_sweep_uids,
                        day_sweep_stats,
                    )
                else:
                    if pending["sweep_idx"] != sweep_idx:
                        prev_best = best_sweep_extreme.get(key)
                        better = True
                        if prev_best is not None:
                            better = (sweep_extreme > prev_best) if is_upper else (sweep_extreme < prev_best)

                        if better:
                            best_sweep_extreme[key] = sweep_extreme
                            expected_dir = "BUY" if not is_upper else "SELL"
                            opposite_dir = "SELL" if expected_dir == "BUY" else "BUY"
                            block_until_i = i + sweep_priority_bars
                            if block_until_i >= sweep_block_until[opposite_dir]:
                                sweep_block_until[opposite_dir] = block_until_i
                                sweep_block_owner[opposite_dir] = key

                            pending_sweeps[key] = {
                                "sweep_idx": sweep_idx,
                                "extreme": sweep_extreme,
                                "created_i": i,
                                "last_attempt_i": -999,
                                "attempts": 0,
                                "name": name,
                                "level": level,
                                "is_upper": is_upper,
                                "block_dir": opposite_dir,
                            }
                            stats["sweeps"] += 1
                            stats["levels_total"] += 1

                            _sweep_ts = pd.Timestamp(times[sweep_idx])
                            register_sweep_event(
                                dates[sweep_idx],
                                to_msk_hour(_sweep_ts.hour),
                                name,
                                level,
                                is_upper,
                                counted_sweep_uids,
                                day_sweep_stats,
                            )
                        else:
                            pass
                    else:
                        stats["retry_sweep"] += 1

                pending = pending_sweeps.get(key)
                if pending is None:
                    continue

                if i - pending["sweep_idx"] > signal_max_age:
                    stats["stale_signal"] += 1
                    release_sweep_block(key, pending_sweeps, sweep_block_until, sweep_block_owner)
                    finalized_sweeps[key] = pending["sweep_idx"]
                    del pending_sweeps[key]
                    continue

                if i - pending["last_attempt_i"] < sweep_attempt_cooldown:
                    continue

                # H1_LIVE_GUARD_SWEEP: block entry unless previous trading day had London sweep
                if params.get("require_prev_ldn_sweep", False):
                    _prev_ldn = 0
                    if prev_trading_day is not None:
                        _prev_ldn = day_sweep_stats.get(prev_trading_day, {}).get("LDN", 0)
                    if _prev_ldn == 0:
                        stats["h1_blocked_entries"] += 1
                        continue

                pending["last_attempt_i"] = i
                pending["attempts"] += 1

                if not params.get("use_choch", True):
                    continue

                result_trade, reason = try_open_trade(
                    i,
                    name,
                    level,
                    is_upper,
                    "sweep",
                    pending["sweep_idx"],
                    pending["extreme"],
                    high_arr,
                    low_arr,
                    close_arr,
                    times,
                    msk_dates,
                    params,
                    pip_size,
                    contract_size,
                    min_fvg_abs,
                    sl_buffer_abs,
                    min_sl_abs,
                    min_sl_realistic_abs,
                    max_sl_realistic_abs,
                    limit_stop_pip,
                    spread_abs,
                    swap_long_pip,
                    swap_short_pip,
                    used_entries,
                    max_orders_per_entry,
                    limit_bars,
                    stats,
                    pre,
                    signal_max_age,
                )

                if result_trade is not None:
                    trade = result_trade
                    _attach_sweep_flags(trade, day, hour_msk)
                    balance += trade["profit"]

                    trade_idx = len(trades)
                    trades.append(trade)

                    release_sweep_block(key, pending_sweeps, sweep_block_until, sweep_block_owner)
                    finalized_sweeps[key] = pending["sweep_idx"]
                    del pending_sweeps[key]

                    price_key = (round(trade["entry"] / pip_size), is_upper)
                    fvg_key = ("FVG", trade["fvg_idx"], is_upper)
                    used_entries[fvg_key] = 1

                    existing_price = used_entries.get(price_key)
                    if existing_price is None:
                        used_entries[price_key] = [1, name, trade_idx]
                    else:
                        existing_price[0] += 1
                        existing_price[2] = trade_idx

                    uses[key] = uses.get(key, 0) + 1
                    orders_today += 1
                    trades_by_level[name] = trades_by_level.get(name, 0) + 1

                    if trade["result"] == -1:
                        sl_today += 1

                    total_spread_cost += trade["spread_cost"]
                    total_swap_cost += trade["swap_cost"]
                    trade_opened = True

                    if print_trades:
                        base_msk_date = (trade["source_time"] + pd.Timedelta(hours=3)).date()
                        head_dt = fmt_msk(trade["source_time"])
                        msk_src = fmt_msk_short(trade["source_time"], base_msk_date)
                        msk_choch = fmt_msk_short(trade["choch_time"], base_msk_date)
                        msk_fvg = fmt_msk_short(trade["fvg_time"], base_msk_date)
                        msk_limit = fmt_msk_short(trade["limit_placed_time"], base_msk_date)
                        msk_fill = fmt_msk_short(trade["fill_time"], base_msk_date)

                        if trade["result"] == 1:
                            status = "✅TP"
                        elif trade["result"] == -1:
                            status = "❌SL"
                        else:
                            status = "🛑EOD"

                        src = "swp" if trade["sl_used_source"] else "fvg"
                        swap_info = (
                            f"  swap=${trade['swap_cost']:+.2f}"
                            if trade["days_held"] > 0 else ""
                        )
                        print(
                            f"    [{head_dt} MSK] {name:<12} "
                            f"{'SELL' if is_upper else 'BUY':<4}  SWEEP  "
                            f"src={msk_src}  choch={msk_choch}  fvg={msk_fvg}  "
                            f"limit_placed={msk_limit}  fill={msk_fill}  "
                            f"limit_dur={trade['limit_dur_min']}min  "
                            f"entry={trade['entry']:.5f}  "
                            f"SL={trade['sl']:.5f} ({trade['sl_pips']:.1f}p,{src})  "
                            f"TP={trade['tp']:.5f} ({trade['tp_pips']:.1f}p)  "
                            f"{status}  ${trade['profit']:+.2f}{swap_info}"
                        )
                    break
                else:
                    if reason in permanent_reasons:
                        stats["sweep_permanent_reject"] += 1
                        release_sweep_block(key, pending_sweeps, sweep_block_until, sweep_block_owner)
                        finalized_sweeps[key] = pending["sweep_idx"]
                        del pending_sweeps[key]

        if trade_opened:
            equity.append(balance)
            continue

        if use_bos and not sl_day_blocked:
            for bos_key, val in sorted(bos_levels.items(), key=lambda kv: kv[1][2]):
                bos_price, is_upper_source, created_idx, source_extreme = val
                bos_name = bos_key[0]
                key = (bos_name, round(float(bos_price), 8))

                if bos_name in IDL_IDH_NAMES:
                    is_upper = is_upper_source
                    stats_key = "idl_reversal" if bos_name == "BOS_IDL" else "idh_reversal"
                else:
                    is_upper = not is_upper_source
                    stats_key = None

                bos_dir = "SELL" if is_upper else "BUY"
                if sweep_block_until.get(bos_dir, -10**9) >= i:
                    stats["blocked_by_pending_sweep"] += 1
                    continue

                if created_idx >= i:
                    continue

                if uses.get(key, 0) >= max_uses:
                    stats["rejected_used"] += 1
                    continue

                last_att = last_bos_attempt.get(key)
                if last_att is not None and i - last_att < bos_cooldown:
                    stats["rejected_cooldown"] += 1
                    continue

                # H1_LIVE_GUARD_BOS: block entry unless previous trading day had London sweep
                if params.get("require_prev_ldn_sweep", False):
                    _prev_ldn = 0
                    if prev_trading_day is not None:
                        _prev_ldn = day_sweep_stats.get(prev_trading_day, {}).get("LDN", 0)
                    if _prev_ldn == 0:
                        stats["h1_blocked_entries"] += 1
                        continue

                last_bos_attempt[key] = i
                stats["bos"] += 1

                if bos_name == "BOS_IDL":
                    stats["idl_dyn"] += 1
                elif bos_name == "BOS_IDH":
                    stats["idh_dyn"] += 1

                if stats_key:
                    stats[stats_key] += 1

                stats["levels_total"] += 1

                if not params.get("use_choch", True):
                    continue

                result_trade, _reason = try_open_trade(
                    i,
                    bos_name,
                    bos_price,
                    is_upper,
                    "bos",
                    created_idx,
                    source_extreme,
                    high_arr,
                    low_arr,
                    close_arr,
                    times,
                    msk_dates,
                    params,
                    pip_size,
                    contract_size,
                    min_fvg_abs,
                    sl_buffer_abs,
                    min_sl_abs,
                    min_sl_realistic_abs,
                    max_sl_realistic_abs,
                    limit_stop_pip,
                    spread_abs,
                    swap_long_pip,
                    swap_short_pip,
                    used_entries,
                    max_orders_per_entry,
                    limit_bars,
                    stats,
                    pre,
                    signal_max_age,
                )

                if result_trade is not None:
                    trade = result_trade
                    _attach_sweep_flags(trade, day, hour_msk)
                    balance += trade["profit"]

                    trade_idx = len(trades)
                    trades.append(trade)

                    price_key = (round(trade["entry"] / pip_size), is_upper)
                    fvg_key = ("FVG", trade["fvg_idx"], is_upper)
                    used_entries[fvg_key] = 1

                    existing_price = used_entries.get(price_key)
                    if existing_price is None:
                        used_entries[price_key] = [1, bos_name, trade_idx]
                    else:
                        existing_price[0] += 1
                        existing_price[2] = trade_idx

                    uses[key] = uses.get(key, 0) + 1
                    orders_today += 1
                    trades_by_level[bos_name] = trades_by_level.get(bos_name, 0) + 1

                    if trade["result"] == -1:
                        sl_today += 1

                    total_spread_cost += trade["spread_cost"]
                    total_swap_cost += trade["swap_cost"]
                    trade_opened = True

                    if print_trades:
                        base_msk_date = (trade["source_time"] + pd.Timedelta(hours=3)).date()
                        head_dt = fmt_msk(trade["source_time"])
                        msk_src = fmt_msk_short(trade["source_time"], base_msk_date)
                        msk_choch = fmt_msk_short(trade["choch_time"], base_msk_date)
                        msk_fvg = fmt_msk_short(trade["fvg_time"], base_msk_date)
                        msk_limit = fmt_msk_short(trade["limit_placed_time"], base_msk_date)
                        msk_fill = fmt_msk_short(trade["fill_time"], base_msk_date)

                        if trade["result"] == 1:
                            status = "✅TP"
                        elif trade["result"] == -1:
                            status = "❌SL"
                        else:
                            status = "🛑EOD"

                        src = "bos" if trade["sl_used_source"] else "fvg"
                        if bos_name in IDL_IDH_NAMES:
                            src = "bos_rev"

                        swap_info = (
                            f"  swap=${trade['swap_cost']:+.2f}"
                            if trade["days_held"] > 0 else ""
                        )
                        print(
                            f"    [{head_dt} MSK] {bos_name:<12} "
                            f"{'SELL' if is_upper else 'BUY':<4}  BOS    "
                            f"src={msk_src}  choch={msk_choch}  fvg={msk_fvg}  "
                            f"limit_placed={msk_limit}  fill={msk_fill}  "
                            f"limit_dur={trade['limit_dur_min']}min  "
                            f"entry={trade['entry']:.5f}  "
                            f"SL={trade['sl']:.5f} ({trade['sl_pips']:.1f}p,{src})  "
                            f"TP={trade['tp']:.5f} ({trade['tp_pips']:.1f}p)  "
                            f"{status}  ${trade['profit']:+.2f}{swap_info}"
                        )
                    break

        equity.append(balance)

    if len(equity) < (end_idx - start_idx):
        equity.extend([balance] * ((end_idx - start_idx) - len(equity)))

    if debug:
        print(f"\n[DEBUG] Core version:                 {__version__}")
        print(f"  [DEBUG] Start idx:                    {start_idx} / {len(df)}")
        print(f"  [DEBUG] Entry type:                   {entry_type}")
        print(f"  [DEBUG] Sweep lookback:               {sweep_lookback}")
        print(f"  [DEBUG] Use BOS:                      {use_bos}")
        print(f"  [DEBUG] CHoCH mode:                   {choch_mode}")
        print(f"  [DEBUG] CHoCH lookback:               {choch_lookback}")
        print(f"  [DEBUG] FVG select:                   {params.get('fvg_select', DEFAULT_FVG_SELECT)}")
        print(f"  [DEBUG] FVG entry edge:               {params.get('fvg_entry_edge', DEFAULT_FVG_ENTRY_EDGE)}")
        print(f"  [DEBUG] Max FVG age bars:             {params.get('max_fvg_age_bars', DEFAULT_MAX_FVG_AGE_BARS)}")
        print(f"  [DEBUG] Max spread % of SL:           {params.get('max_spread_pct_of_sl', DEFAULT_MAX_SPREAD_PCT_OF_SL)}")
        print(f"  [DEBUG] Max SL reversal pip:          {params.get('max_sl_reversal_pip', DEFAULT_MAX_SL_REVERSAL_PIP)}")
        print(f"  [DEBUG] Force close EOD:              {force_close_eod}")
        print(f"  [DEBUG] Signal max age bars:          {signal_max_age}")
        print(f"  [DEBUG] BOS cooldown bars:            {bos_cooldown}")
        print(f"  [DEBUG] Sweep priority bars:          {sweep_priority_bars}")
        print(f"  [DEBUG] Sweep attempt cooldown:       {sweep_attempt_cooldown}")
        print(f"  [DEBUG] Min SL realistic (pip):       {params.get('min_sl_realistic_pip', MIN_SL_REALISTIC_PIP)}")
        print(f"  [DEBUG] Max SL realistic (pip):       {params.get('max_sl_realistic_pip', MAX_SL_REALISTIC_PIP)}")
        print(f"  [DEBUG] Skipped by weekend:           {stats['weekend_skip']}")
        print(f"  [DEBUG] Skipped by KZ:                {stats['kz_skip']}")
        print(f"  [DEBUG] SL-limit days blocked:        {stats['sl_limit_days']}")
        print(f"  [DEBUG] H1 blocked entries:           {stats.get('h1_blocked_entries', 0)}")
        print(f"  [DEBUG] Levels skipped by hour:       {stats['levels_skipped_by_hour']}")
        print(f"  [DEBUG] BOS created:                  {stats['bos_created']}")
        if bos_by_level:
            bos_str = ", ".join(f"{k}:{v}" for k, v in bos_by_level.items())
            print(f"  [DEBUG]   by BOS:                     {bos_str}")
        print(f"  [DEBUG]   BOS_IDL replaced:           {stats['bos_idl_replaced']}")
        print(f"  [DEBUG]   BOS_IDH replaced:           {stats['bos_idh_replaced']}")
        print(f"  [DEBUG] Deduped levels total:         {stats['deduped_total']}")
        print(f"  [DEBUG] Rejected (duplicate):         {stats['rejected_duplicate']}")
        print(f"  [DEBUG] Rejected (extreme):           {stats['rejected_extreme']}")
        print(f"  [DEBUG] Rejected (uses):              {stats['rejected_used']}")
        print(f"  [DEBUG] Rejected (cooldown):          {stats['rejected_cooldown']}")
        print(f"  [DEBUG] Blocked by pending sweep:     {stats['blocked_by_pending_sweep']}")
        print(f"  [DEBUG] Sweep retries:                {stats['retry_sweep']}")
        print(f"  [DEBUG] Sweep permanent rejects:      {stats['sweep_permanent_reject']}")
        print(f"  [DEBUG] Stale signals:                {stats['stale_signal']}")
        print(f"  [DEBUG] Rejected (duplicate entry):   {stats['duplicate_entry']}")
        print(f"  [DEBUG] Rejected (limit&stop):        {stats['limit_stop_violation']}")
        print(f"  [DEBUG] Rejected (wrong side limit):  {stats['wrong_side_limit']}")
        print(f"  [DEBUG] Sequence not ready:           {stats['sequence_not_ready']}")
        print(f"  [DEBUG] FVG not ready:                {stats['fvg_not_ready']}")
        print(f"  [DEBUG] FVG too old:                  {stats['fvg_too_old']}")
        print(f"  [DEBUG] SL rejected (wide source):    {stats['sl_rejected_wide']}")
        print(f"  [DEBUG] Spread % skip:                {stats['spread_pct_skip']}")
        print(f"  [DEBUG] EOD closed:                   {stats['eod_closed']}")
        print(f"  [DEBUG] Levels checked:               {stats['levels_total']}")
        print(f"  [DEBUG] Sweeps found:                 {stats['sweeps']}")
        print(f"  [DEBUG] BOS signals:                  {stats['bos']}")
        print(f"  [DEBUG]   IDL_dyn signals:            {stats['idl_dyn']}  (разворот: {stats['idl_reversal']})")
        print(f"  [DEBUG]   IDH_dyn signals:            {stats['idh_dyn']}  (разворот: {stats['idh_reversal']})")
        if sweep_by_level:
            top_sweeps = sorted(sweep_by_level.items(), key=lambda x: -x[1])[:8]
            sweep_str = ", ".join(f"{k}:{v}" for k, v in top_sweeps)
            print(f"  [DEBUG]   sweeps by level:            {sweep_str}")
        print(f"  [DEBUG] CHoCH passed:                 {stats['choch_ok']}")
        print(f"  [DEBUG] CHoCH not found in window:    {stats['choch_not_found']}")
        print(f"  [DEBUG] FVGs found:                   {stats['fvgs']}")
        print(f"  [DEBUG] FVG not found:                {stats['fvg_not_found']}")
        print(f"  [DEBUG] FVG too small:                {stats['fvg_size_skip']}")
        print(f"  [DEBUG] Skipped by minSL:             {stats['min_sl_skip']}")
        print(f"  [DEBUG] Skipped by minSL realistic:   {stats['min_sl_realistic_skip']}")
        print(f"  [DEBUG] Skipped by maxSL realistic:   {stats['max_sl_realistic_skip']}")
        print(f"  [DEBUG] SL fallback (fvg) used:       {stats['sl_fallback_used']}")
        print(f"  [DEBUG] SL rejected (both < min):     {stats['sl_rejected_all']}")
        print(f"  [DEBUG] Limit order not filled:       {stats['limit_not_filled']}")
        print(f"  [DEBUG] No result (timeout):          {stats['no_result']}")
        print(f"  [DEBUG] Trades executed:              {len(trades)}")
        if trades_by_level:
            trades_str = ", ".join(f"{k}:{v}" for k, v in trades_by_level.items())
            print(f"  [DEBUG] Trades by level:              {trades_str}")
        print(f"  [DEBUG] Total spread cost:            ${total_spread_cost:.2f}")
        print(f"  [DEBUG] Total swap cost:              ${total_swap_cost:+.2f}")

        ldn_days = sum(1 for v in day_sweep_stats.values() if v.get("LDN", 0) > 0)
        ny_days = sum(1 for v in day_sweep_stats.values() if v.get("NY", 0) > 0)
        both_days = sum(
            1
            for v in day_sweep_stats.values()
            if v.get("LDN", 0) > 0 and v.get("NY", 0) > 0
        )
        print(f"  [DEBUG] Days with London sweep:       {ldn_days}")
        print(f"  [DEBUG] Days with NY sweep:           {ny_days}")
        print(f"  [DEBUG] Days with both sweeps:        {both_days}")

        def _print_group(label, subset):
            if not subset:
                print(f"  [DEBUG] {label}: 0 trades, $0.00, WR n/a, PF n/a")
                return
            profits = [float(t.get("profit", 0.0)) for t in subset]
            wins = [p for p in profits if p > 0]
            losses = [p for p in profits if p < 0]
            gross_win = sum(wins)
            gross_loss = abs(sum(losses))
            pf = gross_win / gross_loss if gross_loss > 0 else 999.0
            wr = len(wins) / len(profits) * 100 if profits else 0.0
            print(
                f"  [DEBUG] {label}: "
                f"{len(profits)} trades, "
                f"${sum(profits):.2f}, "
                f"WR {wr:.1f}%, "
                f"PF {pf:.2f}"
            )

        _print_group("all trades", trades)
        for sess in ["LDN", "NY", "OTHER"]:
            _print_group(
                f"entry_session={sess}",
                [t for t in trades if t.get("entry_session") == sess],
            )
        _print_group(
            "trades with London sweep today",
            [t for t in trades if t.get("had_london_sweep_today")],
        )
        _print_group(
            "trades with NY sweep today",
            [t for t in trades if t.get("had_ny_sweep_today")],
        )
        _print_group(
            "trades with current-day both sweeps",
            [t for t in trades if t.get("current_day_had_both_sweeps")],
        )
        _print_group(
            "trades with prev-day London sweep",
            [t for t in trades if t.get("prev_day_had_london_sweep")],
        )
        _print_group(
            "trades with prev-day NY sweep",
            [t for t in trades if t.get("prev_day_had_ny_sweep")],
        )
        _print_group(
            "trades with prev-day both sweeps",
            [t for t in trades if t.get("prev_day_had_both_sweeps")],
        )
        _print_group(
            "LDN entries with prev-day NY sweep",
            [
                t
                for t in trades
                if t.get("entry_session") == "LDN"
                and t.get("prev_day_had_ny_sweep")
            ],
        )
        _print_group(
            "NY entries with same-day London sweep",
            [
                t
                for t in trades
                if t.get("entry_session") == "NY"
                and t.get("had_london_sweep_today")
            ],
        )
        _print_group(
            "non-LDN/non-NY entries",
            [
                t
                for t in trades
                if t.get("entry_session") not in ("LDN", "NY")
            ],
        )

    return balance, trades, equity


# ============================================================
# 8. METRICS
# ============================================================
def calc_metrics(trades, equity, deposit):
    if not trades:
        return {
            "trades": 0,
            "profit": 0,
            "win_rate": 0,
            "pf": 0,
            "max_dd": 0,
            "sharpe": 0,
            "expected": 0,
            "final_balance": deposit,
            "return_pct": 0,
            "spread_cost": 0,
            "swap_cost": 0,
            "avg_limit_dur": 0,
            "zero_dur_cnt": 0,
            "one_bar_cnt": 0,
            "multi_bar_cnt": 0,
            "avg_sl_pips": 0,
            "avg_tp_pips": 0,
            "sl_sweep_cnt": 0,
            "sl_bos_cnt": 0,
            "sl_idl_rev_cnt": 0,
            "sl_idh_rev_cnt": 0,
            "sl_fvg_cnt": 0,
            "eod_cnt": 0,
        }

    profits = [t["profit"] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    pf = sum(wins) / abs(sum(losses)) if losses else 999

    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    max_dd = abs(dd.min()) * 100

    daily_returns = pd.Series(eq).pct_change().dropna()
    sharpe = (
        daily_returns.mean() / daily_returns.std() * np.sqrt(96)
        if len(daily_returns) > 1 and daily_returns.std() > 0
        else 0
    )

    spread_cost = sum(t.get("spread_cost", 0) for t in trades)
    swap_cost = sum(t.get("swap_cost", 0) for t in trades)

    durs = [t.get("limit_dur_min", 0) for t in trades]
    avg_limit_dur = round(np.mean(durs), 1) if durs else 0
    zero_dur_cnt = sum(1 for d in durs if d == 0)
    one_bar_cnt = sum(1 for d in durs if d == 15)
    multi_bar_cnt = sum(1 for d in durs if d > 15)

    sl_pips_list = [t.get("sl_pips", 0) for t in trades]
    tp_pips_list = [t.get("tp_pips", 0) for t in trades]
    avg_sl_pips = round(np.mean(sl_pips_list), 1) if sl_pips_list else 0
    avg_tp_pips = round(np.mean(tp_pips_list), 1) if tp_pips_list else 0

    sl_sweep_cnt = sum(1 for t in trades if t.get("source_type") == "sweep")
    sl_bos_cnt = sum(1 for t in trades if t.get("source_type") == "bos")
    sl_idl_rev_cnt = sum(1 for t in trades if t.get("level") == "BOS_IDL")
    sl_idh_rev_cnt = sum(1 for t in trades if t.get("level") == "BOS_IDH")
    sl_fvg_cnt = sum(1 for t in trades if not t.get("sl_used_source", False))
    eod_cnt = sum(1 for t in trades if t.get("result") == 0)

    return {
        "trades": len(trades),
        "profit": round(sum(profits), 2),
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "pf": round(pf, 3),
        "max_dd": round(max_dd, 2),
        "sharpe": round(sharpe, 3),
        "expected": round(np.mean(profits), 2),
        "final_balance": round(eq[-1], 2),
        "return_pct": round((eq[-1] / deposit - 1) * 100, 2),
        "spread_cost": round(spread_cost, 2),
        "swap_cost": round(swap_cost, 2),
        "avg_limit_dur": avg_limit_dur,
        "zero_dur_cnt": zero_dur_cnt,
        "one_bar_cnt": one_bar_cnt,
        "multi_bar_cnt": multi_bar_cnt,
        "avg_sl_pips": avg_sl_pips,
        "avg_tp_pips": avg_tp_pips,
        "sl_sweep_cnt": sl_sweep_cnt,
        "sl_bos_cnt": sl_bos_cnt,
        "sl_idl_rev_cnt": sl_idl_rev_cnt,
        "sl_idh_rev_cnt": sl_idh_rev_cnt,
        "sl_fvg_cnt": sl_fvg_cnt,
        "eod_cnt": eod_cnt,
    }


def metrics_to_score(metrics, n, min_trades, full_trades, penalty_power, deposit):
    if n < min_trades:
        return -1000 + n

    pf_capped = min(metrics["pf"], PF_CAP)
    if pf_capped < 1.0:
        loss_ratio = abs(metrics["profit"]) / max(float(deposit), 1.0)
        dd_ratio = metrics["max_dd"] / 100.0
        return max(-999.0, -1.0 - 5.0 * loss_ratio - 2.0 * dd_ratio)

    score = pf_capped * (1 - metrics["max_dd"] / 100)
    if n < full_trades:
        ratio = n / float(full_trades)
        score *= ratio ** penalty_power
    return score


def compute_score(trades, equity, deposit, min_trades, full_trades, penalty_power):
    metrics = calc_metrics(trades, equity, deposit)
    return metrics_to_score(
        metrics,
        len(trades),
        min_trades,
        full_trades,
        penalty_power,
        deposit
    )


def export_trades(trades, path):
    if not trades:
        print(f"  Экспорт сделок пропущен: нет сделок -> {path}")
        return

    rows = []
    for t in trades:
        if t.get("result") == 1:
            result_str = "TP"
        elif t.get("result") == -1:
            result_str = "SL"
        else:
            result_str = "EOD"

        rows.append({
            "source_time_ms": fmt_msk(t.get("source_time")),
            "choch_time_ms": fmt_msk(t.get("choch_time")),
            "fvg_time_ms": fmt_msk(t.get("fvg_time")),
            "limit_placed_time_ms": fmt_msk(t.get("limit_placed_time")),
            "fill_time_ms": fmt_msk(t.get("fill_time")),
            "close_time_ms": fmt_msk(t.get("close_time")),
            "level": t.get("level"),
            "source_type": t.get("source_type"),
            "direction": t.get("direction"),
            "entry": t.get("entry"),
            "sl": t.get("sl"),
            "tp": t.get("tp"),
            "exit_price": t.get("exit_price"),
            "sl_pips": t.get("sl_pips"),
            "tp_pips": t.get("tp_pips"),
            "result": result_str,
            "profit": t.get("profit"),
            "days_held": t.get("days_held"),
            "limit_dur_min": t.get("limit_dur_min"),
            "fvg_age_bars": t.get("fvg_age_bars"),
            "entry_type": t.get("entry_type"),
            "fvg_entry_edge": t.get("fvg_entry_edge"),
            "sl_used_source": t.get("sl_used_source"),
            "sl_type": t.get("sl_type"),
            "spread_cost": t.get("spread_cost"),
            "swap_cost": t.get("swap_cost"),
            "entry_session": t.get("entry_session"),
            "had_london_sweep_today": t.get("had_london_sweep_today"),
            "had_ny_sweep_today": t.get("had_ny_sweep_today"),
            "current_day_had_both_sweeps": t.get("current_day_had_both_sweeps"),
            "prev_day_had_london_sweep": t.get("prev_day_had_london_sweep"),
            "prev_day_had_ny_sweep": t.get("prev_day_had_ny_sweep"),
            "prev_day_had_both_sweeps": t.get("prev_day_had_both_sweeps"),
            "london_sweep_count_today": t.get("london_sweep_count_today"),
            "ny_sweep_count_today": t.get("ny_sweep_count_today"),
            "prev_day_london_sweep_count": t.get("prev_day_london_sweep_count"),
            "prev_day_ny_sweep_count": t.get("prev_day_ny_sweep_count"),
        })

    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"  Сделки экспортированы: {path} ({len(rows)})")


# ============================================================
# 9. OPTUNA OBJECTIVE
# ============================================================
def make_objective(df, pip_size, contract_size, base_params,
                   min_trades, full_trades, penalty_power,
                   rr_min, rr_max, rr_step,
                   min_sl_pip_min, min_sl_pip_max,
                   fixed_sweep_buffer=None,
                   fix_sl_buffer_pip=None,
                   fix_min_fvg_pip=None,
                   fix_fvg_lookback=None):
    def objective(trial):
        params = dict(base_params)

        if fixed_sweep_buffer is not None:
            params["sweep_buffer_pip"] = fixed_sweep_buffer
        else:
            params["sweep_buffer_pip"] = trial.suggest_int("sweep_buffer_pip", 1, 3, step=1)

        if rr_min == rr_max:
            params["rr"] = rr_min
        else:
            params["rr"] = trial.suggest_float("rr", rr_min, rr_max, step=rr_step)

        if fix_sl_buffer_pip is not None:
            params["sl_buffer_pip"] = fix_sl_buffer_pip
        else:
            params["sl_buffer_pip"] = trial.suggest_int(
                "sl_buffer_pip",
                SL_BUFFER_PIP_RANGE[0],
                SL_BUFFER_PIP_RANGE[1],
                step=1
            )

        if min_sl_pip_min == min_sl_pip_max:
            params["min_sl_pip"] = min_sl_pip_min
        else:
            params["min_sl_pip"] = trial.suggest_int(
                "min_sl_pip",
                min_sl_pip_min,
                min_sl_pip_max,
                step=1
            )

        if fix_min_fvg_pip is not None:
            params["min_fvg_pip"] = fix_min_fvg_pip
        else:
            params["min_fvg_pip"] = trial.suggest_int("min_fvg_pip", 1, 5, step=1)

        if fix_fvg_lookback is not None:
            params["fvg_lookback"] = fix_fvg_lookback
        else:
            params["fvg_lookback"] = trial.suggest_int("fvg_lookback", 10, 30, step=5)

        balance, trades, equity = backtest(df, params, pip_size, contract_size)
        metrics = calc_metrics(trades, equity, params["deposit"])
        score = metrics_to_score(
            metrics,
            len(trades),
            min_trades,
            full_trades,
            penalty_power,
            params["deposit"]
        )

        trial.set_user_attr("n_trades", int(metrics["trades"]))
        trial.set_user_attr("profit", float(metrics["profit"]))
        trial.set_user_attr("return_pct", float(metrics["return_pct"]))
        trial.set_user_attr("pf", float(metrics["pf"]))
        trial.set_user_attr("max_dd", float(metrics["max_dd"]))
        trial.set_user_attr("win_rate", float(metrics["win_rate"]))
        return score

    return objective


__all__ = [
    "__version__",
    "DATA_DIR",
    "SYMBOL_MAP",
    "DATA_TZ_OFFSET_HOURS",
    "PIP_SIZE",
    "CONTRACT_SIZE",
    "LOOKBACK_BY_TF",
    "TF_MINUTES",
    "ALFAFOREX_SPECS",
    "ALFAFOREX_OPEN_HOUR_MSK",
    "ALFAFOREX_CLOSE_HOUR_MSK",
    "ALFAFOREX_CLOSE_MIN_MSK",
    "MIN_TRADES_FOR_VALID",
    "FULL_TRADES_FOR_SCORE",
    "SCORE_PENALTY_POWER",
    "PF_CAP",
    "DEFAULT_LOT",
    "KZ_PRELONDON_START_MSK",
    "KZ_PRELONDON_END_MSK",
    "KZ_LONDON_START_MSK",
    "KZ_LONDON_END_MSK",
    "KZ_NY_START_MSK",
    "KZ_NY_END_MSK",
    "MAX_USES_PER_LEVEL",
    "LIMIT_VALID_BARS",
    "BOS_MIN_BREAK_PIP",
    "CHOCH_WAIT_BARS",
    "DEFAULT_CHOCH_LOOKBACK",
    "MAX_SL_PER_DAY",
    "MAX_ORDERS_PER_ENTRY",
    "ENTRY_TYPE",
    "LIMIT_DELAY_BARS",
    "MIN_SL_REALISTIC_PIP",
    "MAX_SL_REALISTIC_PIP",
    "MIN_RR",
    "MAX_RR",
    "RR_STEP",
    "SL_BUFFER_PIP_RANGE",
    "MIN_SL_PIP_RANGE",
    "DEFAULT_FVG_SELECT",
    "DEFAULT_FVG_ENTRY_EDGE",
    "DEFAULT_CHOCH_MODE",
    "DEFAULT_SIGNAL_MAX_AGE_BARS",
    "DEFAULT_BOS_COOLDOWN_BARS",
    "DEFAULT_SWEEP_PRIORITY_BARS",
    "DEFAULT_SWEEP_ATTEMPT_COOLDOWN_BARS",
    "DEFAULT_MAX_FVG_AGE_BARS",
    "DEFAULT_MAX_SPREAD_PCT_OF_SL",
    "DEFAULT_MAX_SL_REVERSAL_PIP",
    "DEFAULT_FORCE_CLOSE_EOD",
    "IDL_IDH_NAMES",
    "LEVEL_PRIORITY",
    "get_level_priority",
    "fmt_msk",
    "fmt_msk_short",
    "is_weekend",
    "session_from_msk_hour",
    "register_sweep_event",
    "load_data",
    "precompute_levels",
    "precompute_indicators",
    "get_precomputed",
    "find_choch_in_window_pre",
    "find_fvg_after_idx_pre",
    "find_sweep_arr",
    "get_killzone",
    "to_msk_hour",
    "try_limit_order",
    "simulate_trade_idx",
    "compute_profit",
    "deduplicate_levels",
    "release_sweep_block",
    "try_open_trade",
    "backtest",
    "calc_metrics",
    "metrics_to_score",
    "compute_score",
    "export_trades",
    "make_objective",
]
