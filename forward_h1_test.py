#!/usr/bin/env python3
"""
Forward H1 test: baseline vs prev_day_london post-hoc filter.
Причинно корректен, потому что prev_day_had_london_sweep
использует только данные предыдущего (полностью закрытого) дня.
"""
import sys
import argparse
import pandas as pd
import numpy as np
import core

def calc_stats(trades, label, deposit=10000):
    if not trades:
        print(f"{label:<50} n=0")
        return None
    profits = [t["profit"] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    gw = sum(wins)
    gl = abs(sum(losses))
    pf = gw / gl if gl > 0 else 999.0
    wr = len(wins) / len(profits) * 100.0
    eq = deposit + np.cumsum(profits)
    peak = np.maximum.accumulate(eq)
    dd = abs(((eq - peak) / peak).min()) * 100.0
    exp = np.mean(profits)
    total = sum(profits)

    # monthly concentration
    months = {}
    for t in trades:
        m = str(pd.Timestamp(t["source_time"]).strftime("%Y-%m"))
        months[m] = months.get(m, 0) + t["profit"]
    best_month = max(months.values()) if months else 0
    best_share = best_month / total * 100 if total > 0 else 0

    # top trade concentration
    top1 = max(profits) / total * 100 if total > 0 else 0
    top3 = sum(sorted(profits, reverse=True)[:3]) / total * 100 if total > 0 else 0

    print(
        f"{label:<50} "
        f"n={len(profits):>3} "
        f"profit=${total:>9.2f} "
        f"PF={pf:>6.2f} "
        f"WR={wr:>5.1f}% "
        f"DD={dd:>5.2f}% "
        f"exp=${exp:>7.2f} "
        f"bestM={best_share:>5.1f}% "
        f"top1={top1:>5.1f}% "
        f"top3={top3:>5.1f}%"
    )
    return {
        "n": len(profits), "profit": total, "pf": pf, "wr": wr,
        "dd": dd, "exp": exp, "best_month_share": best_share,
        "top1_share": top1, "top3_share": top3,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--timeframe", default="M15")
    p.add_argument("--data-file", required=True)
    p.add_argument("--start", default="2026-09-15")
    p.add_argument("--end", default="2026-12-31")
    p.add_argument("--lot", type=float, default=0.5)
    p.add_argument("--export", default=None)
    args = p.parse_args()

    pip_size = core.PIP_SIZE[args.symbol]
    contract_size = core.CONTRACT_SIZE[args.symbol]
    sweep_lookback = core.LOOKBACK_BY_TF.get(args.timeframe, 48)

    # Frozen baseline parameters
    params = {
        "deposit": 10000,
        "lot": args.lot,
        "symbol": args.symbol,
        "sweep_lookback": sweep_lookback,
        "cooldown_bars": 4,
        "max_orders_day": 5,
        "max_orders_per_entry": core.MAX_ORDERS_PER_ENTRY,
        "max_uses_per_level": core.MAX_USES_PER_LEVEL,
        "limit_valid_bars": 8,
        "choch_wait_bars": core.CHOCH_WAIT_BARS,
        "choch_strict_after": False,
        "max_sl_per_day": 3,
        "use_choch": True,
        "use_bos": False,
        "choch_lookback": 20,
        "choch_mode": "swing",
        "use_kz": True,
        "kz_prelondon_on": False,
        "kz_london_on": True,
        "kz_ny_on": True,
        "kz_prelondon_start_msk": core.KZ_PRELONDON_START_MSK,
        "kz_prelondon_end_msk": core.KZ_PRELONDON_END_MSK,
        "kz_london_start_msk": core.KZ_LONDON_START_MSK,
        "kz_london_end_msk": core.KZ_LONDON_END_MSK,
        "kz_ny_start_msk": core.KZ_NY_START_MSK,
        "kz_ny_end_msk": core.KZ_NY_END_MSK,
        "entry_type": "fvg",
        "limit_delay_bars": 1,
        "min_sl_realistic_pip": 20,
        "max_sl_realistic_pip": 80,
        "fvg_select": "first",
        "fvg_entry_edge": "proximal",
        "signal_max_age_bars": 20,
        "bos_cooldown_bars": 1,
        "sweep_priority_bars": 7,
        "sweep_attempt_cooldown_bars": 1,
        "max_fvg_age_bars": 6,
        "max_spread_pct_of_sl": 0.12,
        "max_sl_reversal_pip": 25,
        "force_close_eod": False,
        "rr": 1.5,
        "sl_buffer_pip": 16,
        "min_sl_pip": 18,
        "min_fvg_pip": 1,
        "fvg_lookback": 30,
        "sweep_buffer_pip": 1,
    }

    print("=" * 70)
    print(f"FORWARD H1 TEST — {args.symbol} {args.timeframe}")
    print(f"Period: {args.start} — {args.end}")
    print("=" * 70)

    df = core.load_data(args.symbol, args.start, args.end, args.timeframe, data_file=args.data_file)
    df = core.precompute_levels(df)

    balance, trades, equity = core.backtest(df, params, pip_size, contract_size)

    print(f"\nBaseline trades: {len(trades)}")
    if not trades:
        print("Нет сделок. Накопи данные и повтори.")
        return

    # Split by prev_day_had_london_sweep
    h1_trades = [t for t in trades if t.get("prev_day_had_london_sweep")]
    non_h1_trades = [t for t in trades if not t.get("prev_day_had_london_sweep")]

    # Also split by DW / non-DW
    dw_names = {"PDL", "PDH", "PWL", "PWH", "PMH", "PML"}
    h1_dw = [t for t in h1_trades if t["level"] in dw_names]
    h1_nondw = [t for t in h1_trades if t["level"] not in dw_names]
    non_h1_dw = [t for t in non_h1_trades if t["level"] in dw_names]
    non_h1_nondw = [t for t in non_h1_trades if t["level"] not in dw_names]

    print("\n" + "=" * 100)
    print("RESULTS")
    print("=" * 100)
    base = calc_stats(trades, "BASELINE (all)")
    h1 = calc_stats(h1_trades, "H1: prev_day_london = True")
    nh1 = calc_stats(non_h1_trades, "H1: prev_day_london = False")

    print("\n--- Interaction: H1 x level type ---")
    calc_stats(h1_dw, "H1 + DW levels")
    calc_stats(h1_nondw, "H1 + NON-DW levels")
    calc_stats(non_h1_dw, "no H1 + DW levels")
    calc_stats(non_h1_nondw, "no H1 + NON-DW levels")

    # Success criteria check
    print("\n" + "=" * 100)
    print("SUCCESS CRITERIA CHECK")
    print("=" * 100)
    if h1 is None or base is None:
        print("Insufficient data for criteria check.")
        return

    checks = []
    checks.append(("H1 profit > 0", h1["profit"] > 0))
    checks.append(("H1 PF >= 1.25", h1["pf"] >= 1.25))
    checks.append(("H1 WR >= 45%", h1["wr"] >= 45.0))
    checks.append(("H1 DD <= 12%", h1["dd"] <= 12.0))
    checks.append(("H1 DD not worse than baseline +3pp", h1["dd"] <= base["dd"] + 3.0))
    checks.append(("H1 retains >= 40% of baseline trades", h1["n"] >= base["n"] * 0.40))
    checks.append(("H1 retains >= 60% of baseline profit", h1["profit"] >= base["profit"] * 0.60 if base["profit"] > 0 else True))
    checks.append(("H1 best month <= 50%", h1["best_month_share"] <= 50.0))
    checks.append(("H1 top trade <= 25%", h1["top1_share"] <= 25.0))
    checks.append(("H1 top 3 trades <= 50%", h1["top3_share"] <= 50.0))
    checks.append(("H1 n >= 15", h1["n"] >= 15))
    checks.append(("Baseline n >= 30", base["n"] >= 30))

    passed = 0
    for name, ok in checks:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
        if ok:
            passed += 1

    print(f"\nPassed: {passed}/{len(checks)}")
    if passed == len(checks):
        print("🎉 H1 meets all success criteria. Consider promoting to optional filter.")
    elif passed >= len(checks) - 2:
        print("⚠️ H1 is close but not fully confirmed. Continue forward collection.")
    else:
        print("❌ H1 does not meet criteria. Keep as experimental, do not promote.")

    if args.export:
        core.export_trades(trades, args.export)
        print(f"\nTrades exported: {args.export} ({len(trades)})")

if __name__ == "__main__":
    main()
