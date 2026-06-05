# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Nightly automated scanner for Indonesian Stock Exchange (IDX) that pulls end-of-day OHLCV data for ~960 tickers, computes 13 technical indicators, and scores each ticker for next-day **breakout** and **exhaustion** trading setups. Output is a markdown report in `reports/`.

## Running the Scanner

```bash
# First run — backfill 90 days of history (~3–5 min)
python3 run_nightly.py --days-back 90

# Nightly incremental (scheduled after market close ~18:30 WIB)
python3 run_nightly.py --days-back 5

# Re-score from existing DB without any network calls
python3 run_nightly.py --skip-fetch

# Suppress terminal output
python3 run_nightly.py --no-print
```

## Dependencies

No package manifest exists. Install manually:

```bash
pip install --break-system-packages curl_cffi pandas numpy rich
```

- `curl_cffi` — Chrome-impersonating HTTP client to bypass IDX's Cloudflare protection
- `pandas` / `numpy` — All indicator math
- `rich` — Terminal progress output

## Architecture & Data Flow

```
fetch.py (IDX GetStockSummary API)
    → db.py (SQLite upsert, data/idx.db)
    → indicators.py (add_indicators: EMA/RSI/MACD/Bollinger/ATR per ticker)
    → score.py (score_breakout / score_exhaustion)
    → report.py (reports/scan_YYYY-MM-DD.md)
```

`run_nightly.py` is the orchestrator — read it first to understand the full pipeline (it's ~60 lines).

## Key Module Roles

**`config.py`** — Single source of truth for all thresholds. Edit here to tune signal sensitivity.
- `ara_cap_pct(price)` — Dynamic position size limits by price tier (ARA = Automatic Rating Action rule)
- `liquidity_tier(adtv)` — Classifies tickers: mega/large/mid/small
- `BREAKOUT` / `EXHAUSTION` dicts — Component-level thresholds
- `SCORE_WEIGHTS` — Tier-dependent multipliers (e.g., foreign flow matters more for mega-cap)

**`score.py`** — Core logic. Each signal has N components; a minimum number must fire.
- Breakout: 8 components, needs ≥5 (close in top 25% range, uptrend, 10-day breakout, volume surge 1.8×ADV20, RSI 50–70, foreign net+, MACD rising, ARA proximity)
- Exhaustion: 7 components, needs ≥4 (gap-up reversal, distribution, foreign flip, RSI divergence, failed breakout, MACD rollover)
- Universe filtered first by min ADTV, price band, and minimum history rows

**`fetch.py`** — Calls IDX's `GetStockSummary` endpoint once per day. Uses `curl_cffi` with Chrome impersonation (not `requests`) — do not swap this out. Skips weekends, Indonesian public holidays, and dates already in DB.

**`db.py`** — SQLite with WAL mode. Schema: `ohlcv` table (~22 columns) + `fetch_log`. Key function: `load_history(conn, tickers, min_date)` returns a single DataFrame for all tickers.

**`indicators.py`** — Pure pandas/numpy, no external TA library. `add_indicators(g)` takes one ticker's sorted history and appends EMA20, EMA50, RSI14, MACD, Bollinger bands, ATR14, ADV20, and close position columns.

## Data Location

- `data/idx.db` — SQLite database (~12 MB at 90 days of history)
- `reports/scan_YYYY-MM-DD.md` — Output markdown reports

## Important Constraints

- **Never replace `curl_cffi` with `requests` or `httpx`** — Cloudflare blocks standard clients on IDX's API.
- All threshold tuning belongs in `config.py`, not scattered in `score.py`.
- `add_indicators()` must be called on data sorted ascending by date, grouped by ticker.
