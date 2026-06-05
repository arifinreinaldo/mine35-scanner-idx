"""Backtest: replay scoring from N days ago, measure performance against current prices."""
from datetime import datetime, timedelta

import pandas as pd

from indicators import add_indicators
from score import run_scoring

HIT_PCT_BREAKOUT = 2.0   # % gain to count as a hit
HIT_PCT_EXHAUSTION = 2.0  # % drop to count as a hit


def _trading_days_ago(all_dates: list[str], calendar_days: int) -> str | None:
    """Return the latest DB date that is at least `calendar_days` before the most recent date."""
    latest = max(all_dates)
    cutoff = (datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=calendar_days)).strftime("%Y-%m-%d")
    past = [d for d in all_dates if d <= cutoff]
    return max(past) if past else None


def run_backtest(df: pd.DataFrame, days_ago: int = 7) -> dict | None:
    """
    Replay scoring as-of `days_ago` calendar days back and evaluate against today's prices.
    Returns None if there isn't enough history.
    """
    all_dates = sorted(df["date"].unique())
    if len(all_dates) < 2:
        return None

    ref_date = _trading_days_ago(all_dates, days_ago)
    if ref_date is None:
        return None

    today = max(all_dates)

    # Slice to historical view — recompute indicators to avoid any forward-bias
    hist_raw = df[df["date"] <= ref_date][
        ["date", "ticker", "name", "prev_close", "open", "high", "low", "close",
         "volume", "value", "foreign_buy", "foreign_sell", "foreign_net"]
    ].copy()

    parts = []
    for ticker, g in hist_raw.groupby("ticker", sort=False):
        g2 = add_indicators(g)
        g2["ticker"] = ticker
        parts.append(g2)
    if not parts:
        return None
    hist_df = pd.concat(parts, ignore_index=True)

    result = run_scoring(hist_df)

    # Current prices for performance lookup
    curr_prices = df[df["date"] == today].set_index("ticker")["close"]

    def evaluate(candidates: pd.DataFrame, direction: str) -> pd.DataFrame:
        rows = []
        for _, row in candidates[candidates["passed"]].iterrows():
            ticker = row["ticker"]
            if ticker not in curr_prices.index:
                continue
            entry = row["close"]
            current = curr_prices[ticker]
            ret_pct = (current / entry - 1) * 100 if entry else 0
            if direction == "breakout":
                hit = ret_pct >= HIT_PCT_BREAKOUT
            else:
                hit = ret_pct <= -HIT_PCT_EXHAUSTION
            rows.append({
                "ticker": ticker,
                "entry": entry,
                "current": current,
                "ret_pct": round(ret_pct, 1),
                "hit": hit,
                "wscore": row.get("wscore", 0),
                "reasons": (row.get("reasons") or "")[:80],
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["ticker", "entry", "current", "ret_pct", "hit", "wscore", "reasons"]
        )

    return {
        "ref_date": ref_date,
        "today": today,
        "breakout_eval": evaluate(result["breakouts"], "breakout"),
        "exhaustion_eval": evaluate(result["exhaustion"], "exhaustion"),
    }
