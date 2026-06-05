"""
Component-level signal analysis: which scoring components actually predict outcomes?

Run: python3 analyze.py [--hold-days N] [--sample-every N] [--min-score N]

For each sampled historical date (with enough history + forward data):
- Replay scoring on all universe tickers
- Record which components fired
- Measure actual price return after hold_days trading days
- Compute per-component hit rates vs baseline

Output tells you which components have lift > 1.0 (predictive) and which hurt (lift < 1).
"""
import argparse

import pandas as pd
from rich.console import Console
from rich.table import Table

from db import load_history
from indicators import add_indicators
from score import score_breakout, score_exhaustion, universe_filter

console = Console()

BREAKOUT_COMPONENTS  = ["close_pos", "uptrend", "breakout_10d", "vol_surge",
                         "rsi_zone", "foreign_flow", "macd_rising", "ara_proximity"]
EXHAUSTION_COMPONENTS = ["gap_close", "bear_reversal", "distribution", "foreign_flip",
                          "rsi_extreme", "failed_breakout", "macd_rollover", "arb_bounce_trap"]

HIT_PCT = 2.0  # threshold for a "hit"


def _load_df() -> pd.DataFrame:
    console.print("Loading history + computing indicators...")
    df_raw = load_history()
    parts = []
    for ticker, g in df_raw.groupby("ticker", sort=False):
        g2 = add_indicators(g)
        g2["ticker"] = ticker
        parts.append(g2)
    return pd.concat(parts, ignore_index=True)


def run_analysis(df: pd.DataFrame, hold_days: int = 5, sample_every: int = 5,
                 min_score: int = 1) -> dict:
    all_dates = sorted(df["date"].unique())
    # Need >= 25 days of history before ref_date, >= hold_days after it
    if len(all_dates) < 25 + hold_days:
        return {}

    ref_dates = all_dates[25:-hold_days:sample_every]
    console.print(f"Analyzing {len(ref_dates)} reference dates "
                  f"(every {sample_every} trading days, {hold_days}d hold)")

    breakout_rows = []
    exhaust_rows = []

    for ref_date in ref_dates:
        hist_slice = df[df["date"] <= ref_date]
        latest_date = hist_slice["date"].max()
        latest = hist_slice[hist_slice["date"] == latest_date].set_index("ticker")

        # Universe filter
        survivors = universe_filter(latest)

        # Forward date: hold_days trading days after ref_date
        fwd_dates = [d for d in all_dates if d > ref_date]
        if len(fwd_dates) < hold_days:
            continue
        fwd_date = fwd_dates[hold_days - 1]
        fwd_prices = df[df["date"] == fwd_date].set_index("ticker")["close"]

        for ticker, row in survivors.iterrows():
            hist = hist_slice[hist_slice["ticker"] == ticker].sort_values("date")
            if len(hist) < 25 or ticker not in fwd_prices.index:
                continue
            entry = row["close"]
            fwd = fwd_prices[ticker]
            ret_pct = (fwd / entry - 1) * 100 if entry else 0

            _, _, bd = score_breakout(row, hist)
            if sum(bd["components"].values()) >= min_score:
                breakout_rows.append({
                    "ret_pct": ret_pct,
                    "hit": ret_pct >= HIT_PCT,
                    **bd["components"],
                })

            _, _, ed = score_exhaustion(row, hist)
            if sum(ed["components"].values()) >= min_score:
                exhaust_rows.append({
                    "ret_pct": ret_pct,
                    "hit": ret_pct <= -HIT_PCT,
                    **ed["components"],
                })

    return {
        "breakout": pd.DataFrame(breakout_rows),
        "exhaustion": pd.DataFrame(exhaust_rows),
        "hold_days": hold_days,
    }


