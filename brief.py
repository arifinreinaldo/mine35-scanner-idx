"""
Per-ticker contextual briefs for the nightly report.
Generates 2-3 sentence narratives based on signals, ARB history, and price context.
"""
import numpy as np
import pandas as pd

from config import ara_cap_pct


def _safe(x, default=0.0):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return default
    return float(x)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _arb_context(row: pd.Series, hist: pd.DataFrame) -> str:
    """Return an ARB cascade sentence if the stock is in one, else ''."""
    streak = int(_safe(row.get("arb_streak", 0)))
    if streak == 0:
        return ""

    raw = hist.iloc[-1]  # full OHLCV for today

    arb_mask = hist["arb_streak"] > 0
    arb_days  = hist[arb_mask]
    if arb_days.empty:
        return ""

    start_price = _safe(arb_days.iloc[0]["prev_close"])
    total_pct   = (row["close"] / start_price - 1) * 100 if start_price else 0
    first_date  = arb_days.iloc[0]["date"]

    prev_close     = _safe(raw.get("prev_close", row["close"]))
    intra_high_pct = (_safe(raw["high"]) / prev_close - 1) * 100 if prev_close else 0

    first_vol   = _safe(arb_days.iloc[0]["volume"])
    today_vol   = _safe(raw["volume"])
    vol_ratio   = today_vol / first_vol if first_vol else 1
    vol_context = (f"volume {vol_ratio:.1f}× vs first ARB day — "
                   + ("expanding seller pressure" if vol_ratio > 2 else
                      "stable" if vol_ratio > 0.7 else "declining — watch for capitulation"))

    gap_pct  = (_safe(raw.get("open")) / prev_close - 1) * 100 if prev_close else 0
    gap_note = f", gapped {'down' if gap_pct < -1 else 'up'} {gap_pct:+.1f}% at open" if abs(gap_pct) > 1.5 else ""

    if intra_high_pct < 0:
        recovery_note = " No recovery above yesterday's close — selling continued from the open."
    elif intra_high_pct < 5:
        recovery_note = f" Intraday recovery feeble ({intra_high_pct:+.1f}% above yesterday's close)."
    else:
        recovery_note = f" Bounced {intra_high_pct:+.1f}% intraday but closed at {int(_safe(row.get('close_pos', 0))*100)}% of range."

    return (f"**ARB cascade day {streak}** — down {total_pct:.1f}% since {first_date}"
            f"{gap_note}. {vol_context.capitalize()}.{recovery_note}")


def _breakout_brief(row: pd.Series, hist: pd.DataFrame) -> str:
    raw        = hist.iloc[-1]
    close      = _safe(row["close"])
    prev_close = _safe(raw.get("prev_close", close))
    close_pos  = _safe(row.get("close_pos"))
    vol_mult   = _safe(row.get("vol_mult"))
    fnet       = _safe(row.get("fnet_today_b"))

    candle = (f"closed at {int(close_pos*100)}% of its day's range "
              f"({'strong demand' if close_pos >= 0.75 else 'mixed session'})")

    open_ = _safe(raw.get("open"))
    vol_note = (f"{vol_mult:.1f}× average volume"
                + (" on a green candle — buying pressure confirmed" if open_ and close >= open_ else ""))

    fnet_note = (f"Foreign net {'buying' if fnet >= 0 else 'selling'} {abs(fnet):.2f}B today"
                 if abs(fnet) > 0.01 else "")

    ara = prev_close * (1 + ara_cap_pct(prev_close))
    ara_pct = (ara / close - 1) * 100
    ara_note = f"ARA at {ara:,.0f} ({ara_pct:.1f}% away)."

    parts = [f"{candle.capitalize()}, {vol_note}."]
    if fnet_note:
        parts.append(fnet_note + ".")
    parts.append(ara_note)
    return " ".join(parts)


def _exhaustion_brief(row: pd.Series, hist: pd.DataFrame) -> str:
    raw        = hist.iloc[-1]
    close      = _safe(row["close"])
    prev_close = _safe(raw.get("prev_close", close))
    close_pos  = _safe(row.get("close_pos"))
    vol_mult   = _safe(row.get("vol_mult"))
    fnet       = _safe(row.get("fnet_today_b"))
    reasons    = row.get("reasons", "")
    arb_streak = int(_safe(row.get("arb_streak", 0)))

    arb_ctx = _arb_context(row, hist)

    # Candle context
    candle = (f"closed at {int(close_pos*100)}% of range "
              f"({'complete rejection of rally' if close_pos <= 0.15 else 'sellers dominated' if close_pos <= 0.35 else 'mixed'})")

    # Volume
    vol_note = (f"{vol_mult:.1f}× volume"
                + (" — high-conviction distribution" if vol_mult >= 2 else " — moderate" if vol_mult >= 1.2 else ""))

    # Check for arb_bounce_trap in reasons
    trap_note = ""
    if "post-ARB bull trap" in reasons:
        arb_close = _safe(hist.iloc[-2]["close"]) if len(hist) >= 2 else prev_close
        trap_note = (f"Yesterday's ARB close ({arb_close:,.0f}) now acts as resistance — "
                     f"if tomorrow can't recover above it, continuation is likely.")

    if arb_ctx:
        body = arb_ctx
    else:
        body = f"Sellers controlled the session; {candle}, {vol_note}."

    if trap_note:
        return f"{body} {trap_note}"
    return body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_briefs(result: dict, df: pd.DataFrame) -> dict[str, str]:
    """
    Returns {ticker: brief_str} for every ticker that:
    - passed the breakout or exhaustion threshold, OR
    - triggered arb_bounce_trap
    """
    bdf = result.get("breakouts", pd.DataFrame())
    edf = result.get("exhaustion", pd.DataFrame())
    briefs: dict[str, str] = {}

    def _hist(ticker):
        return df[df["ticker"] == ticker].sort_values("date")

    # Breakout passers
    if not bdf.empty:
        for _, row in bdf[bdf["passed"]].iterrows():
            t = row["ticker"]
            hist = _hist(t)
            arb_ctx = _arb_context(row, hist)
            body = _breakout_brief(row, hist)
            briefs[f"b_{t}"] = (f"{arb_ctx} {body}".strip() if arb_ctx else body)

    # Exhaustion passers + arb_bounce_trap fires + stocks in active ARB cascade
    if not edf.empty:
        targets = edf[
            edf["passed"] |
            edf["reasons"].str.contains("post-ARB bull trap", na=False) |
            (edf["arb_streak"] >= 1)
        ]
        for _, row in targets.iterrows():
            t = row["ticker"]
            hist = _hist(t)
            briefs[f"e_{t}"] = _exhaustion_brief(row, hist)

    return briefs
