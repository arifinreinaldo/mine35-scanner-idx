"""Generate the nightly markdown report."""
from datetime import datetime
from pathlib import Path

import pandas as pd

from brief import generate_briefs
from config import REPORTS_DIR, WATCHLISTS


def _fmt_df(df: pd.DataFrame, top: int = 15) -> str:
    if df.empty:
        return "_(no candidates)_\n"
    show = df.head(top).copy()
    show["mark"] = show["passed"].map(lambda x: "★" if x else " ")
    show["close"] = show["close"].map(lambda x: f"{x:,.0f}")
    show["change_pct"] = show["change_pct"].map(lambda x: f"{x:+.1f}%")
    show["adtv20_b"] = show["adtv20_b"].map(lambda x: f"{x:,.1f}b")
    show["vol_mult"] = show["vol_mult"].map(lambda x: f"{x:.1f}x")
    show["fnet_today_b"] = show["fnet_today_b"].map(lambda x: f"{x:+.2f}b")
    show["max_pos_idr_m"] = show["max_pos_idr_m"].map(lambda x: f"{x:,.0f}m")
    show["rsi14"] = show["rsi14"].map(lambda x: f"{x:.0f}")
    cols = ["mark", "ticker", "tier", "close", "change_pct", "vol_mult", "rsi14",
            "fnet_today_b", "adtv20_b", "max_pos_idr_m", "wscore", "reasons"]
    return show[cols].to_markdown(index=False) + "\n"


def build(result: dict, bt: dict | None = None, df: pd.DataFrame | None = None) -> str:
    d = result["date"]
    n_uni = result["universe_size"]
    nb = result["n_breakouts_passed"]
    ne = result["n_exhaustion_passed"]

    briefs: dict[str, str] = generate_briefs(result, df) if df is not None else {}

    parts = [
        f"# IDX Nightly Scan — {d}",
        f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z",
        "",
        f"- Universe size after liquidity filter: **{n_uni}**",
        f"- Breakouts crossing threshold (★): **{nb}**",
        f"- Exhaustion crossing threshold (★): **{ne}**",
        "",
        "## Breakout watchlist — top 15 by score (★ = passed threshold)",
        _fmt_df(result["breakouts"], top=15),
    ]
    b_notes = _build_notes(result["breakouts"], briefs, "b_")
    if b_notes:
        parts += ["", b_notes]
    parts += [
        "",
        "## Exhaustion watchlist — top 15 by score (★ = passed threshold)",
        _fmt_df(result["exhaustion"], top=15),
    ]
    e_notes = _build_notes(result["exhaustion"], briefs, "e_")
    if e_notes:
        parts += ["", e_notes]
    parts += [
        "",
        "### Column legend",
        "- `tier` = liquidity tier (mega/large/mid/small) — drives scoring weights",
        "- `vol_mult` = today's volume / 20-day average volume",
        "- `fnet_today_b` = foreign net buy today, IDR billions (+/-)",
        "- `adtv20_b` = 20-day average daily value traded, IDR billions",
        "- `max_pos_idr_m` = realistic max position size = 5% of ADTV (slippage guardrail)",
        "- `wscore` = tier-weighted signal score (price/foreign/context weighted by liquidity tier)",
        "",
        "_Not investment advice. Always confirm with order book at pre-open._",
    ]
    if WATCHLISTS:
        parts.append("")
        parts.append(_build_watchlists(result))
    if bt:
        parts.append("")
        parts.append(_build_backtest(bt))
    return "\n".join(parts)


def _build_notes(df: pd.DataFrame, briefs: dict, prefix: str) -> str:
    """Render per-ticker brief notes for stocks that have one."""
    if df.empty:
        return ""
    lines = ["### Notes"]
    found = False
    for _, row in df.head(15).iterrows():
        key = f"{prefix}{row['ticker']}"
        if key not in briefs:
            continue
        name = row.get("name", "")
        name_str = f" ({name})" if name and str(name) != "nan" else ""
        tier = row.get("tier", "")
        mark = "★ " if row.get("passed") else ""
        lines.append(f"\n**{mark}{row['ticker']}**{name_str} [{tier}]  \n{briefs[key]}")
        found = True
    return "\n".join(lines) if found else ""


def _build_watchlists(result: dict) -> str:
    bdf = result["breakouts"]
    edf = result["exhaustion"]
    lines = ["---", "## Watchlists"]

    for group, tickers in WATCHLISTS.items():
        label = group.replace("_", " ").title()
        lines += ["", f"### {label}"]
        rows = []
        for t in tickers:
            br = bdf[bdf["ticker"] == t]
            er = edf[edf["ticker"] == t]
            if br.empty and er.empty:
                rows.append({"ticker": t, "close": "-", "chg%": "-", "tier": "-",
                             "breakout": "-", "exhaustion": "-", "signals": "below liquidity filter"})
                continue
            ref = br.iloc[0] if not br.empty else er.iloc[0]
            b_ws = f"{'★' if not br.empty and br.iloc[0]['passed'] else ''}{br.iloc[0]['wscore']:.1f}" if not br.empty else "-"
            e_ws = f"{'★' if not er.empty and er.iloc[0]['passed'] else ''}{er.iloc[0]['wscore']:.1f}" if not er.empty else "-"
            # dominant signal: whichever scored higher
            if not br.empty and not er.empty:
                sig = br.iloc[0]["reasons"] if br.iloc[0]["wscore"] >= er.iloc[0]["wscore"] else er.iloc[0]["reasons"]
            elif not br.empty:
                sig = br.iloc[0]["reasons"]
            else:
                sig = er.iloc[0]["reasons"]
            rows.append({
                "ticker": t,
                "close": f"{ref['close']:,.0f}",
                "chg%": f"{ref['change_pct']:+.1f}%",
                "tier": ref["tier"],
                "breakout": b_ws,
                "exhaustion": e_ws,
                "signals": sig[:80],
            })
        lines.append(pd.DataFrame(rows).to_markdown(index=False))
    return "\n".join(lines)


def _build_backtest(bt: dict) -> str:
    ref = bt["ref_date"]
    today = bt["today"]
    b_eval = bt["breakout_eval"]
    e_eval = bt["exhaustion_eval"]

    lines = [
        f"---",
        f"## Signal Backtest — signals from {ref}, evaluated at {today}",
        "",
    ]

    def _bt_table(df: pd.DataFrame, label: str, hit_label: str) -> list[str]:
        if df.empty:
            return [f"**{label}:** _(no signals passed threshold on {ref})_", ""]
        total = len(df)
        hits = df["hit"].sum()
        rate = hits / total * 100 if total else 0
        out = [f"**{label}:** {hits}/{total} hit ({rate:.0f}%) — {hit_label}", ""]
        show = df.copy()
        show["entry"] = show["entry"].map(lambda x: f"{x:,.0f}")
        show["current"] = show["current"].map(lambda x: f"{x:,.0f}")
        show["ret_pct"] = show["ret_pct"].map(lambda x: f"{x:+.1f}%")
        show["result"] = show["hit"].map(lambda x: "✓" if x else "✗")
        cols = ["result", "ticker", "entry", "current", "ret_pct", "wscore", "reasons"]
        out.append(show[cols].to_markdown(index=False))
        out.append("")
        return out

    lines += _bt_table(b_eval, "Breakout signals", "closed ≥+2% since signal")
    lines += _bt_table(e_eval, "Exhaustion signals", "closed ≤-2% since signal")
    return "\n".join(lines)


def save(text: str, date: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    p = REPORTS_DIR / f"scan_{date}.md"
    p.write_text(text)
    return p
