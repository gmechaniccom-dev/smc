#!/usr/bin/env python3
"""
ICT/SMC Backtest v50.2-h1-live — CLI wrapper.

Adds:
- --no-dw-levels
- --require-prev-ldn-sweep
"""
import os
import sys
import time
import argparse
import pandas as pd
import numpy as np
import optuna
from optuna.samplers import TPESampler

optuna.logging.set_verbosity(optuna.logging.WARNING)
import core

VERSION = getattr(core, "__version__", "v50.2-h1-live")


def parse_args():
    p = argparse.ArgumentParser(
        prog="ict_smc_backtest.py",
        description=f"ICT/SMC Backtest {VERSION} — wrapper around core.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--symbol", default="EURUSD", choices=list(core.SYMBOL_MAP.keys()))
    p.add_argument("--timeframe", default="M5", choices=list(core.LOOKBACK_BY_TF.keys()))
    p.add_argument("--start", default="2026-09-01")
    p.add_argument("--end", default="2026-09-18")
    p.add_argument("--data-file", default=None)
    p.add_argument("--trials", type=int, default=100)
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--lot", type=float, default=core.DEFAULT_LOT)
    p.add_argument("--min-trades", type=int, default=core.MIN_TRADES_FOR_VALID)
    p.add_argument("--full-trades", type=int, default=core.FULL_TRADES_FOR_SCORE)
    p.add_argument("--penalty-power", type=float, default=core.SCORE_PENALTY_POWER)
    p.add_argument("--max-sl-per-day", type=int, default=core.MAX_SL_PER_DAY)
    p.add_argument("--max-orders-per-entry", type=int, default=core.MAX_ORDERS_PER_ENTRY)
    p.add_argument("--max-uses-per-level", type=int, default=core.MAX_USES_PER_LEVEL)
    p.add_argument("--limit-valid-bars", type=int, default=core.LIMIT_VALID_BARS)
    p.add_argument("--entry-type", dest="entry_type", default=core.ENTRY_TYPE,
                   choices=["fvg", "sweep50", "fvg_or_sweep50"])
    p.add_argument("--limit-delay-bars", dest="limit_delay_bars",
                   type=int, default=core.LIMIT_DELAY_BARS)
    p.add_argument("--min-sl-realistic", dest="min_sl_realistic",
                   type=int, default=core.MIN_SL_REALISTIC_PIP)
    p.add_argument("--max-sl-realistic", dest="max_sl_realistic",
                   type=int, default=core.MAX_SL_REALISTIC_PIP)
    p.add_argument("--sweep-buffer-pip", dest="sweep_buffer_pip",
                   type=int, default=None,
                   help="Фикс. sweep_buffer_pip")
    p.add_argument("--rr-min", dest="rr_min", type=float, default=core.MIN_RR)
    p.add_argument("--rr-max", dest="rr_max", type=float, default=core.MAX_RR)
    p.add_argument("--rr-step", dest="rr_step", type=float, default=core.RR_STEP)
    p.add_argument("--min-sl-pip-min", dest="min_sl_pip_min", type=int,
                   default=core.MIN_SL_PIP_RANGE[0])
    p.add_argument("--min-sl-pip-max", dest="min_sl_pip_max", type=int,
                   default=core.MIN_SL_PIP_RANGE[1])
    p.add_argument("--fix-sl-buffer-pip", dest="fix_sl_buffer_pip", type=int, default=None)
    p.add_argument("--fix-min-fvg-pip", dest="fix_min_fvg_pip", type=int, default=None)
    p.add_argument("--fix-fvg-lookback", dest="fix_fvg_lookback", type=int, default=None)
    p.add_argument("--fvg-select", dest="fvg_select", default=core.DEFAULT_FVG_SELECT,
                   choices=["first", "best"])
    p.add_argument("--fvg-entry-edge", dest="fvg_entry_edge", default=core.DEFAULT_FVG_ENTRY_EDGE,
                   choices=["proximal", "distal", "mid"])
    p.add_argument("--choch-mode", dest="choch_mode", default=core.DEFAULT_CHOCH_MODE,
                   choices=["swing", "window"])
    p.add_argument("--choch-lookback", dest="choch_lookback", type=int,
                   default=core.DEFAULT_CHOCH_LOOKBACK)
    p.add_argument("--choch-wait-bars", type=int, default=core.CHOCH_WAIT_BARS)
    p.add_argument("--choch-strict-after", action="store_true")
    p.add_argument("--signal-max-age-bars", dest="signal_max_age_bars", type=int,
                   default=core.DEFAULT_SIGNAL_MAX_AGE_BARS)
    p.add_argument("--bos-cooldown-bars", dest="bos_cooldown_bars", type=int,
                   default=core.DEFAULT_BOS_COOLDOWN_BARS)
    p.add_argument("--sweep-priority-bars", dest="sweep_priority_bars", type=int,
                   default=core.DEFAULT_SWEEP_PRIORITY_BARS)
    p.add_argument("--sweep-attempt-cooldown-bars", dest="sweep_attempt_cooldown_bars", type=int,
                   default=core.DEFAULT_SWEEP_ATTEMPT_COOLDOWN_BARS)
    p.add_argument("--max-fvg-age-bars", dest="max_fvg_age_bars", type=int,
                   default=core.DEFAULT_MAX_FVG_AGE_BARS)
    p.add_argument("--max-spread-pct-of-sl", dest="max_spread_pct_of_sl", type=float,
                   default=core.DEFAULT_MAX_SPREAD_PCT_OF_SL)
    p.add_argument("--max-sl-reversal-pip", dest="max_sl_reversal_pip", type=int,
                   default=core.DEFAULT_MAX_SL_REVERSAL_PIP)

    bos_group = p.add_mutually_exclusive_group()
    bos_group.add_argument("--use-bos", dest="use_bos", action="store_true",
                           help="BOS scenario (default ON)")
    bos_group.add_argument("--no-bos", dest="use_bos", action="store_false")
    p.set_defaults(use_bos=True)

    kz_group = p.add_mutually_exclusive_group()
    kz_group.add_argument("--use-kz", dest="use_kz", action="store_true")
    kz_group.add_argument("--no-kz", dest="use_kz", action="store_false")
    p.set_defaults(use_kz=False)

    ch_group = p.add_mutually_exclusive_group()
    ch_group.add_argument("--use-choch", dest="use_choch", action="store_true")
    ch_group.add_argument("--no-choch", dest="use_choch", action="store_false")
    p.set_defaults(use_choch=True)

    eod_group = p.add_mutually_exclusive_group()
    eod_group.add_argument("--force-close-eod", dest="force_close_eod", action="store_true")
    eod_group.add_argument("--no-force-close-eod", dest="force_close_eod", action="store_false")
    p.set_defaults(force_close_eod=core.DEFAULT_FORCE_CLOSE_EOD)

    p.add_argument("--kz-prelondon", dest="kz_prelondon", action="store_true", default=False)
    p.add_argument("--kz-london", dest="kz_london", action="store_true", default=True)
    p.add_argument("--no-kz-london", dest="kz_london", action="store_false")
    p.add_argument("--kz-ny", dest="kz_ny", action="store_true", default=True)
    p.add_argument("--no-kz-ny", dest="kz_ny", action="store_false")

    p.add_argument("--no-dw-levels", dest="no_dw_levels", action="store_true", default=False,
                   help="Diagnostic: exclude PDL/PDH/PWL/PWH/PMH/PML from static levels")
    p.add_argument("--require-prev-ldn-sweep", dest="require_prev_ldn_sweep", action="store_true", default=False,
                   help="H1 experimental: entries only if prev trading day had London sweep")

    p.add_argument("--debug", action="store_true")
    p.add_argument("--print-trades", action="store_true")
    p.add_argument("--export-trades", dest="export_trades", default=None)
    return p


