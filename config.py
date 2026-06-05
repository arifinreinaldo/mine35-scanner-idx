"""Configuration: paths, thresholds, ARA rules."""
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "idx.db"
REPORTS_DIR = ROOT / "reports"

IDX_STOCK_SUMMARY_URL = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary"
HTTP_IMPERSONATE = "chrome"
HTTP_TIMEOUT = 30
SLEEP_BETWEEN_DAYS = 0.5

BACKFILL_DAYS = 90

NTFY_URL = ""  # e.g. "https://ntfy.sh/your-topic-name"

UNIVERSE = {
    "min_adtv_idr": 5_000_000_000,
    "min_price": 50,
    "max_price": 50_000,
    "min_history_days": 25,
}

ARA_TIERS = [
    (200, 0.35),
    (5_000, 0.25),
    (float("inf"), 0.20),
]


def ara_cap_pct(prev_close: float) -> float:
    for ceiling, pct in ARA_TIERS:
        if prev_close < ceiling:
            return pct
    return 0.20


BREAKOUT = {
    "close_in_top_pct_of_range": 0.25,
    "vol_mult_vs_adv20": 2.5,       # raised from 1.8 — only truly exceptional vol (data: raw 1.8x was noise/distribution)
    "vol_must_be_green": True,       # vol_surge only fires when close > open (buying pressure, not sell-off)
    "n_day_breakout_lookback": 10,
    "ara_proximity_pct": 0.03,
    "rsi_min": 55,                   # tightened from 50 — 50-55 zone showed negative lift
    "rsi_max": 72,
    "min_score": 4,                  # lowered from 5 — fewer components now, calibrate threshold
}

EXHAUSTION = {
    "close_in_bottom_pct_of_range": 0.30,
    "rsi_extreme": 80,
    "vol_distribution_lookback": 3,
    "arb_bounce_min_pct": 0.08,      # next-day intraday high must be >= +8% above ARB close to count as "shot high"
    "min_score": 3,
}

TIERS = {
    "mega_adtv": 100_000_000_000,
    "large_adtv": 30_000_000_000,
    "mid_adtv": 10_000_000_000,
}


def liquidity_tier(adtv: float) -> str:
    if adtv >= TIERS["mega_adtv"]:
        return "mega"
    if adtv >= TIERS["large_adtv"]:
        return "large"
    if adtv >= TIERS["mid_adtv"]:
        return "mid"
    return "small"


WATCHLISTS = {
    "prajogo_pangestu": ["BREN", "BRPT", "TPIA", "CUAN", "PTRO"],
}

SCORE_WEIGHTS = {
    "mega":  {"price": 0.45, "foreign": 0.35, "context": 0.20},
    "large": {"price": 0.45, "foreign": 0.30, "context": 0.25},
    "mid":   {"price": 0.50, "foreign": 0.20, "context": 0.30},
    "small": {"price": 0.55, "foreign": 0.05, "context": 0.40},
}
