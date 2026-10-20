"""Flipped SNR — смена роли уровня по правилам Malaysian SNR.

Уровень строится от CLOSE первой свечи к OPEN второй (фитили игнорируются):
  * бычья -> медвежья: уровень = close бычьей  (сопротивление, формация «A»);
  * медвежья -> бычья: уровень = close медвежьей (поддержка, формация «V»).

Пробой **телом** даёт «свежий» (fresh) уровень — сигнал на смену роли (SBR/RBS).
Пробой только фитилём считается «unfresh» и по методичке слабее — его можно отфильтровать.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def flip_signals(
    df: pd.DataFrame,
    lookback: int = 60,
    buffer_atr: float = 0.10,
    stop_atr: float = 1.0,
    rr: float = 2.0,
    body_only: bool = True,
    max_level_age: int = 240,
    dedupe_atr: float = 0.3,
) -> pd.DataFrame:
    n = len(df)
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)

    levels: list[dict] = []
    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    stop_price = np.full(n, np.nan)
    tp_price = np.full(n, np.nan)
    reason = np.empty(n, dtype=object)
    reason[:] = ""

    for i in range(1, n):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        # 1) новый уровень из пары свечей (close -> open)
        green_prev = c[i - 1] > o[i - 1]
        red_prev = c[i - 1] < o[i - 1]
        green_now = c[i] > o[i]
        red_now = c[i] < o[i]
        if (green_prev and red_now) or (red_prev and green_now):
            price = c[i - 1]
            kind = "resistance" if (green_prev and red_now) else "support"
            near = [lv for lv in levels if abs(lv["price"] - price) < dedupe_atr * a]
            if not near:
                levels.append({"price": price, "kind": kind, "born": i, "broken": False})

        # 2) проверка пробоя телом / фитилём (на баре рождения проверок нет)
        for lv in levels:
            if lv["broken"] or i <= lv["born"]:
                continue
            if i - lv["born"] > max_level_age:
                lv["broken"] = True
                continue
            price = lv["price"]
            if lv["kind"] == "resistance":
                body_break = c[i] > price + buffer_atr * a and c[i - 1] <= price
                wick_touch = h[i] > price and c[i] <= price
                side = "long"
            else:
                body_break = c[i] < price - buffer_atr * a and c[i - 1] >= price
                wick_touch = l[i] < price and c[i] >= price
                side = "short"

            if body_break:
                lv["broken"] = True
                stop = price - stop_atr * a if side == "long" else price + stop_atr * a
                risk = abs(c[i] - stop)
                if risk > 0:
                    if side == "long":
                        long_sig[i] = True
                    else:
                        short_sig[i] = True
                    stop_price[i] = stop
                    tp_price[i] = c[i] + rr * risk if side == "long" else c[i] - rr * risk
                    tag = "fresh" if not lv.get("unfresh") else "unfresh-фитиль раньше"
                    reason[i] = (
                        f"пробой телом уровня {price:.2f} "
                        f"({'сопротивление' if lv['kind'] == 'resistance' else 'поддержка'}) — flip, {tag}"
                    )
                break
            if wick_touch and not lv.get("unfresh"):
                lv["unfresh"] = True  # уровень «засвечен» фитилём — считаем unfresh

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["stop_atr"] = stop_atr
    out["rr"] = rr
    out["stop_price"] = stop_price
    out["tp_price"] = tp_price
    out["reason"] = reason
    return out
