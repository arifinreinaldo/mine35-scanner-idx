"""Indicators computed directly with pandas/numpy. No pandas-ta dependency."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    roll_down = down.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(s, fast) - ema(s, slow)
    sig = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - sig
    return macd_line, sig, hist


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0):
    m = sma(s, n)
    sd = s.rolling(n, min_periods=n).std(ddof=0)
    return m, m + k * sd, m - k * sd, sd / m  # mid, upper, lower, width-ratio


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_indicators(g: pd.DataFrame) -> pd.DataFrame:
    """Given one ticker's full history sorted by date, append indicator columns."""
    g = g.sort_values("date").copy()
    c = g["close"]

    g["ema20"] = ema(c, 20)
    g["ema50"] = ema(c, 50)
    g["rsi14"] = rsi(c, 14)
    macd_line, macd_sig, macd_hist = macd(c)
    g["macd_hist"] = macd_hist
    bb_mid, bb_up, bb_lo, bb_w = bollinger(c, 20)
    g["bb_width"] = bb_w
    g["atr14"] = atr(g, 14)

    g["adv20"] = g["volume"].rolling(20, min_periods=10).mean()
    g["adtv20"] = g["value"].rolling(20, min_periods=10).mean()

    # 10-day breakout: did today's close break above prior-10-day close high?
    g["high_close_10"] = c.shift(1).rolling(10, min_periods=5).max()

    # range close position (0=low, 1=high)
    rng = (g["high"] - g["low"]).replace(0, np.nan)
    g["close_pos"] = (g["close"] - g["low"]) / rng

    # foreign flow rolling
    g["fnet_5d"] = g["foreign_net"].rolling(5, min_periods=3).sum()

    # ARB streak: consecutive days closing near the lower circuit breaker (-13.5% threshold)
    arb_hit = (g["close"] - g["prev_close"]) / g["prev_close"].replace(0, np.nan) <= -0.135
    streak = []
    count = 0
    for hit in arb_hit:
        count = count + 1 if hit else 0
        streak.append(count)
    g["arb_streak"] = streak

    # Yesterday was ARB flag (for post-ARB bounce detection in scoring)
    g["prev_arb"] = arb_hit.shift(1).fillna(False)

    return g
