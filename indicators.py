"""Индикаторы без внешних зависимостей кроме pandas/numpy."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = wilder(gain, period)
    avg_loss = wilder(loss, period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return wilder(true_range(df), period)


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)

    atr_ = wilder(true_range(df), period).replace(0, np.nan)
    plus_di = 100 * wilder(plus_dm, period) / atr_
    minus_di = 100 * wilder(minus_dm, period) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame(
        {"plus_di": plus_di, "minus_di": minus_di, "adx": wilder(dx.fillna(0), period)}
    )


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def donchian(df: pd.DataFrame, period: int) -> pd.DataFrame:
    """Канал по предыдущим `period` барам (без текущего)."""
    upper = df["high"].rolling(period).max().shift(1)
    lower = df["low"].rolling(period).min().shift(1)
    return pd.DataFrame({"upper": upper, "lower": lower})


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Стандартный набор колонок для стратегий."""
    out = df.copy()
    close = out["close"]
    out["ema50"] = ema(close, 50)
    out["ema200"] = ema(close, 200)
    out["rsi"] = rsi(close, 14)
    out["atr"] = atr(out, 14)
    out["atr_pct"] = out["atr"] / close * 100
    out["atr_median"] = out["atr"].rolling(200).median()
    a = adx(out, 14)
    out["adx"] = a["adx"]
    out["plus_di"] = a["plus_di"]
    out["minus_di"] = a["minus_di"]
    m = macd(close)
    out["macd"] = m["macd"]
    out["macd_signal"] = m["signal"]
    out["macd_hist"] = m["hist"]
    d = donchian(out, 24)
    out["don_hi"] = d["upper"]
    out["don_lo"] = d["lower"]
    out["hour"] = out.index.hour
    out["dow"] = out.index.dayofweek
    return out
