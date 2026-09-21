#!/usr/bin/env python3
"""
H1 post-filter report.

Читает CSV с сделками baseline и считает статистику:
- ALL
- prev_day_had_london_sweep = True
- prev_day_had_london_sweep = False
- DW / non-DW interaction

Поддерживает:
  --eval-start YYYY-MM-DD
  --eval-end   YYYY-MM-DD

Фильтрация по source_time_ms в MSK.
"""

import argparse
import numpy as np
import pandas as pd


BOOL_COLS = [
    "had_london_sweep_today",
    "had_ny_sweep_today",
    "current_day_had_both_sweeps",
    "prev_day_had_london_sweep",
    "prev_day_had_ny_sweep",
    "prev_day_had_both_sweeps",
]

DW_LEVELS = {"PDL", "PDH", "PWL", "PWH", "PMH", "PML"}


def to_bool(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes", "y"])
    )


def calc_stats(sub: pd.DataFrame, label: str, deposit: float = 10000.0):
    if len(sub) == 0:
        print(f"{label:<55} n=0")
        return None

    profits = sub["profit"].astype(float).to_numpy()
    wins = profits[profits > 0]
    losses = profits[profits < 0]

    gross_win = wins.sum()
    gross_loss = abs(losses.sum())

    pf = gross_win / gross_loss if gross_loss > 0 else 999.0
    wr = len(wins) / len(profits) * 100.0
    expected = profits.mean()
    total = profits.sum()

    equity = deposit + np.cumsum(profits)
    peak = np.maximum.accumulate(equity)
    dd = abs(((equity - peak) / peak).min()) * 100.0

    best_month_share = None
    dt = sub.get("_dt")
    if dt is not None:
        dt = pd.to_datetime(dt, errors="coerce")
        valid = dt.notna()
        if valid.any() and total > 0:
            monthly = (
                pd.Series(profits[valid.to_numpy()])
                .groupby(dt[valid].dt.to_period("M").to_numpy())
                .sum()
            )
            if len(monthly) > 0:
                val = monthly.max() / total * 100.0
                if np.isfinite(val):
                    best_month_share = float(val)

    top1_share = None
    top3_share = None
    if total > 0:
        sorted_profits = np.sort(profits)
        val1 = sorted_profits[-1] / total * 100.0
        if np.isfinite(val1):
            top1_share = float(val1)

        val3 = sorted_profits[-min(3, len(sorted_profits)):].sum() / total * 100.0
        if np.isfinite(val3):
            top3_share = float(val3)

    bm = "  nan%" if best_month_share is None else f"{best_month_share:5.1f}%"
    t1 = "  nan%" if top1_share is None else f"{top1_share:5.1f}%"
    t3 = "  nan%" if top3_share is None else f"{top3_share:5.1f}%"

    print(
        f"{label:<55} "
        f"n={len(profits):>3} "
        f"profit=${total:>9.2f} "
        f"PF={pf:>6.2f} "
        f"WR={wr:>5.1f}% "
        f"DD={dd:>5.2f}% "
        f"exp=${expected:>7.2f} "
        f"bestM={bm} "
        f"top1={t1} "
        f"top3={t3}"
    )

    return {
        "n": len(profits),
        "profit": float(total),
        "pf": float(pf),
        "wr": float(wr),
        "dd": float(dd),
        "expected": float(expected),
        "best_month_share": best_month_share,
        "top1_share": top1_share,
        "top3_share": top3_share,
    }


