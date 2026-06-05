"""DB backup/restore as gzipped CSV — for Google Drive persistence between routine runs."""
import argparse
import gzip
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd

from config import DB_PATH

GDRIVE_FILENAME = "idx_scanner_backup.csv.gz"
BACKUP_DAYS = 60   # keep this many days in the backup (enough for EMA50)


def export_csv_gz(dest: str = "/tmp/idx_backup.csv.gz", days: int = BACKUP_DAYS) -> str:
    """Export last N days of OHLCV to a gzipped CSV file."""
    from db import load_history
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    df = load_history(min_date=cutoff)
    data = gzip.compress(df.to_csv(index=False).encode("utf-8"), compresslevel=9)
    Path(dest).write_bytes(data)
    kb = len(data) / 1024
    print(f"Exported {len(df):,} rows ({df['date'].min()} → {df['date'].max()}) → {kb:.0f} KB")
    return dest


def import_csv_gz(src: str = "/tmp/idx_backup.csv.gz") -> None:
    """Restore OHLCV from a gzipped CSV, upserting into the local DB."""
    from db import init_db, upsert_rows
    data = Path(src).read_bytes()
    csv  = gzip.decompress(data).decode("utf-8")
    df   = pd.read_csv(StringIO(csv))
    init_db()
    rows = df.to_dict("records")
    upsert_rows(rows)
    print(f"Restored: {len(rows):,} rows  ({df['date'].min()} → {df['date'].max()})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["export", "import"])
    ap.add_argument("--path", default="/tmp/idx_backup.csv.gz")
    ap.add_argument("--days", type=int, default=BACKUP_DAYS)
    args = ap.parse_args()
    if args.action == "export":
        export_csv_gz(args.path, args.days)
    else:
        import_csv_gz(args.path)
