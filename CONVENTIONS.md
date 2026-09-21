# SMC4 Project Conventions

## Project Context
This is an ICT/SMC backtest research project for EURUSD M15.
The goal is to separate random noise from stable market regimes.
Current status: experimental, not production. Frozen version: v50.2-h1-live.

## Critical Rules (NEVER violate)
- DO NOT change the core backtest logic in core.py without explicit instruction.
- DO NOT modify frozen parameters listed in RESEARCH_LOG.md.
- DO NOT delete or rewrite RESEARCH_LOG.md entries.
- DO NOT commit changes to .env or data files.
- ALWAYS run ./make_backup.sh before any change to core.py.
- The prev_day_london filter (H1) is an experimental candidate. Do not "optimize" it.

## Code Style
- Python 3.12, PEP8.
- Use type hints where existing code has them.
- Preserve existing function signatures in core.py.
- Do not add new dependencies without asking.

## Aider Workflow for This Project
- Before editing, read RESEARCH_LOG.md and CONVENTIONS.md.
- After editing, run: python3 -m py_compile core.py ict_smc_backtest.py
- For backtest changes, always show a diff before applying.
- Never use --auto-commits on this repo (research history must be manual).

## Files You May Edit
- h1_report.py, append_log.py, ensure_trades_csv.py
- forward_h1_test.py
- ict_smc_backtest.py (CLI additions only)
- New helper/analysis scripts

## Files You Must Never Edit
- core.py (only for bug fixes, with explicit user approval)
- RESEARCH_LOG.md (append-only via append_log.py)
- backup/ (read-only archive)
- data/ (raw market data)
- .env (secrets)
- out/ (research outputs)
