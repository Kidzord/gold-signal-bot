"""Сетап от имбаланса (FVG) — механика из разбора видео.

Bias по системе = взаимодействие цены с ключевым уровнем (имбаланс/FVG) и
подтверждённая реакция. Механически это: формируется имбаланс (разрыв между
свечой i-2 и свечой i), цена возвращается в зону, даёт реакцию — вход в сторону
импульса, стоп за зоной, цель 2R (или следующий имбаланс).

Режимы входа:
  * "touch"   — лимит внутри зоны (агрессивно, как в видео при хорошем RR);
  * "confirm" — ждём закрытия свечи обратно за границей зоны (консервативно).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def find_fvgs(df: pd.DataFrame, min_gap_atr: float = 0.15, max_age: int = 120) -> list[dict]:
    """Имбалансы: разрыв между high[i-2] и low[i] (бычий) или наоборот (медвежий)."""
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    atr = df["atr"].to_numpy(float)
    out = []
    for i in range(2, len(df)):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        if l[i] - h[i - 2] > min_gap_atr * a:
            out.append({"side": "bull", "top": l[i], "bottom": h[i - 2], "born": i, "dead": None})
        elif l[i - 2] - h[i] > min_gap_atr * a:
            out.append({"side": "bear", "top": l[i - 2], "bottom": h[i], "born": i, "dead": None})
    return out


def fvg_signals(
    df: pd.DataFrame,
    mode: str = "confirm",
    min_gap_atr: float = 0.15,
    entry_depth: float = 0.5,
    stop_buffer_atr: float = 0.25,
    rr: float = 2.0,
    max_age: int = 120,
    max_fill_bars: int = 60,
) -> pd.DataFrame:
    n = len(df)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)

    fvgs = find_fvgs(df, min_gap_atr=min_gap_atr, max_age=max_age)

    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    stop_price = np.full(n, np.nan)
    tp_price = np.full(n, np.nan)
    reason = np.empty(n, dtype=object)
    reason[:] = ""

    used: set[int] = set()

    for k, z in enumerate(fvgs):
        top, bottom = z["top"], z["bottom"]
        height = top - bottom
        if height <= 0:
            continue
        # уровень входа внутри зоны
        if z["side"] == "bull":
            entry_level = top - height * entry_depth
        else:
            entry_level = bottom + height * entry_depth

        for i in range(z["born"] + 1, min(z["born"] + max_fill_bars, n)):
            a = atr[i]
            if not np.isfinite(a) or a <= 0:
                continue

            if z["side"] == "bull":
                # инвалидация: закрытие ниже зоны
                if c[i] < bottom - stop_buffer_atr * a:
                    z["dead"] = i
                    break
                if mode == "touch":
                    hit = l[i] <= entry_level
                else:
                    hit = l[i] <= top and c[i] > top
                if hit:
                    stop = bottom - stop_buffer_atr * a
                    risk = c[i] - stop
                    if risk > 0:
                        long_sig[i] = True
                        stop_price[i] = stop
                        tp_price[i] = c[i] + rr * risk
                        reason[i] = f"возврат в бычий имбаланс {bottom:.2f}–{top:.2f}, реакция"
                        used.add(k)
                    break
            else:
                if c[i] > top + stop_buffer_atr * a:
                    z["dead"] = i
                    break
                if mode == "touch":
                    hit = h[i] >= entry_level
                else:
                    hit = h[i] >= bottom and c[i] < bottom
                if hit:
                    stop = top + stop_buffer_atr * a
                    risk = stop - c[i]
                    if risk > 0:
                        short_sig[i] = True
                        stop_price[i] = stop
                        tp_price[i] = c[i] - rr * risk
                        reason[i] = f"возврат в медвежий имбаланс {bottom:.2f}–{top:.2f}, реакция"
                        used.add(k)
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
