# ICT/SMC Research Log

This file tracks research stages, intermediate results, script versions, and decisions.
Update it after every meaningful backtest / optimization / validation run.

Current script version: v50.2-h1-live

## Main hypothesis

`prev_day_london`: trade only if the previous trading day had a London-session liquidity sweep.

## Current status

```text
Baseline M15 EURUSD:
- research control;
- not production;
- without H1 is weak and risky.

H1 prev_day_london:
- live-implemented experimental candidate;
- historical validation passed;
- paper/forward ready;
- not production default.

No-DW:
- diagnostic only;
- not default;
- useful to prove H1 is not only PDL/PWL.
```

## v50.2-h1-live validation

Date: 2026-09-21 18:53 UTC

```text
H1 OFF baseline: n=87, profit=$3644.75
H1 ON candidate: n=45, profit=$3415.50
No-DW diagnostic: n=49, profit=$1189.25
No-DW + H1 diagnostic: n=15, profit=$1427.75

True trade retention vs H1 OFF: 51.7%
True profit retention vs H1 OFF: 93.7%
```

## Important interpretation

```text
When h1_report.py is run directly on the already filtered H1 ON CSV,
retention is self-referential and may show 100%.

The correct retention comparison is:
H1 ON candidate versus H1 OFF baseline.

Current correct retention is computed above from the two CSV files.
```

## Frozen baseline parameters, EURUSD M15

```text
entry_type=fvg
use_choch=True
use_bos=False
use_kz=True
rr=1.5 fixed
sl_buffer_pip=16
min_sl_pip=18
min_fvg_pip=1
fvg_lookback=30
sweep_buffer_pip=1
min_sl_realistic=20
max_sl_realistic=80
max_sl_per_day=3
limit_valid_bars=8
signal_max_age_bars=20
bos_cooldown_bars=1
sweep_priority_bars=7
sweep_attempt_cooldown_bars=1
max_fvg_age_bars=6
max_spread_pct_of_sl=0.12
max_sl_reversal_pip=25
force_close_eod=False
lot=0.5
deposit=10000
```

## Validated statistical state

```text
Full baseline:
n=87, profit=$3644.75, PF=1.49, WR=51.7%, DD=13.86%

Full post-hoc H1:
n=45, profit=$3415.50, PF=2.20, WR=60.0%, DD=5.26%

Full post-hoc no-H1:
n=42, profit=$229.25, PF=1.05, WR=42.9%, DD=15.77%

OOS pre-2026-03 H1:
n=32, profit=$2187.25, PF=2.01, WR=59.4%, DD=5.26%

OOS pre-2026-03 no-H1:
n=31, profit=-$206.75, PF=0.94, WR=41.9%, DD=15.77%

Full bootstrap H1 vs no-H1:
observed diff=$70.44, one-sided p=0.0735, P(diff > 0)=92.5%

OOS-only bootstrap H1 vs no-H1:
observed diff=$75.02, one-sided p=0.0978, P(diff > 0)=90.9%
```

## Backup policy

```text
All future patches must first run:
  ./make_backup.sh

Backups must be stored only in:
  ./backup

No backup files should be left in the project root.
```

## Next gates

```text
1. Keep RESEARCH_LOG.md updated after every meaningful run.
2. Accumulate forward/paper data:
   - control: baseline without H1;
   - candidate: baseline with --require-prev-ldn-sweep.
3. Do not draw forward conclusions until:
   - control has at least 30 trades;
   - candidate H1 has at least 15 trades.
4. Expand EURUSD M15 history backward if possible,
   ideally 2023-2026 or at least 2024-2026.
5. Validate GBPUSD only after EURUSD forward/paper is meaningful.
6. For GBPUSD, calibrate separately;
   do not copy EURUSD parameters directly.
```

## 2026-09-21 19:06 UTC — Forward pair 2026-09-15 — 2026-09-19

- Version: `v50.2-h1-live`
- Period: `2026-09-15 — 2026-09-19`
- Command:
```bash
./run_forward_pair.sh
```
- CSV summaries:
```text
out/forward/control.csv: n=0, profit=$0.00
out/forward/candidate_h1.csv: n=0, profit=$0.00
```
- Note:
```text
Warm-up starts 2026-09-14. Control is baseline without H1. Candidate is baseline with --require-prev-ldn-sweep. Zero trades in short windows is possible and should not be interpreted until control >= 30 trades and candidate H1 >= 15 trades.
```

## 2026-09-21 19:06 UTC — Manual research note

- Version: `v50.2-h1-live`
- Note:
```text
Frozen v50.2-h1-live after historical validation. No strategy changes until forward thresholds are reached.
```

## 2026-09-21 19:06 UTC — H1 live validation summary

- Version: `v50.2-h1-live`
- Period: `2025-06-19 — 2026-09-18`
- CSV summaries:
```text
out/live/H1_off_final_check.csv: n=87, profit=$3644.75
out/live/H1_on_final_check.csv: n=45, profit=$3415.50
```
- Note:
```text
H1 OFF reproduces baseline. H1 ON matches post-hoc H1. Status: experimental paper/forward candidate.
```

## 2026-09-21 19:07 UTC — Forward pair 2026-09-15 — 2026-09-19

- Version: `v50.2-h1-live`
- Period: `2026-09-15 — 2026-09-19`
- Command:
```bash
./run_forward_pair.sh
```
- CSV summaries:
```text
out/forward/control.csv: n=0, profit=$0.00
out/forward/candidate_h1.csv: n=0, profit=$0.00
```
- Note:
```text
Warm-up starts 2026-09-14. Control is baseline without H1. Candidate is baseline with --require-prev-ldn-sweep. Zero trades in short windows is possible and should not be interpreted until control >= 30 trades and candidate H1 >= 15 trades.
```

## 2026-09-21 19:17 UTC — Forward pair 2026-09-15 — 2026-09-19

- Version: `v50.2-h1-live`
- Period: `2026-09-15 — 2026-09-19`
- Command:
```bash
./run_forward_pair.sh
```
- CSV summaries:
```text
out/forward/control.csv: n=0, profit=$0.00
out/forward/candidate_h1.csv: n=0, profit=$0.00
```
- Note:
```text
Warm-up starts 2026-09-14. Control is baseline without H1. Candidate is baseline with --require-prev-ldn-sweep. Zero trades in short windows is possible and should not be interpreted until control >= 30 trades and candidate H1 >= 15 trades. Stale CSVs are deleted before each run.
```

## 2026-09-21 19:17 UTC — Tooling hardening: forward runner deletes stale CSVs

- Version: `v50.2-h1-live`
- Note:
```text
run_forward_pair.sh now removes ./out/forward/control.csv and ./out/forward/candidate_h1.csv before each run. This prevents old trades from contaminating reports when a new forward run has 0 trades.
```
