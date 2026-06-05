"""Scoring: breakout + exhaustion. Operates on per-ticker history with indicators."""
import numpy as np
import pandas as pd

from config import (
    ARA_TIERS, BREAKOUT, EXHAUSTION, SCORE_WEIGHTS, UNIVERSE,
    ara_cap_pct, liquidity_tier,
)
# Remove deprecated key if config upgraded from old version
_EXHAUSTION_RSI_KEY = "rsi_extreme" if "rsi_extreme" in EXHAUSTION else "rsi_overbought"

# Max signals per category — must match the components coded below
_BREAKOUT_TOTALS = {"price": 5, "foreign": 1, "context": 2}
_EXHAUST_TOTALS  = {"price": 4, "foreign": 1, "context": 3}  # price: gap_close, rsi_extreme, failed_breakout, arb_bounce_trap


def _weighted_score(cats: dict, totals: dict, weights: dict) -> float:
    n = sum(totals.values())
    return sum(cats.get(k, 0) / totals[k] * weights[k] for k in totals) * n


def universe_filter(latest: pd.DataFrame) -> pd.DataFrame:
    """latest: one row per ticker, the most recent date. Returns filtered subset."""
    f = latest
    # Exclude price-floor-pinned stocks: high == low means zero range (stuck at min price)
    has_range = (f["high"] - f["low"]) > 0
    mask = (
        (f["close"] >= UNIVERSE["min_price"]) &
        (f["close"] <= UNIVERSE["max_price"]) &
        (f["adtv20"] >= UNIVERSE["min_adtv_idr"]) &
        (f["close"].notna()) &
        has_range
    )
    return f[mask].copy()


def _safe(x, default=0.0):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return default
    return x


def score_breakout(row: pd.Series, hist: pd.DataFrame) -> tuple[int, list[str], dict]:
    """Return (score, reasons, debug). Score is 0..8, reasons explain hits."""
    reasons: list[str] = []
    s = 0
    price_s = foreign_s = context_s = 0

    close = _safe(row["close"])
    high = _safe(row["high"])
    low = _safe(row["low"])
    prev_close = _safe(row["prev_close"], close)
    close_pos = _safe(row.get("close_pos"))
    ema20 = _safe(row.get("ema20"))
    ema50 = _safe(row.get("ema50"))
    rsi14 = _safe(row.get("rsi14"))
    macd_hist = _safe(row.get("macd_hist"))
    high_close_10 = _safe(row.get("high_close_10"))
    volume = _safe(row.get("volume"))
    adv20 = _safe(row.get("adv20"), 1)
    foreign_net = _safe(row.get("foreign_net"))
    fnet_5d = _safe(row.get("fnet_5d"))
    bb_width = _safe(row.get("bb_width"))

    vol_mult = volume / adv20 if adv20 else 0
    cap_pct = ara_cap_pct(prev_close)
    ara_price = prev_close * (1 + cap_pct)
    ara_distance = (ara_price - close) / close if close else 1
    hit_ara = high >= ara_price * 0.999
    near_ara = ara_distance < BREAKOUT["ara_proximity_pct"]
    prev_mh = _safe(hist.iloc[-2].get("macd_hist")) if len(hist) >= 2 else 0.0

    # vol_surge: only counts if it's a green candle (buying pressure, not distribution)
    _open = _safe(row.get("open"))
    _green = close >= _open if _open else True
    c = {
        "close_pos":    close_pos >= (1 - BREAKOUT["close_in_top_pct_of_range"]),
        "uptrend":      close > ema20 > ema50 > 0,
        "breakout_10d": high_close_10 > 0 and close > high_close_10,
        "vol_surge":    vol_mult >= BREAKOUT["vol_mult_vs_adv20"] and (_green if BREAKOUT.get("vol_must_be_green") else True),
        "rsi_zone":     BREAKOUT["rsi_min"] <= rsi14 <= BREAKOUT["rsi_max"],
        "foreign_flow": foreign_net > 0 and fnet_5d > 0,
        "macd_rising":  macd_hist > 0 and macd_hist > prev_mh,
        "ara_proximity": near_ara and not hit_ara and close_pos > 0.75,
    }

    # 1. [price]
    if c["close_pos"]:
        s += 1; price_s += 1; reasons.append(f"close at {int(close_pos*100)}% of range")
    # 2. [price]
    if c["uptrend"]:
        s += 1; price_s += 1; reasons.append("uptrend (close>EMA20>EMA50)")
    # 3. [price]
    if c["breakout_10d"]:
        s += 1; price_s += 1; reasons.append(f"10-day close breakout > {high_close_10:.0f}")
    # 4. [context] — requires green candle to distinguish buying from distribution
    if c["vol_surge"]:
        s += 1; context_s += 1; reasons.append(f"vol {vol_mult:.1f}x ADV20 (green)")
    # 5. [price]
    if c["rsi_zone"]:
        s += 1; price_s += 1; reasons.append(f"RSI {rsi14:.0f} in {BREAKOUT['rsi_min']}-{BREAKOUT['rsi_max']} zone")
    # 6. [foreign]
    if c["foreign_flow"]:
        s += 1; foreign_s += 1; reasons.append(f"foreign net+ today & 5d (+{foreign_net/1e9:.1f}b / +{fnet_5d/1e9:.1f}b)")
    # 7. [context]
    if c["macd_rising"] and len(hist) >= 2:
        s += 1; context_s += 1; reasons.append("MACD hist rising +")
    # 8. [price]
    if c["ara_proximity"]:
        s += 1; price_s += 1; reasons.append(f"approached ARA {ara_price:.0f} (~{ara_distance*100:.1f}%) without hit, strong close")

    debug = {
        "vol_mult": round(vol_mult, 2),
        "ara_distance_pct": round(ara_distance * 100, 2),
        "hit_ara": hit_ara,
        "rsi14": round(rsi14, 1),
        "fnet_5d_b": round(fnet_5d / 1e9, 2),
        "bb_width": round(bb_width, 4) if bb_width else None,
        "cats": {"price": price_s, "foreign": foreign_s, "context": context_s},
        "components": c,
    }
    return s, reasons, debug


