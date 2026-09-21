#!/usr/bin/env bash
set -euo pipefail

mkdir -p ./backup

TS="$(date -u +%Y%m%d_%H%M%S)"

FILES=(
  core.py
  ict_smc_backtest.py
  h1_report.py
  RESEARCH_LOG.md
)

echo "Creating backups in ./backup with timestamp ${TS}"

for f in "${FILES[@]}"; do
  if [[ -f "$f" ]]; then
    base="$(basename "$f")"
    dest="./backup/${base}.${TS}.bak"
    cp -v "$f" "$dest"
  else
    echo "skip missing: $f"
  fi
done

echo "Backup finished."
