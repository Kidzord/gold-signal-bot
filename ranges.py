"""Диапазонная торговля — идея из канала Fx_wad1m: «ЛП от границы диапазона».

Логика: находим консолидацию (ширина N баров в пределах min..max ATR, ADX низкий),
покупаем у нижней границы при отбое, продаём у верхней. Цель — противоположная граница
или выход за неё на ширину диапазона, стоп — за границей диапазона.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def range_signals(
    df: pd.DataFrame,
    n: int = 48,
    adx_max: float = 22.0,
    min_width_atr: float = 2.0,
    max_width_atr: float = 8.0,
    touch: float = 0.15,
    stop_atr: float = 0.7,
    target: str = "edge",
    rr: float = 2.0,
    trend_filter: bool = False,
) -> pd.DataFrame:
    """Сигналы от границ диапазона.

    target: "edge" — противоположная граница; "ext" — граница + ширина диапазона;
            "rr" — обычный стоп/тейк в R.
    """
    hi = df["high"].rolling(n).max().shift(1)
    lo = df["low"].rolling(n).min().shift(1)
    width = hi - lo
    atr = df["atr"]
    close, high, low = df["close"], df["high"], df["low"]

    valid = (
        (width >= min_width_atr * atr)
        & (width <= max_width_atr * atr)
        & (df["adx"] < adx_max)
        & width.notna()
    )

    long_touch = (low <= lo + touch * atr) & (close > lo) & (close < hi)
    short_touch = (high >= hi - touch * atr) & (close < hi) & (close > lo)

    if trend_filter:
        up = (close > df["ema200"]) & (df["ema50"] > df["ema200"])
        dn = (close < df["ema200"]) & (df["ema50"] < df["ema200"])
        long_touch &= up
        short_touch &= dn

    long_sig = valid & long_touch
    short_sig = valid & short_touch

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = long_sig.fillna(False)
    out["short_signal"] = short_sig.fillna(False)

    stop_price = np.where(long_sig, lo - stop_atr * atr, np.where(short_sig, hi + stop_atr * atr, np.nan))
    if target == "edge":
        tp_price = np.where(long_sig, hi, np.where(short_sig, lo, np.nan))
    elif target == "ext":
        tp_price = np.where(long_sig, hi + width, np.where(short_sig, lo - width, np.nan))
    elif target == "mid":
        tp_price = np.where(long_sig, lo + width * 0.5, np.where(short_sig, hi - width * 0.5, np.nan))
    else:
        tp_price = np.full(len(df), np.nan)

    out["stop_atr"] = 1.5
    out["rr"] = rr
    out["stop_price"] = stop_price
    out["tp_price"] = tp_price
    out["reason"] = ""
    out.loc[out["long_signal"], "reason"] = "отбой от нижней границы диапазона (ЛП)"
    out.loc[out["short_signal"], "reason"] = "отбой от верхней границы диапазона (ЛП)"
    return out