def score_exhaustion(row: pd.Series, hist: pd.DataFrame) -> tuple[int, list[str], dict]:
    reasons: list[str] = []
    s = 0
    price_s = foreign_s = context_s = 0

    close = _safe(row["close"])
    high = _safe(row["high"])
    low = _safe(row["low"])
    open_ = _safe(row["open"])
    prev_close = _safe(row["prev_close"], close)
    close_pos = _safe(row.get("close_pos"))
    rsi14 = _safe(row.get("rsi14"))
    volume = _safe(row.get("volume"))
    adv20 = _safe(row.get("adv20"), 1)
    foreign_net = _safe(row.get("foreign_net"))
    fnet_5d = _safe(row.get("fnet_5d"))
    macd_hist = _safe(row.get("macd_hist"))
    ema20 = _safe(row.get("ema20"))

    gapped_up = open_ > prev_close * 1.005
    prior_fnet = hist["foreign_net"].iloc[-6:-1].sum() if len(hist) >= 6 else 0
    prev_arb   = bool(row.get("prev_arb", False))
    arb_close  = _safe(hist.iloc[-2]["close"]) if len(hist) >= 2 and prev_arb else 0

    _last4 = hist.tail(4) if len(hist) >= 4 else None
    _prior_up = (
        (_last4["close"].iloc[:-1].diff().fillna(0).iloc[1:] > 0).all()
        if _last4 is not None else False
    )
    _resistance = hist["high"].iloc[-11:-1].max() if len(hist) >= 11 else 0.0
    _prev_mh  = _safe(hist.iloc[-2].get("macd_hist")) if len(hist) >= 3 else 0.0
    _prev2_mh = _safe(hist.iloc[-3].get("macd_hist")) if len(hist) >= 3 else 0.0

    _n = EXHAUSTION["vol_distribution_lookback"]
    _dist_tail = hist.tail(_n + 1) if len(hist) >= _n + 1 else None
    if _dist_tail is not None:
        _vol_trend = _dist_tail["volume"].diff().dropna().mean()
        _price_rng = _dist_tail["close"].max() - _dist_tail["close"].min()
        _price_pct = _price_rng / _dist_tail["close"].iloc[0] if _dist_tail["close"].iloc[0] else 1
    else:
        _vol_trend = 0; _price_pct = 1

    _rsi_tail = hist.tail(6) if len(hist) >= 6 else None
    # rsi_extreme: only fire on truly extreme RSI — divergence had 0.74x lift (data: extended stocks continue up)
    _rsi_thresh = EXHAUSTION.get("rsi_extreme", EXHAUSTION.get("rsi_overbought", 80))
    _rsi_extreme = rsi14 > _rsi_thresh

    # Post-ARB bull trap: yesterday hit ARB, today shot up >= threshold but closed in bottom 30%
    _arb_bounce_high = (high / arb_close - 1) if arb_close > 0 else 0
    c = {
        "gap_close":       gapped_up and close_pos <= EXHAUSTION["close_in_bottom_pct_of_range"],
        "bear_reversal":   _prior_up and close < open_ and volume > adv20 * 1.2,
        "distribution":    _dist_tail is not None and _vol_trend > 0 and _price_pct < 0.03,
        "foreign_flip":    foreign_net < 0 and prior_fnet > 0 and abs(foreign_net) > prior_fnet * 0.3,
        "rsi_extreme":     _rsi_extreme,
        "failed_breakout": _resistance > 0 and high > _resistance and close < _resistance,
        "macd_rollover":   macd_hist > 0 and macd_hist < _prev_mh < _prev2_mh,
        "arb_bounce_trap": (prev_arb
                            and _arb_bounce_high >= EXHAUSTION["arb_bounce_min_pct"]
                            and close_pos <= EXHAUSTION["close_in_bottom_pct_of_range"]),
    }

    # 1. [price]
    if c["gap_close"]:
        s += 1; price_s += 1; reasons.append(f"gap up, close at {int(close_pos*100)}% of range")
    # 2. [context]
    if c["bear_reversal"]:
        s += 1; context_s += 1; reasons.append("bearish reversal after 3-day up streak on rising vol")
    # 3. [context]
    if c["distribution"]:
        s += 1; context_s += 1; reasons.append(f"distribution: vol↑ price flat ({_price_pct*100:.1f}%) over {_n}d")
    # 4. [foreign]
    if c["foreign_flip"]:
        s += 1; foreign_s += 1; reasons.append(f"foreign flip to sell ({foreign_net/1e9:.1f}b) after 5d net buy")
    # 5. [price] — only extreme RSI + closes weak (not just momentum continuation)
    if c["rsi_extreme"]:
        s += 1; price_s += 1; reasons.append(f"RSI {rsi14:.0f} extreme overbought, closed weak ({int(close_pos*100)}% of range)")
    # 6. [price]
    if c["failed_breakout"]:
        s += 1; price_s += 1; reasons.append(f"failed breakout above {_resistance:.0f}")
    # 7. [context]
    if c["macd_rollover"]:
        s += 1; context_s += 1; reasons.append("MACD hist rolling over")
    # 8. [price] — post-ARB bull trap: shot high after circuit breaker, sellers crushed it
    if c["arb_bounce_trap"]:
        s += 1; price_s += 1
        reasons.append(f"post-ARB bull trap: bounced +{_arb_bounce_high*100:.0f}% intraday, closed at {int(close_pos*100)}% of range")

    debug = {
        "rsi14": round(rsi14, 1),
        "close_pos": round(close_pos, 2),
        "fnet_today_b": round(foreign_net / 1e9, 2),
        "fnet_prior5d_b": round(prior_fnet / 1e9, 2),
        "arb_bounce_pct": round(_arb_bounce_high * 100, 1),
        "cats": {"price": price_s, "foreign": foreign_s, "context": context_s},
        "components": c,
    }
    return s, reasons, debug


