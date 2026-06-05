"""End-to-end nightly run: fetch → compute → score → backtest → report → notify."""
import argparse

import pandas as pd
from rich.console import Console

from backtest import run_backtest
from config import BACKFILL_DAYS, UNIVERSE
from db import load_history
from fetch import backfill
from indicators import add_indicators
from notify import send_scan_summary
from report import build, save
from score import run_scoring

console = Console()


def main(days_back: int, skip_fetch: bool, print_report: bool, backtest_days: int):
    if not skip_fetch:
        console.rule("[bold]1. Fetch")
        stats = backfill(days_back)
        console.print(stats)

    console.rule("[bold]2. Load history + compute indicators")
    df = load_history()
    if df.empty:
        console.print("[red]No data in DB. Run backfill first.[/red]")
        return
    console.print(f"Loaded {len(df):,} rows for {df['ticker'].nunique()} tickers, "
                  f"{df['date'].nunique()} dates ({df['date'].min()} → {df['date'].max()})")

    parts = []
    for ticker, g in df.groupby("ticker", sort=False):
        g2 = add_indicators(g)
        g2["ticker"] = ticker
        parts.append(g2)
    df = pd.concat(parts, ignore_index=True)

    console.rule("[bold]3. Score")
    result = run_scoring(df)
    console.print(f"Universe: {result['universe_size']}, "
                  f"breakouts: {len(result['breakouts'])}, "
                  f"exhaustion: {len(result['exhaustion'])}")

    bt = None
    if backtest_days > 0:
        console.rule("[bold]4. Backtest")
        bt = run_backtest(df, backtest_days)
        if bt:
            b_eval, e_eval = bt["breakout_eval"], bt["exhaustion_eval"]
            b_hits = b_eval["hit"].sum() if not b_eval.empty else 0
            e_hits = e_eval["hit"].sum() if not e_eval.empty else 0
            console.print(f"Breakout hit rate: {b_hits}/{len(b_eval)} | "
                          f"Exhaustion hit rate: {e_hits}/{len(e_eval)} "
                          f"(ref: {bt['ref_date']})")
        else:
            console.print("[yellow]Backtest skipped — insufficient history[/yellow]")

    console.rule("[bold]5. Report")
    text = build(result, bt, df)
    p = save(text, result["date"])
    console.print(f"[green]Saved {p}[/green]")
    if print_report:
        print()
        print(text)

    send_scan_summary(result["date"], result["universe_size"],
                      result["n_breakouts_passed"], result["n_exhaustion_passed"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-back", type=int, default=BACKFILL_DAYS)
    ap.add_argument("--skip-fetch", action="store_true", help="Use DB only, no network")
    ap.add_argument("--no-print", action="store_true")
    ap.add_argument("--backtest", type=int, default=7, metavar="DAYS",
                    help="Evaluate signals from N calendar days ago (0 to skip, default 7)")
    args = ap.parse_args()
    main(args.days_back, args.skip_fetch, not args.no_print, args.backtest)
