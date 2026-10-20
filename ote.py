"""OTE-вход (0.618–0.79) после слома структуры — механика из канала MW.

Логика ICT/SMC: после подтверждённого слома структуры (закрытие за свингом)
ждём откат в зону OTE (61.8–79 % импульса), входим при возврате закрытием,
стоп за началом импульса, цель 2R.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _swings(df: pd.DataFrame, strength: int = 3) -> tuple[np.ndarray, np.ndarray]:
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    n = len(df)
    sh = np.zeros(n, bool)
    sl = np.zeros(n, bool)
    for i in range(strength, n - strength):
        win_h = h[i - strength: i + strength + 1]
        win_l = l[i - strength: i + strength + 1]
        if h[i] == win_h.max() and (win_h == h[i]).sum() == 1:
            sh[i] = True
        if l[i] == win_l.min() and (win_l == l[i]).sum() == 1:
            sl[i] = True
    return sh, sl


def ote_signals(
    df: pd.DataFrame,
    strength: int = 3,
    ote_low: float = 0.618,
    ote_high: float = 0.79,
    stop_buffer_atr: float = 0.3,
    rr: float = 2.0,
    wait: int = 24,
) -> pd.DataFrame:
    n = len(df)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)

    sh, sl = _swings(df, strength)

    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    stop_price = np.full(n, np.nan)
    tp_price = np.full(n, np.nan)
    reason = np.empty(n, dtype=object)
    reason[:] = ""

    last_high = np.nan
    last_low = np.nan
    pending: list[dict] = []

    for i in range(strength + 1, n):
        if sh[i - 1]:
            last_high = h[i - 1]
        if sl[i - 1]:
            last_low = l[i - 1]

        # слом вверх: закрытие выше последнего свинг-хая
        if np.isfinite(last_high) and c[i] > last_high and c[i - 1] <= last_high and np.isfinite(last_low):
            leg = c[i] - last_low
            if leg > 0:
                pending.append({
                    "side": "long", "bar": i,
                    "zone_top": last_low + ote_low * leg,
                    "zone_bottom": last_low + ote_high * leg,
                    "leg_start": last_low,
                })
        if np.isfinite(last_low) and c[i] < last_low and c[i - 1] >= last_low and np.isfinite(last_high):
            leg = last_high - c[i]
            if leg > 0:
                pending.append({
                    "side": "short", "bar": i,
                    "zone_top": last_high - ote_low * leg,
                    "zone_bottom": last_high - ote_high * leg,
                    "leg_start": last_high,
                })

        pending = [p for p in pending if i - p["bar"] <= wait]
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        for p in list(pending):
            if p["side"] == "long":
                touched = l[i] <= p["zone_top"]
                held = c[i] > p["zone_top"]
                if touched and held:
                    stop = p["leg_start"] - stop_buffer_atr * a
                    risk = c[i] - stop
                    if risk > 0:
                        long_sig[i] = True
                        stop_price[i] = stop
                        tp_price[i] = c[i] + rr * risk
                        reason[i] = f"OTE-откат {ote_low:.2f}–{ote_high:.2f} после слома вверх"
                    pending.remove(p)
                    break
            else:
                touched = h[i] >= p["zone_bottom"]
                held = c[i] < p["zone_bottom"]
                if touched and held:
                    stop = p["leg_start"] + stop_buffer_atr * a
                    risk = stop - c[i]
                    if risk > 0:
                        short_sig[i] = True
                        stop_price[i] = stop
                        tp_price[i] = c[i] - rr * risk
                        reason[i] = f"OTE-откат {ote_low:.2f}–{ote_high:.2f} после слома вниз"
                    pending.remove(p)
                    break

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["stop_atr"] = 1.0
    out["rr"] = rr
    out["stop_price"] = stop_price
    out["tp_price"] = tp_price
    out["reason"] = reason
    return out
