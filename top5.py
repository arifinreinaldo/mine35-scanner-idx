"""Quick top-5 conviction picks with entry / exit / cut-loss levels."""
import argparse

import pandas as pd
from rich.console import Console

from brief import generate_briefs
from config import ara_cap_pct
from db import load_history
from fetch import backfill
from indicators import add_indicators
from score import run_scoring

console = Console()
plain_console = Console(no_color=True, highlight=False)

# Cut-loss buffer: if today's low is within 3% of close, use ATR-based stop instead
MIN_STOP_PCT = 0.05   # minimum 5% cut-loss distance for breakouts
ARB_ESTIMATE = 0.15   # estimated ARB (lower circuit breaker) for exhaustion targets


def _build_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for ticker, g in df_raw.groupby("ticker", sort=False):
        g2 = add_indicators(g)
        g2["ticker"] = ticker
        parts.append(g2)
    return pd.concat(parts, ignore_index=True)


def _levels_breakout(row: pd.Series, hist: pd.DataFrame):
    """Return (entry, exit, cut_loss) for a breakout setup."""
    raw    = hist.iloc[-1]
    entry  = float(row["close"])

    # Exit = tomorrow's ARA (maximum one-day upside from entry)
    exit_p = entry * (1 + ara_cap_pct(entry))

    # Cut loss = today's low, but at least MIN_STOP_PCT below entry
    today_low  = float(raw["low"])
    floor_stop = entry * (1 - MIN_STOP_PCT)
    cut_loss   = min(today_low, floor_stop)   # whichever is lower = tighter safety net

    return entry, exit_p, cut_loss


def _levels_exhaustion(row: pd.Series, hist: pd.DataFrame):
    """Return (entry, exit, cut_loss) for an exhaustion/short setup."""
    raw    = hist.iloc[-1]
    entry  = float(row["close"])

    # Exit = ARB estimate (maximum one-day downside)
    exit_p = entry * (1 - ARB_ESTIMATE)

    # Cut loss = 3% above today's high (stop out if buyers recapture highs)
    today_high = float(raw["high"])
    cut_loss   = today_high * 1.03

    return entry, exit_p, cut_loss


def _rr(entry, exit_p, cut_loss, is_short=False):
    if is_short:
        gain = entry - exit_p
        risk = cut_loss - entry
    else:
        gain = exit_p - entry
        risk = entry - cut_loss
    return gain / risk if risk > 0 else 0


def _print_pick(rank, row, hist, brief, prefix):
    ticker  = row["ticker"]
    name    = str(row.get("name", "") or "")
    tier    = row.get("tier", "")
    chg     = row["change_pct"]
    wscore  = row.get("wscore", 0)
    passed_ = row.get("passed", False)
    reasons = row.get("reasons", "")
    is_short = prefix == "e_"

    if is_short:
        entry, exit_p, cut_loss = _levels_exhaustion(row, hist)
    else:
        entry, exit_p, cut_loss = _levels_breakout(row, hist)

    rr = _rr(entry, exit_p, cut_loss, is_short)
    upside_pct = abs(exit_p / entry - 1) * 100
    risk_pct   = abs(cut_loss / entry - 1) * 100

    mark = "[green]★[/green]" if passed_ else " "
    chg_color = "green" if chg >= 0 else "red"

    # Header line
    console.print(
        f"{mark} [bold]{rank}. {ticker}[/bold]  "
        f"[dim]{name[:35]}[/dim]  "
        f"[yellow][{tier}][/yellow]  "
        f"[{chg_color}]{chg:+.1f}% today[/]  "
        f"wscore [bold]{wscore:.1f}[/bold]"
    )

    # Levels line
    arrow = "↓" if is_short else "↑"
    console.print(
        f"   Entry  [bold white]{entry:>8,.0f}[/bold white]    "
        f"Exit {arrow} [bold green]{exit_p:>8,.0f}[/bold green] [dim]({upside_pct:+.1f}%)[/dim]    "
        f"Cut loss [bold red]{cut_loss:>8,.0f}[/bold red] [dim](-{risk_pct:.1f}%)[/dim]    "
        f"R/R [bold {'green' if rr >= 2 else 'yellow' if rr >= 1 else 'red'}]{rr:.1f}×[/bold {'green' if rr >= 2 else 'yellow' if rr >= 1 else 'red'}]"
    )

    # Signal summary
    if reasons and reasons != "(no signals)":
        console.print(f"   [dim]{reasons}[/dim]")

    # Brief
    if brief:
        console.print(f"   [italic]{brief}[/italic]")

    console.print()


