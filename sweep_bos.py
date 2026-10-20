"""«Закол + BOS» — свип ликвидности и слом структуры (приём из канала MW).

Сценарий шорта:
  1. цена фитилём прокалывает последний свинг-хай, но закрывается НИЖЕ него (закол);
  2. затем закрытие ниже последнего свинг-лоя (BOS);
  3. вход в шорт, стоп за максимум закола, цель 2R.

Сценарий лонга — зеркально (свип под свинг-лоем, затем пробой свинг-хая вверх).
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


def sweep_bos_signals(
    df: pd.DataFrame,
    strength: int = 3,
    sweep_window: int = 12,
    stop_buffer_atr: float = 0.2,
    rr: float = 2.0,
    require_sweep: bool = True,
    cooldown: int = 5,
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
    sweep_high: float | None = None   # закол сверху (для шорта)
    sweep_low: float | None = None    # закол снизу (для лонга)
    sweep_high_bar = sweep_low_bar = -10**6
    last_signal = -10**6

    for i in range(strength + 1, n):
        if sh[i - 1]:
            last_high = h[i - 1]
        if sl[i - 1]:
            last_low = l[i - 1]

        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        # 1) фиксируем заколы
        if np.isfinite(last_high) and h[i] > last_high and c[i] < last_high:
            sweep_high = h[i]
            sweep_high_bar = i
        if np.isfinite(last_low) and l[i] < last_low and c[i] > last_low:
            sweep_low = l[i]
            sweep_low_bar = i

        # закол «протухает»
        if i - sweep_high_bar > sweep_window:
            sweep_high = None
        if i - sweep_low_bar > sweep_window:
            sweep_low = None

        if i - last_signal < cooldown:
            continue

        # 2) BOS после закола
        if np.isfinite(last_low) and c[i] < last_low and c[i - 1] >= last_low:
            if require_sweep and sweep_high is None:
                pass
            else:
                stop = (sweep_high if (require_sweep and sweep_high) else h[i]) + stop_buffer_atr * a
                risk = stop - c[i]
                if risk > 0:
                    short_sig[i] = True
                    stop_price[i] = stop
                    tp_price[i] = c[i] - rr * risk
                    reason[i] = "закол сверху + слом структуры вниз"
                    last_signal = i
                    sweep_high = None
                    continue

        if np.isfinite(last_high) and c[i] > last_high and c[i - 1] <= last_high:
            if require_sweep and sweep_low is None:
                pass
            else:
                stop = (sweep_low if (require_sweep and sweep_low) else l[i]) - stop_buffer_atr * a
                risk = c[i] - stop
                if risk > 0:
                    long_sig[i] = True
                    stop_price[i] = stop
                    tp_price[i] = c[i] + rr * risk
                    reason[i] = "закол снизу + слом структуры вверх"
                    last_signal = i
                    sweep_low = None

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["stop_atr"] = 1.0
    out["rr"] = rr
    out["stop_price"] = stop_price
    out["tp_price"] = tp_price
    out["reason"] = reason
    return out
