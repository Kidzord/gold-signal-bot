"""Сетап «Азиатский диапазон» из методички Malaysian SNR.

Логика: диапазон азиатской сессии (по умолчанию 00:00–07:00 UTC) служит зоной.
В окне Лондона/Нью-Йорка вход на закрытии за границей диапазона, стоп за
противоположной границей (или ATR), цель — 2R. Один вход в день.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def asian_range_signals(
    df: pd.DataFrame,
    start: int = 0,
    end: int = 7,
    entry_from: int = 7,
    entry_to: int = 16,
    buffer_atr: float = 0.15,
    stop_mode: str = "range",
    stop_atr: float = 1.5,
    rr: float = 2.0,
    both_sides: bool = True,
) -> pd.DataFrame:
    n = len(df)
    idx = df.index
    hours = idx.hour.to_numpy()
    days = idx.date

    close = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)

    session_mask = (hours >= start) & (hours < end)
    session = df[session_mask]
    if session.empty:
        return _empty(df)

    daily = session.groupby(session.index.date).agg(hi=("high", "max"), lo=("low", "min"))
    hi_map = daily["hi"].to_dict()
    lo_map = daily["lo"].to_dict()

    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    stop_price = np.full(n, np.nan)
    tp_price = np.full(n, np.nan)
    reason = np.empty(n, dtype=object)
    reason[:] = ""

    used_long: set = set()
    used_short: set = set()

    for i in range(n):
        h = hours[i]
        if not (entry_from <= h < entry_to):
            continue
        day = days[i]
        rng_hi = hi_map.get(day)
        rng_lo = lo_map.get(day)
        if rng_hi is None or rng_lo is None:
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        if close[i] > rng_hi + buffer_atr * a and day not in used_long:
            long_sig[i] = True
            used_long.add(day)
            stop = (rng_lo - buffer_atr * a) if stop_mode == "range" else (close[i] - stop_atr * a)
            risk = close[i] - stop
            if risk > 0:
                stop_price[i] = stop
                tp_price[i] = close[i] + rr * risk
                reason[i] = f"пробой азиатского максимума {rng_hi:.2f} в окне Лондона/НЙ"
            else:
                long_sig[i] = False

        elif both_sides and close[i] < rng_lo - buffer_atr * a and day not in used_short:
            short_sig[i] = True
            used_short.add(day)
            stop = (rng_hi + buffer_atr * a) if stop_mode == "range" else (close[i] + stop_atr * a)
            risk = stop - close[i]
            if risk > 0:
                stop_price[i] = stop
                tp_price[i] = close[i] - rr * risk
                reason[i] = f"пробой азиатского минимума {rng_lo:.2f} в окне Лондона/НЙ"
            else:
                short_sig[i] = False

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["stop_atr"] = stop_atr
    out["rr"] = rr
    out["stop_price"] = stop_price
    out["tp_price"] = tp_price
    out["reason"] = reason
    return out


def _empty(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["long_signal"] = False
    out["short_signal"] = False
    out["stop_atr"] = 1.5
    out["rr"] = 2.0
    out["stop_price"] = np.nan
    out["tp_price"] = np.nan
    out["reason"] = ""
    return out
