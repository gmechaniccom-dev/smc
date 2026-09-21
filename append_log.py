#!/usr/bin/env python3
"""
Append a structured entry to RESEARCH_LOG.md.

Examples:

  python3 append_log.py \
    --title "Forward pair 2026-09-15" \
    --period "2026-09-15 — 2026-09-18" \
    --csv ./out/forward/control.csv \
    --csv ./out/forward/candidate_h1.csv \
    --note "0 trades is possible in short windows."

  python3 append_log.py \
    --title "Manual note" \
    --note "Frozen v50.2-h1-live after historical validation."
"""

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def get_version() -> str:
    try:
        text = Path("core.py").read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else "unknown"
    except Exception:
        return "unknown"


def summarize_csv(path_str: str) -> dict:
    p = Path(path_str)
    out = {
        "path": str(p),
        "exists": p.exists(),
        "n": 0,
        "profit": 0.0,
        "error": None,
    }

    if not p.exists():
        return out

    if p.stat().st_size == 0:
        out["error"] = "empty file"
        return out

    try:
        df = pd.read_csv(p)
    except Exception as e:
        out["error"] = str(e)
        return out

    out["n"] = int(len(df))

    if "profit" in df.columns and out["n"] > 0:
        try:
            out["profit"] = float(df["profit"].sum())
        except Exception as e:
            out["error"] = f"profit sum error: {e}"

    return out


def main():
    ap = argparse.ArgumentParser(description="Append entry to RESEARCH_LOG.md")
    ap.add_argument("--title", required=True, help="Entry title")
    ap.add_argument("--period", default="", help="Experiment period")
    ap.add_argument("--note", default="", help="Free-form note")
    ap.add_argument("--command", default="", help="Command associated with run")
    ap.add_argument(
        "--csv",
        action="append",
        default=[],
        help="CSV path to summarize. Can be repeated.",
    )
    args = ap.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    version = get_version()

    lines = []
    lines.append("")
    lines.append(f"## {stamp} — {args.title}")
    lines.append("")
    lines.append(f"- Version: `{version}`")

    if args.period:
        lines.append(f"- Period: `{args.period}`")

    if args.command:
        lines.append("- Command:")
        lines.append("```bash")
        lines.append(args.command)
        lines.append("```")

    if args.csv:
        lines.append("- CSV summaries:")
        lines.append("```text")

        for c in args.csv:
            s = summarize_csv(c)

            if not s["exists"]:
                lines.append(f"{s['path']}: missing, n=0, profit=$0.00")
            elif s["error"]:
                lines.append(
                    f"{s['path']}: error={s['error']}, n={s['n']}, profit=${s['profit']:.2f}"
                )
            else:
                lines.append(f"{s['path']}: n={s['n']}, profit=${s['profit']:.2f}")

        lines.append("```")

    if args.note:
        lines.append("- Note:")
        lines.append("```text")
        lines.append(args.note)
        lines.append("```")

    text = "\n".join(lines) + "\n"

    log_path = Path("RESEARCH_LOG.md")

    if not log_path.exists():
        log_path.write_text("# ICT/SMC Research Log\n\n", encoding="utf-8")

    with log_path.open("a", encoding="utf-8") as f:
        f.write(text)

    print(f"✅ Appended to RESEARCH_LOG.md: {args.title}")


if __name__ == "__main__":
    main()