def _component_table(df: pd.DataFrame, components: list[str], label: str) -> None:
    if df.empty:
        console.print(f"[yellow]No {label} data[/yellow]")
        return

    baseline = df["hit"].mean() * 100
    t = Table(title=f"{label} components  (baseline hit rate: {baseline:.1f}%,  n={len(df)})",
              show_header=True, header_style="bold")
    t.add_column("Component", style="cyan")
    t.add_column("Fired", justify="right")
    t.add_column("Hit %", justify="right")
    t.add_column("Baseline %", justify="right")
    t.add_column("Lift", justify="right")
    t.add_column("Verdict", justify="left")

    rows = []
    for col in components:
        if col not in df.columns:
            continue
        fired = df[df[col] == True]
        if len(fired) == 0:
            continue
        hr = fired["hit"].mean() * 100
        lift = hr / baseline if baseline > 0 else 0
        rows.append((col, len(fired), hr, baseline, lift))

    rows.sort(key=lambda x: -x[4])
    for col, n, hr, bl, lift in rows:
        if lift >= 1.3:
            verdict = "[green]strong signal[/green]"
        elif lift >= 1.0:
            verdict = "[yellow]weak signal[/yellow]"
        else:
            verdict = "[red]noise / hurts[/red]"
        t.add_row(col, str(n), f"{hr:.1f}%", f"{bl:.1f}%", f"{lift:.2f}x", verdict)

    console.print(t)


def _suggest_weights(df_b: pd.DataFrame, df_e: pd.DataFrame) -> None:
    """Print weight adjustment suggestions based on lift scores."""
    from config import SCORE_WEIGHTS, BREAKOUT, EXHAUSTION

    # Category mapping
    b_cat = {
        "close_pos": "price", "uptrend": "price", "breakout_10d": "price",
        "rsi_zone": "price", "ara_proximity": "price",
        "vol_surge": "context", "macd_rising": "context",
        "foreign_flow": "foreign",
    }
    e_cat = {
        "gap_close": "price", "rsi_extreme": "price", "failed_breakout": "price",
        "arb_bounce_trap": "price",
        "bear_reversal": "context", "distribution": "context", "macd_rollover": "context",
        "foreign_flip": "foreign",
    }

    console.print("\n[bold]Weight adjustment suggestions (relative lifts per category):[/bold]")
    for signal_type, df, cat_map in [("Breakout", df_b, b_cat), ("Exhaustion", df_e, e_cat)]:
        if df.empty:
            continue
        baseline = df["hit"].mean()
        cat_lifts: dict[str, list] = {}
        for col, cat in cat_map.items():
            if col not in df.columns:
                continue
            fired = df[df[col] == True]
            if len(fired) == 0:
                continue
            lift = (fired["hit"].mean() / baseline) if baseline > 0 else 1.0
            cat_lifts.setdefault(cat, []).append(lift)
        avg_lifts = {cat: sum(ls)/len(ls) for cat, ls in cat_lifts.items()}
        total = sum(avg_lifts.values())
        if total == 0:
            continue
        new_weights = {cat: round(v/total, 2) for cat, v in avg_lifts.items()}
        console.print(f"\n  {signal_type} (data-driven weights vs current):")
        for tier in SCORE_WEIGHTS:
            cur = SCORE_WEIGHTS[tier]
            console.print(f"    [{tier:5s}]  price {cur['price']:.2f}→{new_weights.get('price',0):.2f}  "
                          f"foreign {cur['foreign']:.2f}→{new_weights.get('foreign',0):.2f}  "
                          f"context {cur['context']:.2f}→{new_weights.get('context',0):.2f}")
        console.print("  (these are aggregated across tiers; IDX data too limited for per-tier splits)")


def main(hold_days: int = 5, sample_every: int = 5, min_score: int = 1) -> None:
    df = _load_df()
    result = run_analysis(df, hold_days, sample_every, min_score)
    if not result:
        console.print("[red]Not enough history for analysis.[/red]")
        return

    console.print(f"\n[bold]Hold period:[/bold] {result['hold_days']} trading days  "
                  f"[bold]Hit threshold:[/bold] ±{HIT_PCT}%\n")
    _component_table(result["breakout"],   BREAKOUT_COMPONENTS,  "BREAKOUT")
    console.print()
    _component_table(result["exhaustion"], EXHAUSTION_COMPONENTS, "EXHAUSTION")
    _suggest_weights(result["breakout"], result["exhaustion"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Analyze signal component predictive power")
    ap.add_argument("--hold-days",    type=int, default=5,  help="Trading days to measure outcome")
    ap.add_argument("--sample-every", type=int, default=5,  help="Sample one reference date per N days")
    ap.add_argument("--min-score",    type=int, default=1,  help="Min components fired to include row")
    args = ap.parse_args()
    main(args.hold_days, args.sample_every, args.min_score)