def print_check(name: str, ok: bool):
    print(f"  {'✅' if ok else '❌'} {name}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv", help="Path to exported trades CSV")
    p.add_argument("--label", default="", help="Optional label")
    p.add_argument("--eval-start", default=None, help="Include trades from this MSK date, e.g. 2026-03-01")
    p.add_argument("--eval-end", default=None, help="Include trades strictly before this MSK date, e.g. 2026-04-01")
    p.add_argument("--deposit", type=float, default=10000.0)
    p.add_argument("--min-h1-trades", type=int, default=15)
    args = p.parse_args()

    # H1_REPORT_MISSING_FILE_SAFE
    import os as _os
    if not _os.path.exists(args.csv):
        print(f"⚠️  No trades CSV found: {args.csv}")
        print("    Backtest exported no trades. Nothing to report.")
        return
    if _os.path.getsize(args.csv) == 0:
        print(f"⚠️  Empty trades CSV: {args.csv}")
        print("    No trades to report.")
        return
    df = pd.read_csv(args.csv)
    if df.empty:
        print("⚠️  No rows in trades CSV. Nothing to report.")
        return

    if "prev_day_had_london_sweep" not in df.columns:
        raise SystemExit(
            "CSV не содержит колонку prev_day_had_london_sweep. "
            "Нужен экспорт из v50.1-diag baseline backtest."
        )

    df["_dt"] = pd.to_datetime(df["source_time_ms"], errors="coerce")

    if args.eval_start:
        start_ts = pd.Timestamp(args.eval_start)
        df = df[df["_dt"] >= start_ts]

    if args.eval_end:
        end_ts = pd.Timestamp(args.eval_end)
        df = df[df["_dt"] < end_ts]

    df = df.reset_index(drop=True)

    for col in BOOL_COLS:
        if col in df.columns:
            df[col] = to_bool(df[col])

    df["is_dw_level"] = df["level"].astype(str).isin(DW_LEVELS)

    title = f"H1 POST-FILTER REPORT: {args.label}".strip()
    print("=" * 110)
    print(title)
    print(f"File: {args.csv}")
    print(f"Rows after eval filter: {len(df)}")
    if args.eval_start:
        print(f"Eval start: {args.eval_start}")
    if args.eval_end:
        print(f"Eval end:   {args.eval_end}")
    print("=" * 110)

    all_stats = calc_stats(df, "ALL BASELINE", args.deposit)

    print("\n--- Previous-day London sweep ---")
    h1_stats = calc_stats(
        df[df["prev_day_had_london_sweep"]],
        "H1: prev LDN sweep = True",
        args.deposit,
    )
    no_h1_stats = calc_stats(
        df[~df["prev_day_had_london_sweep"]],
        "H1: prev LDN sweep = False",
        args.deposit,
    )

    print("\n--- Interaction: H1 x level type ---")
    calc_stats(
        df[df["prev_day_had_london_sweep"] & df["is_dw_level"]],
        "H1 + DW levels",
        args.deposit,
    )
    calc_stats(
        df[df["prev_day_had_london_sweep"] & ~df["is_dw_level"]],
        "H1 + NON-DW levels",
        args.deposit,
    )
    calc_stats(
        df[~df["prev_day_had_london_sweep"] & df["is_dw_level"]],
        "no H1 + DW levels",
        args.deposit,
    )
    calc_stats(
        df[~df["prev_day_had_london_sweep"] & ~df["is_dw_level"]],
        "no H1 + NON-DW levels",
        args.deposit,
    )

    print("\n--- Same-day London sweep, for comparison ---")
    calc_stats(
        df[df["had_london_sweep_today"]],
        "same-day LDN sweep = True",
        args.deposit,
    )
    calc_stats(
        df[~df["had_london_sweep_today"]],
        "same-day LDN sweep = False",
        args.deposit,
    )

    print("\n" + "=" * 110)
    print("H1 SUCCESS CRITERIA")
    print("=" * 110)

    if h1_stats is None:
        print("Нет сделок H1. Критерии не проверяются.")
        return

    checks = []

    checks.append((f"H1 n >= {args.min_h1_trades}", h1_stats["n"] >= args.min_h1_trades))
    checks.append(("H1 profit > 0", h1_stats["profit"] > 0))
    checks.append(("H1 PF >= 1.25", h1_stats["pf"] >= 1.25))
    checks.append(("H1 WR >= 45%", h1_stats["wr"] >= 45.0))
    checks.append(("H1 DD <= 12%", h1_stats["dd"] <= 12.0))

    if h1_stats["best_month_share"] is not None:
        checks.append(("H1 best month <= 50%", h1_stats["best_month_share"] <= 50.0))
    else:
        checks.append(("H1 best month <= 50%", False))

    if h1_stats["top1_share"] is not None:
        checks.append(("H1 top trade <= 25%", h1_stats["top1_share"] <= 25.0))
    else:
        checks.append(("H1 top trade <= 25%", False))

    if h1_stats["top3_share"] is not None:
        checks.append(("H1 top 3 trades <= 50%", h1_stats["top3_share"] <= 50.0))
    else:
        checks.append(("H1 top 3 trades <= 50%", False))

    trade_retention = None
    profit_retention = None

    if all_stats is not None and all_stats["n"] > 0:
        trade_retention = h1_stats["n"] / all_stats["n"]
        checks.append(("H1 retains >= 40% baseline trades", trade_retention >= 0.40))
        checks.append(("H1 retains <= 75% baseline trades", trade_retention <= 0.75))
    else:
        checks.append(("H1 retains >= 40% baseline trades", False))
        checks.append(("H1 retains <= 75% baseline trades", False))

    if all_stats is not None and all_stats["profit"] > 0:
        profit_retention = h1_stats["profit"] / all_stats["profit"]
        checks.append(("H1 retains >= 60% baseline profit", profit_retention >= 0.60))
    else:
        checks.append(("H1 retains >= 60% baseline profit", False))

    passed = 0
    for name, ok in checks:
        print_check(name, ok)
        if ok:
            passed += 1

    print(f"\nPassed: {passed}/{len(checks)}")

    if trade_retention is not None:
        print(f"H1 trade retention: {trade_retention * 100:.1f}%")
    if profit_retention is not None:
        print(f"H1 profit retention: {profit_retention * 100:.1f}%")

    if h1_stats["n"] < args.min_h1_trades:
        print("\n⚠️ Выборка H1 слишком мала. Даже если критерии пройдены, это не подтверждение.")
    elif passed == len(checks):
        print("\n🎉 H1 проходит предварительные критерии. Можно переводить в experimental forward/paper.")
    elif passed >= len(checks) - 2:
        print("\n⚠️ H1 близко к успеху, но не подтверждена. Продолжать сбор данных.")
    else:
        print("\n❌ H1 не проходит критерии. Не включать как фильтр.")


if __name__ == "__main__":
    main()
