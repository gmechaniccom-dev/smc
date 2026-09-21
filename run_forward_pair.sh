#!/usr/bin/env bash
set -euo pipefail

# Defaults can be overridden by environment variables.
WARMUP_START="${WARMUP_START:-2026-09-14}"
EVAL_START="${EVAL_START:-2026-09-15}"

mkdir -p ./out/forward

CONTROL="./out/forward/control.csv"
CANDIDATE="./out/forward/candidate_h1.csv"

# Always remove previous CSVs before a new forward run.
# This prevents stale trades from being reported if the new run has 0 trades.
rm -f "${CONTROL}" "${CANDIDATE}"

# Compute latest end date from data file, +1 day to include final bar.
LATEST_END=$(python3 - <<'DATEPY'
import pandas as pd

df = pd.read_csv("./data/EURUSD_M15.csv", parse_dates=["datetime"])
latest_msk = df["datetime"].max()
next_day = (latest_msk + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
print(next_day)
DATEPY
)

echo "WARMUP_START=${WARMUP_START}"
echo "EVAL_START=${EVAL_START}"
echo "LATEST_END=${LATEST_END}"

PARAMS="--symbol EURUSD --timeframe M15 \
--data-file ./data/EURUSD_M15.csv \
--trials 1 --jobs 1 --seed 42 \
--use-choch --no-bos --use-kz --limit-delay-bars 1 \
--rr-min 1.5 --rr-max 1.5 --rr-step 0.5 \
--fix-sl-buffer-pip 16 --fix-min-fvg-pip 1 --fix-fvg-lookback 30 \
--min-sl-realistic 20 --max-sl-realistic 80 \
--min-sl-pip-min 18 --min-sl-pip-max 18 --max-sl-per-day 3 \
--fvg-select first --fvg-entry-edge proximal --choch-mode swing \
--signal-max-age-bars 20 --bos-cooldown-bars 1 --sweep-priority-bars 7 \
--sweep-attempt-cooldown-bars 1 --max-fvg-age-bars 6 --limit-valid-bars 8 \
--no-force-close-eod --min-trades 1 --full-trades 1 --penalty-power 1.0 \
--sweep-buffer-pip 1 --lot 0.5"

echo
echo "=============================================================="
echo "# Forward control: baseline without H1"
echo "=============================================================="
./ict_smc_backtest.py ${PARAMS} \
    --start "${WARMUP_START}" \
    --end "${LATEST_END}" \
    --export-trades "${CONTROL}"

python3 ensure_trades_csv.py "${CONTROL}"

echo
echo "=============================================================="
echo "# Forward candidate: baseline + live H1 filter"
echo "=============================================================="
./ict_smc_backtest.py ${PARAMS} \
    --require-prev-ldn-sweep \
    --start "${WARMUP_START}" \
    --end "${LATEST_END}" \
    --export-trades "${CANDIDATE}"

python3 ensure_trades_csv.py "${CANDIDATE}"

echo
echo "=============================================================="
echo "# Forward reports"
echo "=============================================================="

python3 h1_report.py "${CONTROL}" \
    --label "FORWARD control since ${EVAL_START}" \
    --eval-start "${EVAL_START}" \
    --eval-end "${LATEST_END}" \
    --min-h1-trades 15 || true

python3 h1_report.py "${CANDIDATE}" \
    --label "FORWARD candidate H1 since ${EVAL_START}" \
    --eval-start "${EVAL_START}" \
    --eval-end "${LATEST_END}" \
    --min-h1-trades 15 || true

echo
echo "=============================================================="
echo "# Append RESEARCH_LOG.md"
echo "=============================================================="

python3 append_log.py \
    --title "Forward pair ${EVAL_START} — ${LATEST_END}" \
    --period "${EVAL_START} — ${LATEST_END}" \
    --command "./run_forward_pair.sh" \
    --csv "${CONTROL}" \
    --csv "${CANDIDATE}" \
    --note "Warm-up starts ${WARMUP_START}. Control is baseline without H1. Candidate is baseline with --require-prev-ldn-sweep. Zero trades in short windows is possible and should not be interpreted until control >= 30 trades and candidate H1 >= 15 trades. Stale CSVs are deleted before each run."

echo
echo "✅ Forward pair finished."