def _top5(candidates: pd.DataFrame, df: pd.DataFrame, label: str,
          briefs: dict, prefix: str) -> None:
    if candidates.empty:
        console.print(f"[dim]No {label} candidates.[/dim]")
        return

    passed = candidates[candidates["passed"]].head(5)
    if len(passed) < 5:
        rest = candidates[~candidates["passed"]].head(5 - len(passed))
        picks = pd.concat([passed, rest])
    else:
        picks = passed

    console.print(f"\n[bold cyan]── {label.upper()} ──[/bold cyan]")

    for rank, (_, row) in enumerate(picks.iterrows(), 1):
        ticker = row["ticker"]
        hist   = df[df["ticker"] == ticker].sort_values("date")
        brief  = briefs.get(f"{prefix}{ticker}", "")
        _print_pick(rank, row, hist, brief, prefix)


def _plain_line(rank, row, hist, passed, prefix):
    """Single compact line for ntfy / plain output."""
    ticker = row["ticker"]
    chg    = row["change_pct"]
    mark   = "★" if passed else " "

    if prefix == "e_":
        entry, exit_p, cut_loss = _levels_exhaustion(row, hist)
        arrow = "↓"
    else:
        entry, exit_p, cut_loss = _levels_breakout(row, hist)
        arrow = "↑"

    rr = _rr(entry, exit_p, cut_loss, prefix == "e_")
    return (f"{mark}{rank}. {ticker} {chg:+.1f}% | "
            f"Entry {entry:,.0f} | Exit{arrow} {exit_p:,.0f} | CL {cut_loss:,.0f} | R/R {rr:.1f}x")


def plain_output(result: dict, df: pd.DataFrame) -> str:
    """Plain text top 5 — suitable for ntfy notification."""
    lines = [f"IDX Top 5 — {result['date']} (universe: {result['universe_size']})"]

    for label, candidates, prefix in [
        ("BREAKOUT",   result["breakouts"],  "b_"),
        ("EXHAUSTION", result["exhaustion"], "e_"),
    ]:
        lines.append(f"\n{label}:")
        passed = candidates[candidates["passed"]].head(5)
        rest   = candidates[~candidates["passed"]].head(5 - len(passed)) if len(passed) < 5 else pd.DataFrame()
        picks  = pd.concat([passed, rest])
        for rank, (_, row) in enumerate(picks.iterrows(), 1):
            hist = df[df["ticker"] == row["ticker"]].sort_values("date")
            lines.append(_plain_line(rank, row, hist, row.get("passed", False), prefix))

    return "\n".join(lines)


def main(fetch: bool = False, days_back: int = 5, plain: bool = False) -> None:
    if fetch:
        console.print("[bold]Fetching latest data…[/bold]")
        backfill(days_back)

    df_raw = load_history()
    if df_raw.empty:
        console.print("[red]No data. Run: python3 run_nightly.py --days-back 90[/red]")
        return

    df     = _build_df(df_raw)
    result = run_scoring(df)

    if plain:
        print(plain_output(result, df))
        return

    briefs = generate_briefs(result, df)
    console.rule(f"[bold]IDX Top 5 — {result['date']}  (universe: {result['universe_size']})[/bold]")
    _top5(result["breakouts"],  df, "Breakout",  briefs, "b_")
    _top5(result["exhaustion"], df, "Exhaustion", briefs, "e_")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Top 5 conviction picks with entry/exit/cut-loss")
    ap.add_argument("--fetch",     action="store_true", help="Fetch latest data first")
    ap.add_argument("--days-back", type=int, default=5)
    ap.add_argument("--plain",     action="store_true", help="Plain text output (no colors, for ntfy)")
    args = ap.parse_args()
    main(args.fetch, args.days_back, args.plain)
