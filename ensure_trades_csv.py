#!/usr/bin/env python3
"""
Ensure a trades CSV exists.

If the file is missing or empty, create an empty CSV with standard columns.
This prevents downstream report scripts from failing when a backtest has 0 trades.
"""

import sys
from pathlib import Path

import pandas as pd

COLUMNS = [
    "source_time_ms",
    "choch_time_ms",
    "fvg_time_ms",
    "limit_placed_time_ms",
    "fill_time_ms",
    "close_time_ms",
    "level",
    "source_type",
    "direction",
    "entry",
    "sl",
    "tp",
    "exit_price",
    "sl_pips",
    "tp_pips",
    "result",
    "profit",
    "days_held",
    "limit_dur_min",
    "fvg_age_bars",
    "entry_type",
    "fvg_entry_edge",
    "sl_used_source",
    "sl_type",
    "spread_cost",
    "swap_cost",
    "entry_session",
    "had_london_sweep_today",
    "had_ny_sweep_today",
    "current_day_had_both_sweeps",
    "prev_day_had_london_sweep",
    "prev_day_had_ny_sweep",
    "prev_day_had_both_sweeps",
    "london_sweep_count_today",
    "ny_sweep_count_today",
    "prev_day_london_sweep_count",
    "prev_day_ny_sweep_count",
]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: ensure_trades_csv.py <path.csv>")

    path = Path(sys.argv[1])

    if path.exists() and path.stat().st_size > 0:
        print(f"CSV already exists and is non-empty: {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=COLUMNS).to_csv(path, index=False)
    print(f"Created empty trades CSV: {path}")


if __name__ == "__main__":
    main()
