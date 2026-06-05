#!/usr/bin/env bash
# Installs a cron job to run the IDX scanner nightly.
# Default schedule: Mon–Fri at 11:30 UTC = 18:30 WIB (adjust HOUR/MIN if needed).
set -euo pipefail

HOUR=${HOUR:-11}
MIN=${MIN:-30}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON=$(command -v python3)
LOG="/tmp/idx_scanner_cron.log"

CRON_CMD="$MIN $HOUR * * 1-5 cd \"$SCRIPT_DIR\" && $PYTHON run_nightly.py --days-back 5 >> \"$LOG\" 2>&1"

# Ensure cron daemon is running
service cron start 2>/dev/null || true

# Replace any existing entry for this script, then append the new one
( crontab -l 2>/dev/null | grep -v "run_nightly.py" ; echo "$CRON_CMD" ) | crontab -

echo "Installed cron job:"
crontab -l | grep "run_nightly"
echo ""
echo "Schedule : Mon–Fri ${HOUR}:$(printf '%02d' $MIN) UTC  (18:30 WIB at default)"
echo "Log file : $LOG"
echo ""
echo "To change time:  HOUR=12 MIN=00 bash setup_cron.sh"
echo "To remove:       crontab -l | grep -v run_nightly.py | crontab -"
echo "To tail logs:    tail -f $LOG"