def rr_range_text(rr_min, rr_max, rr_step):
    if rr_min == rr_max:
        return f"{rr_min} (FIXED), step={rr_step}"
    return f"{rr_min}–{rr_max}, step={rr_step}"


def min_sl_range_text(min_sl_pip_min, min_sl_pip_max):
    if min_sl_pip_min == min_sl_pip_max:
        return f"{min_sl_pip_min} (FIXED) (opt)"
    return f"{min_sl_pip_min}–{min_sl_pip_max} (opt)"


def fixed_or_range_text(value, range_tuple):
    if value is not None:
        return f"{value} (FIXED)"
    return f"{range_tuple[0]}–{range_tuple[1]} (opt)"


def resolve_param(trial_params, name, fixed=None, default=None, range_pair=None):
    if fixed is not None:
        return fixed
    if name in trial_params:
        return trial_params[name]
    if range_pair is not None and range_pair[0] == range_pair[1]:
        return range_pair[0]
    return default


def main():
    parser = parse_args()
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()
    t0 = time.time()

    pip_size = core.PIP_SIZE[args.symbol]
    contract_size = core.CONTRACT_SIZE[args.symbol]
    sweep_lookback = core.LOOKBACK_BY_TF.get(args.timeframe, 48)
    spec = core.ALFAFOREX_SPECS.get(args.symbol, core.ALFAFOREX_SPECS["EURUSD"])

    print("=" * 70)
    print(f"ICT/SMC Backtest {VERSION} — {args.symbol} {args.timeframe}")
    print("=" * 70)
    print(f"  Версия:             {VERSION}")
    print(f"  Период (UTC):       {args.start} — {args.end}")
    print(f"  Данные:             {args.data_file or (core.DATA_DIR + '/' + core.SYMBOL_MAP[args.symbol])}")
    print(f"  Часовой пояс:       MSK (UTC+{core.DATA_TZ_OFFSET_HOURS}) → UTC")
    print(f"  Pip:                {pip_size}")
    print(f"  Contract size:      {contract_size:,}")
    print(f"  Sweep lookback:     {sweep_lookback} баров (TF={args.timeframe})")
    print(f"  --- Альфа-Форекс ---")
    print(f"  Спред:              {spec['spread_pip']} пипс")
    print(f"  Limit&Stop level:   {spec['limit_stop_level_pip']} пипс")
    print(f"  Своп long/short:    {spec['swap_long_pip']:+.2f} / {spec['swap_short_pip']:+.2f} пипс/ночь")
    print(f"  Рабочее время:      Пн 02:00 — Пт 23:55 MSK")
    print(f"  -------------------")
    print(f"  Ядер:               {args.jobs}")
    print(f"  Попыток:            {args.trials}")
    print(f"  Seed:               {args.seed}")
    print(f"  Entry type:         {args.entry_type}")
    print(f"  RR range:           {rr_range_text(args.rr_min, args.rr_max, args.rr_step)}")
    print(f"  Min SL realistic:   {args.min_sl_realistic} пипс")
    print(f"  Max SL realistic:   {args.max_sl_realistic} пипс")
    print(f"  min_sl_pip range:   {min_sl_range_text(args.min_sl_pip_min, args.min_sl_pip_max)}")
    print(f"  sl_buffer_pip:      {fixed_or_range_text(args.fix_sl_buffer_pip, core.SL_BUFFER_PIP_RANGE)}")
    print(f"  min_fvg_pip:        {fixed_or_range_text(args.fix_min_fvg_pip, (1, 5))}")
    print(f"  fvg_lookback:       {fixed_or_range_text(args.fix_fvg_lookback, (10, 30))}")
    print(f"  Max spread % of SL: {args.max_spread_pct_of_sl}")
    print(f"  Max SL reversal:    {args.max_sl_reversal_pip} пипс")
    print(f"  Force close EOD:    {'✅ ВКЛ' if args.force_close_eod else '❌ ВЫКЛ'}")
    print(f"  CHoCH mode:         {args.choch_mode}")
    print(f"  CHoCH lookback:     {args.choch_lookback} баров")
    print(f"  FVG select:         {args.fvg_select}")
    print(f"  FVG entry edge:     {args.fvg_entry_edge}")
    print(f"  Max FVG age:        {args.max_fvg_age_bars} баров")
    print(f"  Signal max age:     {args.signal_max_age_bars} баров")
    print(f"  BOS cooldown:       {args.bos_cooldown_bars} баров")
    print(f"  Sweep priority:     {args.sweep_priority_bars} баров")
    print(f"  Sweep attempt cd:   {args.sweep_attempt_cooldown_bars} баров")
    print(f"  Limit valid bars:   {args.limit_valid_bars} баров")
    print(f"  Use BOS:            {'✅ ВКЛ' if args.use_bos else '❌ ВЫКЛ'}")
    print(f"  CHoCH:              {'✅ ВКЛ' if args.use_choch else '❌ ВЫКЛ'}")
    print(f"  Killzone (MSK):     {'✅ ВКЛ' if args.use_kz else '❌ ВЫКЛ'}")
    print(f"  No DW levels:       {'ON' if args.no_dw_levels else 'OFF'}")
    print(f"  Require prev LDN:   {'ON' if args.require_prev_ldn_sweep else 'OFF'}")
    print(f"  Max SL / day:       {args.max_sl_per_day}")
    print(f"  Lot:                {args.lot}")
    print(f"  Export trades:      {args.export_trades or '—'}")
    print("=" * 70)

    df = core.load_data(
        args.symbol,
        args.start,
        args.end,
        args.timeframe,
        data_file=args.data_file
    )
    df = core.precompute_levels(df)

    base_params = {
        "deposit": 10000,
        "lot": args.lot,
        "symbol": args.symbol,
        "sweep_lookback": sweep_lookback,
        "cooldown_bars": 4,
        "max_orders_day": 5,
        "max_orders_per_entry": args.max_orders_per_entry,
        "max_uses_per_level": args.max_uses_per_level,
        "limit_valid_bars": args.limit_valid_bars,
        "choch_wait_bars": args.choch_wait_bars,
        "choch_strict_after": args.choch_strict_after,
        "max_sl_per_day": args.max_sl_per_day,
        "use_choch": args.use_choch,
        "use_bos": args.use_bos,
        "choch_lookback": args.choch_lookback,
        "choch_mode": args.choch_mode,
        "use_kz": args.use_kz,
        "kz_prelondon_on": args.kz_prelondon,
        "kz_london_on": args.kz_london,
        "kz_ny_on": args.kz_ny,
        "kz_prelondon_start_msk": core.KZ_PRELONDON_START_MSK,
        "kz_prelondon_end_msk": core.KZ_PRELONDON_END_MSK,
        "kz_london_start_msk": core.KZ_LONDON_START_MSK,
        "kz_london_end_msk": core.KZ_LONDON_END_MSK,
        "kz_ny_start_msk": core.KZ_NY_START_MSK,
        "kz_ny_end_msk": core.KZ_NY_END_MSK,
        "entry_type": args.entry_type,
        "limit_delay_bars": args.limit_delay_bars,
        "min_sl_realistic_pip": args.min_sl_realistic,
        "max_sl_realistic_pip": args.max_sl_realistic,
        "fvg_select": args.fvg_select,
        "fvg_entry_edge": args.fvg_entry_edge,
        "signal_max_age_bars": args.signal_max_age_bars,
        "bos_cooldown_bars": args.bos_cooldown_bars,
        "sweep_priority_bars": args.sweep_priority_bars,
        "sweep_attempt_cooldown_bars": args.sweep_attempt_cooldown_bars,
        "max_fvg_age_bars": args.max_fvg_age_bars,
        "max_spread_pct_of_sl": args.max_spread_pct_of_sl,
        "max_sl_reversal_pip": args.max_sl_reversal_pip,
        "force_close_eod": args.force_close_eod,
        "no_dw_levels": args.no_dw_levels,
        "require_prev_ldn_sweep": args.require_prev_ldn_sweep,
    }

    if args.debug:
        print("\n" + "=" * 70)
        print(f"ДИАГНОСТИКА (CHoCH={'ON' if args.use_choch else 'OFF'}, "
              f"BOS={'ON' if args.use_bos else 'OFF'}, "
              f"KZ={'ON' if args.use_kz else 'OFF'}):")
        print("=" * 70)

        diag_params = dict(base_params)
        diag_params["rr"] = args.rr_min
        diag_params["sl_buffer_pip"] = args.fix_sl_buffer_pip if args.fix_sl_buffer_pip is not None else 10
        diag_params["min_sl_pip"] = args.min_sl_pip_min
        diag_params["min_fvg_pip"] = args.fix_min_fvg_pip if args.fix_min_fvg_pip is not None else 1
        diag_params["fvg_lookback"] = args.fix_fvg_lookback if args.fix_fvg_lookback is not None else 20
        diag_params["sweep_buffer_pip"] = args.sweep_buffer_pip if args.sweep_buffer_pip is not None else 1

        core.backtest(
            df,
            diag_params,
            pip_size,
            contract_size,
            debug=True,
            print_trades=False,
        )

    print(f"\nЗапуск оптимизации ({args.trials} попыток × {args.jobs} ядер)...")

    objective_fn = core.make_objective(
        df,
        pip_size,
        contract_size,
        base_params,
        args.min_trades,
        args.full_trades,
        args.penalty_power,
        args.rr_min,
        args.rr_max,
        args.rr_step,
        args.min_sl_pip_min,
        args.min_sl_pip_max,
        fixed_sweep_buffer=args.sweep_buffer_pip,
        fix_sl_buffer_pip=args.fix_sl_buffer_pip,
        fix_min_fvg_pip=args.fix_min_fvg_pip,
        fix_fvg_lookback=args.fix_fvg_lookback,
    )

    sampler = TPESampler(seed=args.seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(
        objective_fn,
        n_trials=args.trials,
        n_jobs=args.jobs,
        show_progress_bar=True,
        catch=(Exception,),
    )

    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if not completed:
        print("\n" + "=" * 70)
        print("  Нет завершённых попыток!")
        print("=" * 70)
        return

    sorted_trials = sorted(
        completed,
        key=lambda t: t.value if t.value is not None else -99999,
        reverse=True
    )
    top10 = sorted_trials[:10]
    rr_range_display = rr_range_text(args.rr_min, args.rr_max, args.rr_step)

    print("\n" + "=" * 150)
    print(f"ТОП-10 (score = min(PF,{core.PF_CAP}) × (1−DD/100) × (n/{args.full_trades})^power, RR {rr_range_display}):")
    print("=" * 150)

    header = (
        f"{'#':<3} {'Score':<9} {'Profit':<10} {'Ret%':<7} "
        f"{'Trades':<7} {'PFcap':<6} {'DD%':<6} {'Win%':<6} "
        f"{'Lot':<6} {'RR':<4} {'SLbuf':<6} {'MinSL':<6} "
        f"{'MinFVG':<7} {'SwpBuf':<7} {'FVGbk':<6} {'V':<3}"
    )
    print(header)
    print("-" * len(header))

    for idx, t in enumerate(top10, 1):
        p = t.params
        rr_value = resolve_param(p, "rr", default=args.rr_min, range_pair=(args.rr_min, args.rr_max))
        sl_buffer_value = resolve_param(p, "sl_buffer_pip", fixed=args.fix_sl_buffer_pip, default=10)
        min_sl_value = resolve_param(p, "min_sl_pip", default=args.min_sl_pip_min,
                                     range_pair=(args.min_sl_pip_min, args.min_sl_pip_max))
        min_fvg_value = resolve_param(p, "min_fvg_pip", fixed=args.fix_min_fvg_pip, default=1)
        fvg_lookback_value = resolve_param(p, "fvg_lookback", fixed=args.fix_fvg_lookback, default=20)
        sweep_buffer_value = resolve_param(p, "sweep_buffer_pip", fixed=args.sweep_buffer_pip, default=1)

        test_params = dict(base_params)
        test_params.update({
            "rr": rr_value,
            "sl_buffer_pip": sl_buffer_value,
            "min_sl_pip": min_sl_value,
            "min_fvg_pip": min_fvg_value,
            "fvg_lookback": fvg_lookback_value,
            "sweep_buffer_pip": sweep_buffer_value,
        })

        bal, tr, eq = core.backtest(df, test_params, pip_size, contract_size)
        m = core.calc_metrics(tr, eq, 10000)
        valid_flag = "✅" if m["trades"] >= args.min_trades else "❌"
        pf_cap = min(m["pf"], core.PF_CAP)

        line = (
            f"{idx:<3} "
            f"{(t.value if t.value is not None else -9999):<9.3f} "
            f"${m['profit']:<9.2f} {m['return_pct']:<7.2f} "
            f"{m['trades']:<7} {pf_cap:<6.2f} {m['max_dd']:<6.2f} "
            f"{m['win_rate']:<6.1f} {args.lot:<6.3f} "
            f"{rr_value:<4} {sl_buffer_value:<6} {min_sl_value:<6} "
            f"{min_fvg_value:<7} {sweep_buffer_value:<7} "
            f"{fvg_lookback_value:<6} {valid_flag:<3}"
        )
        print(line)

    if study.best_value is None or study.best_value <= -1000:
        print("\n" + "=" * 70)
        print("ВНИМАНИЕ: все попытки вернули -1000 (0 сделок)")
        print("=" * 70)
        return

    best_p = study.best_params
    best_rr = resolve_param(best_p, "rr", default=args.rr_min, range_pair=(args.rr_min, args.rr_max))
    best_sl_buffer = resolve_param(best_p, "sl_buffer_pip", fixed=args.fix_sl_buffer_pip, default=10)
    best_min_sl = resolve_param(best_p, "min_sl_pip", default=args.min_sl_pip_min,
                                range_pair=(args.min_sl_pip_min, args.min_sl_pip_max))
    best_min_fvg = resolve_param(best_p, "min_fvg_pip", fixed=args.fix_min_fvg_pip, default=1)
    best_fvg_lookback = resolve_param(best_p, "fvg_lookback", fixed=args.fix_fvg_lookback, default=20)
    best_sweep_buffer = resolve_param(best_p, "sweep_buffer_pip", fixed=args.sweep_buffer_pip, default=1)

    print("\n" + "=" * 70)
    print("ЛУЧШИЕ ПАРАМЕТРЫ (в пипсах):")
    print("=" * 70)
    print(f"  sweep_buffer_pip       = {best_sweep_buffer}")
    print(f"  rr                     = {best_rr}")
    print(f"  sl_buffer_pip          = {best_sl_buffer}")
    print(f"  min_sl_pip             = {best_min_sl}")
    print(f"  min_fvg_pip            = {best_min_fvg}")
    print(f"  fvg_lookback           = {best_fvg_lookback}")
    print(f"  lot                    = {args.lot}")
    print(f"  rr_range               = {rr_range_display}")
    print(f"  choch_mode             = {args.choch_mode}")
    print(f"  choch_lookback         = {args.choch_lookback}")
    print(f"  fvg_select             = {args.fvg_select}")
    print(f"  fvg_entry_edge         = {args.fvg_entry_edge}")
    print(f"  max_fvg_age            = {args.max_fvg_age_bars}")
    print(f"  max_spread_pct         = {args.max_spread_pct_of_sl}")
    print(f"  max_sl_reversal        = {args.max_sl_reversal_pip}")
    print(f"  force_close_eod        = {args.force_close_eod}")
    print(f"  signal_max_age         = {args.signal_max_age_bars}")
    print(f"  bos_cooldown           = {args.bos_cooldown_bars}")
    print(f"  sweep_priority         = {args.sweep_priority_bars}")
    print(f"  sweep_attempt_cd       = {args.sweep_attempt_cooldown_bars}")
    print(f"  limit_valid_bars       = {args.limit_valid_bars}")

    best_params = dict(base_params)
    best_params.update({
        "rr": best_rr,
        "sl_buffer_pip": best_sl_buffer,
        "min_sl_pip": best_min_sl,
        "min_fvg_pip": best_min_fvg,
        "fvg_lookback": best_fvg_lookback,
        "sweep_buffer_pip": best_sweep_buffer,
    })

    print("\n" + "=" * 70)
    print(f"СПИСОК ВСЕХ СДЕЛОК (SL range=[{args.min_sl_realistic},{args.max_sl_realistic}], "
          f"max_spread%={args.max_spread_pct_of_sl}, rev_SL<={args.max_sl_reversal_pip}p):")
    print("=" * 70)

    balance, trades, equity = core.backtest(
        df,
        best_params,
        pip_size,
        contract_size,
        debug=False,
        print_trades=args.print_trades,
    )
    metrics = core.calc_metrics(trades, equity, 10000)

    print("\n" + "=" * 70)
    print("ФИНАЛЬНЫЙ РЕЗУЛЬТАТ:")
    print("=" * 70)
    print(f"  Version:             {VERSION}")
    print(f"  Entry type:          {args.entry_type}")
    print(f"  RR:                  {best_rr}  (range {rr_range_display})")
    print(f"  Min SL realistic:    {args.min_sl_realistic} пипс")
    print(f"  Max SL realistic:    {args.max_sl_realistic} пипс")
    print(f"  Max spread % of SL:  {args.max_spread_pct_of_sl}")
    print(f"  Max SL reversal:     {args.max_sl_reversal_pip} пипс")
    print(f"  Force close EOD:     {'✅ ВКЛ' if args.force_close_eod else '❌ ВЫКЛ'}")
    print(f"  Sweep lookback:      {sweep_lookback} баров")
    print(f"  CHoCH mode:          {args.choch_mode}")
    print(f"  CHoCH lookback:      {args.choch_lookback} баров")
    print(f"  FVG select:          {args.fvg_select}")
    print(f"  FVG entry edge:      {args.fvg_entry_edge}")
    print(f"  Max FVG age:         {args.max_fvg_age_bars} баров")
    print(f"  Signal max age:      {args.signal_max_age_bars} баров")
    print(f"  BOS cooldown:        {args.bos_cooldown_bars} баров")
    print(f"  Sweep priority:      {args.sweep_priority_bars} баров")
    print(f"  Limit valid bars:    {args.limit_valid_bars} баров")
    print(f"  Use BOS:             {'✅ ВКЛ' if args.use_bos else '❌ ВЫКЛ'}")
    print(f"  Сделок:              {metrics['trades']}")
    print(f"  Прибыль (net):       ${metrics['profit']:.2f}")
    print(f"  Доходность:          {metrics['return_pct']:.2f}%")
    print(f"  Win Rate:            {metrics['win_rate']:.1f}%")
    print(f"  Profit Factor:       {metrics['pf']:.2f} (capped: {min(metrics['pf'], core.PF_CAP):.2f})")
    print(f"  Max Drawdown:        {metrics['max_dd']:.2f}%")
    print(f"  Sharpe:              {metrics['sharpe']:.2f}")
    print(f"  Expected/trade:      ${metrics['expected']:.2f}")
    print(f"  Финальный баланс:    ${balance:.2f}")
    print(f"  --- SL/TP в пипсах ---")
    print(f"  Средний SL:          {metrics['avg_sl_pips']} пипс")
    print(f"  Средний TP:          {metrics['avg_tp_pips']} пипс")
    print(f"  Сделок по SWEEP:     {metrics['sl_sweep_cnt']}")
    print(f"  Сделок по BOS:       {metrics['sl_bos_cnt']}")
    print(f"  --- По источникам ---")
    print(f"  BOS_IDL (разворот):  {metrics['sl_idl_rev_cnt']}")
    print(f"  BOS_IDH (разворот):  {metrics['sl_idh_rev_cnt']}")
    print(f"  SL за FVG (fallback):{metrics['sl_fvg_cnt']}")
    print(f"  EOD force-close:     {metrics['eod_cnt']}")
    print(f"  --- Издержки ---")
    print(f"  Всего спред:         ${metrics['spread_cost']:.2f}")
    print(f"  Всего свопов:        ${metrics['swap_cost']:+.2f}")

    if args.export_trades:
        core.export_trades(trades, args.export_trades)
        print(f"  Сделки экспортированы: {args.export_trades} ({len(trades)})")

    print(f"  --- Итого ---")
    print(f"  Время:               {time.time() - t0:.1f} сек")


if __name__ == "__main__":
    main()