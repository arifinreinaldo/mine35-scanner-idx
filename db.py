"""SQLite schema + helpers."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import pandas as pd

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    date           TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    name           TEXT,
    prev_close     REAL,
    open           REAL,
    high           REAL,
    low            REAL,
    close          REAL,
    change         REAL,
    volume         REAL,
    value          REAL,
    frequency      REAL,
    bid            REAL,
    bid_volume     REAL,
    offer          REAL,
    offer_volume   REAL,
    listed_shares  REAL,
    tradeable_shares REAL,
    foreign_buy    REAL,
    foreign_sell   REAL,
    foreign_net    REAL,
    index_weight   REAL,
    remarks        TEXT,
    PRIMARY KEY (date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv(ticker, date);
CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv(date);

CREATE TABLE IF NOT EXISTS fetch_log (
    date       TEXT PRIMARY KEY,
    records    INTEGER,
    fetched_at TEXT
);
"""


@contextmanager
def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)


def upsert_rows(rows: Iterable[dict]):
    rows = list(rows)
    if not rows:
        return 0
    cols = [
        "date", "ticker", "name", "prev_close", "open", "high", "low", "close",
        "change", "volume", "value", "frequency", "bid", "bid_volume", "offer",
        "offer_volume", "listed_shares", "tradeable_shares", "foreign_buy",
        "foreign_sell", "foreign_net", "index_weight", "remarks",
    ]
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT OR REPLACE INTO ohlcv ({','.join(cols)}) VALUES ({placeholders})"
    with connect() as con:
        con.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    return len(rows)


def log_fetch(date: str, records: int):
    from datetime import datetime
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO fetch_log (date, records, fetched_at) VALUES (?, ?, ?)",
            (date, records, datetime.utcnow().isoformat()),
        )


def fetched_dates() -> set[str]:
    with connect() as con:
        cur = con.execute("SELECT date FROM fetch_log WHERE records > 0")
        return {row[0] for row in cur.fetchall()}


def load_history(min_date: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM ohlcv"
    params: tuple = ()
    if min_date:
        sql += " WHERE date >= ?"
        params = (min_date,)
    sql += " ORDER BY ticker, date"
    with connect() as con:
        return pd.read_sql_query(sql, con, params=params)


def latest_date_in_db() -> str | None:
    with connect() as con:
        cur = con.execute("SELECT MAX(date) FROM ohlcv")
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def trim_old_data(keep_days: int = 100) -> int:
    """Delete rows older than keep_days. Returns number of rows deleted."""
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    with connect() as con:
        cur = con.execute("DELETE FROM ohlcv WHERE date < ?", (cutoff,))
        rows = cur.rowcount
        con.execute("DELETE FROM fetch_log WHERE date < ?", (cutoff,))
    return rows