def run_scoring(df: pd.DataFrame) -> dict:
    """df: full history with indicators. Returns dict with breakouts/exhaustion DataFrames."""
    latest_date = df["date"].max()
    latest = df[df["date"] == latest_date].set_index("ticker")
    survivors = universe_filter(latest)

    breakouts = []
    exhaustions = []

    for ticker, row in survivors.iterrows():
        hist = df[df["ticker"] == ticker].sort_values("date")
        if len(hist) < UNIVERSE["min_history_days"]:
            continue
        bs, br, bd = score_breakout(row, hist)
        es, er, ed = score_exhaustion(row, hist)
        tier = liquidity_tier(row["adtv20"])
        # tomorrow-liquidity guardrail: realistic max position = 5% of ADTV
        max_pos = row["adtv20"] * 0.05

        weights = SCORE_WEIGHTS[tier]
        b_wscore = _weighted_score(bd["cats"], _BREAKOUT_TOTALS, weights)
        e_wscore = _weighted_score(ed["cats"], _EXHAUST_TOTALS, weights)

        common = {
            "ticker": ticker,
            "name": row["name"],
            "close": row["close"],
            "change_pct": (row["close"] / row["prev_close"] - 1) * 100 if row["prev_close"] else 0,
            "adtv20_b": row["adtv20"] / 1e9,
            "tier": tier,
            "vol_mult": bd["vol_mult"],
            "rsi14": bd["rsi14"],
            "fnet_today_b": ed["fnet_today_b"],
            "fnet_5d_b": bd["fnet_5d_b"],
            "max_pos_idr_m": max_pos / 1e6,
            "arb_streak": int(row.get("arb_streak", 0)),
            "close_pos": ed["close_pos"],
        }

        breakouts.append({**common, "score": bs, "wscore": round(b_wscore, 1),
                          "passed": bs >= BREAKOUT["min_score"],
                          "reasons": "; ".join(br) or "(no signals)", **bd})
        exhaustions.append({**common, "score": es, "wscore": round(e_wscore, 1),
                            "passed": es >= EXHAUSTION["min_score"],
                            "reasons": "; ".join(er) or "(no signals)", **ed})

    bdf = pd.DataFrame(breakouts).sort_values("wscore", ascending=False) if breakouts else pd.DataFrame()
    edf = pd.DataFrame(exhaustions).sort_values("wscore", ascending=False) if exhaustions else pd.DataFrame()
    return {"date": latest_date, "breakouts": bdf, "exhaustion": edf,
            "universe_size": len(survivors),
            "n_breakouts_passed": int(bdf["passed"].sum()) if not bdf.empty else 0,
            "n_exhaustion_passed": int(edf["passed"].sum()) if not edf.empty else 0}
