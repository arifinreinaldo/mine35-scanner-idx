# IDX Nightly Scanner (v1)

Pulls IDX EOD market data + foreign flow, scores tickers for next-day **breakout** and **exhaustion** setups.

## What it captures
- **OHLCV** + foreign buy/sell for the full IDX market (~960 tickers/day, 1 HTTP call/day)
- **20/50 EMA, RSI(14), MACD, Bollinger width, ATR(14), ADV20, 10-day close-high**
- **ARA proximity** (computed from previous close + tier rules)
- **Liquidity tier** (mega/large/mid/small) → different scoring weights
- **Realistic max position size** = 5% of ADTV (slippage guardrail)

## What it does NOT include yet (v2 work)
- Broker summary (bandarmologi) — IDX has an endpoint for it, drop into `fetch.py`
- Sector indices (11 IDX-IC sectors) — same endpoint pattern, separate table
- Commodity overlay (coal/CPO/nickel) — needs a separate scrape

## Run

```bash
cd /workspace/idx_scanner

# First time: backfill 90 days (~3-5 minutes, polite delay between days)
python3 run_nightly.py --days-back 90

# Each subsequent night (after 18:30 WIB ideally):
python3 run_nightly.py --days-back 5

# Re-score without re-fetching (fast):
python3 run_nightly.py --skip-fetch
```

## Reports

Saved to `reports/scan_YYYY-MM-DD.md`. Also printed to terminal.

## Tunables

All thresholds live in `config.py`:
- Universe filter (price band, ADTV floor, history minimum)
- Breakout signals (8 components, score ≥ 5 to make list)
- Exhaustion signals (7 components, score ≥ 4 to make list)
- ARA cap rules per price tier
- Liquidity tier cutoffs

## Files

| File | Role |
|---|---|
| `config.py` | Thresholds, paths, ARA rules |
| `db.py` | SQLite schema + helpers |
| `fetch.py` | IDX `GetStockSummary` scraper + backfill loop |
| `indicators.py` | EMA/RSI/MACD/BB/ATR/ADV — pure pandas, no external TA lib |
| `score.py` | Breakout + exhaustion scoring with reasons |
| `report.py` | Markdown report builder |
| `run_nightly.py` | Orchestrator |

## Notes

- IDX endpoint requires Cloudflare-aware client; `curl_cffi` with Chrome impersonation works reliably.
- Holidays/weekends return 0 records and are logged once — fetch is idempotent.
- DB at `data/idx.db` (WAL mode, ~30MB after 90 days of full market).
