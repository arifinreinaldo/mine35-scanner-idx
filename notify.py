"""Send ntfy push notification after scan completes."""
import urllib.request
import urllib.error

from config import NTFY_URL


def send_scan_summary(date: str, n_uni: int, nb: int, ne: int) -> None:
    if not NTFY_URL:
        return
    body = f"Universe: {n_uni} | Breakouts ★: {nb} | Exhaustion ★: {ne}"
    try:
        req = urllib.request.Request(
            NTFY_URL,
            data=body.encode(),
            headers={
                "Title": f"IDX Scan {date}",
                "Tags": "chart_with_upwards_trend",
                "Priority": "default",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[notify] {e}")
