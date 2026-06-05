"""Fetch IDX TradingSummary for one day, plus backfill loop."""
import time
from datetime import date, datetime, timedelta

from curl_cffi import requests as cr
from rich.console import Console

from config import (
    BACKFILL_DAYS,
    HTTP_IMPERSONATE,
    HTTP_TIMEOUT,
    IDX_STOCK_SUMMARY_URL,
    SLEEP_BETWEEN_DAYS,
)
from db import fetched_dates, init_db, log_fetch, upsert_rows

console = Console()


def _parse_row(r: dict) -> dict:
    d = r.get("Date", "")[:10]
    fb = float(r.get("ForeignBuy") or 0)
    fs = float(r.get("ForeignSell") or 0)
    return {
        "date": d,
        "ticker": r.get("StockCode") or "",
        "name": r.get("StockName") or "",
        "prev_close": r.get("Previous"),
        "open": r.get("OpenPrice"),
        "high": r.get("High"),
        "low": r.get("Low"),
        "close": r.get("Close"),
        "change": r.get("Change"),
        "volume": r.get("Volume"),
        "value": r.get("Value"),
        "frequency": r.get("Frequency"),
        "bid": r.get("Bid"),
        "bid_volume": r.get("BidVolume"),
        "offer": r.get("Offer"),
        "offer_volume": r.get("OfferVolume"),
        "listed_shares": r.get("ListedShares"),
        "tradeable_shares": r.get("TradebleShares"),
        "foreign_buy": fb,
        "foreign_sell": fs,
        "foreign_net": fb - fs,
        "index_weight": r.get("WeightForIndex"),
        "remarks": r.get("Remarks"),
    }


def fetch_day(d: date) -> list[dict]:
    """Return parsed rows for a single trading date. Empty list = holiday/weekend."""
    ds = d.strftime("%Y%m%d")
    url = f"{IDX_STOCK_SUMMARY_URL}?length=9999&start=0&date={ds}"
    r = cr.get(url, impersonate=HTTP_IMPERSONATE, timeout=HTTP_TIMEOUT,
               headers={"Referer": "https://www.idx.co.id/"})
    r.raise_for_status()
    j = r.json()
    data = j.get("data") or []
    return [_parse_row(row) for row in data if row.get("StockCode")]


def backfill(days_back: int = BACKFILL_DAYS) -> dict:
    """Walk back day-by-day, skip what's already in db. Returns stats."""
    init_db()
    have = fetched_dates()
    today = date.today()
    saved = 0
    skipped = 0
    holidays = 0
    queried = 0

    for offset in range(0, days_back + 1):
        d = today - timedelta(days=offset)
        ds = d.strftime("%Y-%m-%d")
        if ds in have:
            skipped += 1
            continue
        # don't waste calls on Sat/Sun
        if d.weekday() >= 5:
            log_fetch(ds, 0)
            holidays += 1
            continue
        try:
            rows = fetch_day(d)
        except Exception as e:
            console.print(f"[red]err {ds}: {e}[/red]")
            time.sleep(2)
            continue
        queried += 1
        if not rows:
            log_fetch(ds, 0)
            holidays += 1
            console.print(f"[dim]{ds}: holiday/closed (0 records)[/dim]")
        else:
            n = upsert_rows(rows)
            log_fetch(ds, n)
            saved += n
            console.print(f"[green]{ds}: {n} rows[/green]")
        time.sleep(SLEEP_BETWEEN_DAYS)

    return {"saved": saved, "skipped_days": skipped, "holiday_days": holidays, "queried": queried}


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else BACKFILL_DAYS
    stats = backfill(n)
    console.print(stats)
