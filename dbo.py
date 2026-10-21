"""MSnR Double Breakout Level (RWBTradeLab) — конечный автомат по спецификации.

Правила (из описания автора):

  * A-уровень: зелёная свеча, сразу за ней красная -> уровень = CLOSE зелёной.
  * V-уровень: красная свеча, сразу за ней зелёная -> уровень = CLOSE красной.
  * Дожи (open == close) не участвует.

  * DBO A (нисходящая лестница): держим пару A1 (сверху) и A2 (снизу), A2 < A1.
      - новый A-уровень ниже A2 -> пара СДВИГАЕТСЯ: A2 становится A1, новый — A2;
      - новый A-уровень на уровне A2 или выше -> поиск ПЕРЕЗАПУСКАЕТСЯ с него как A1;
      - закрытие ВЫШЕ A1 -> пробой подтверждён, отмечается A2.
    DBO V — зеркально (пара V1 снизу, V2 сверху, закрытие ниже V1, отмечается V2).

  * Пробой проверяется РАНЬШЕ, чем новый уровень.

  * DBO to DBO: подтверждённый DBO A может быть снят закрытием ниже его уровня после
    подтверждённого DBO V (и зеркально) — уровень «апгрейдится», а не дублируется.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Event:
    side: str            # "A" (пробой вверх) | "V" (пробой вниз)
    level: float         # отмечаемый уровень (A2 / V2)
    outer: float         # A1 / V1 — то, что пробили
    bar: int             # индекс бара подтверждения
    time: pd.Timestamp
    upgraded: bool = False


def find_events(df: pd.DataFrame, scan_length: int = 500) -> list[Event]:
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    ts = df.index

    green = c > o
    red = c < o

    a1: float | None = None
    a2: float | None = None
    v1: float | None = None
    v2: float | None = None
    a_born = v_born = 0

    events: list[Event] = []

    for i in range(1, len(df)):
        # 1) пробой проверяем первым
        if a1 is not None and a2 is not None and c[i] > a1:
            events.append(Event("A", a2, a1, i, ts[i]))
            a1 = a2 = None
        if v1 is not None and v2 is not None and c[i] < v1:
            events.append(Event("V", v2, v1, i, ts[i]))
            v1 = v2 = None

        # 2) затем разбираем новый уровень
        if green[i - 1] and red[i]:
            lvl = c[i - 1]
            if a1 is None:
                a1, a2, a_born = lvl, None, i
            elif a2 is None:
                if lvl < a1:
                    a2 = lvl
                else:
                    a1, a_born = lvl, i
            elif lvl < a2:
                a1, a2 = a2, lvl
            else:
                a1, a2, a_born = lvl, None, i

        if red[i - 1] and green[i]:
            lvl = c[i - 1]
            if v1 is None:
                v1, v2, v_born = lvl, None, i
            elif v2 is None:
                if lvl > v1:
                    v2 = lvl
                else:
                    v1, v_born = lvl, i
            elif lvl > v2:
                v1, v2 = v2, lvl
            else:
                v1, v2, v_born = lvl, None, i

        # 3) устаревание ожидающей пары
        if a1 is not None and i - a_born > scan_length:
            a1 = a2 = None
        if v1 is not None and i - v_born > scan_length:
            v1 = v2 = None

    return events


def _upgrade_events(events: list[Event]) -> None:
    """Помечает DBO-to-DBO: уровень снят обратным пробоем."""
    for i, ev in enumerate(events):
        opposite = [e for e in events[:i] if e.side != ev.side]
        if not opposite:
            continue
        last_opp = opposite[-1]
        # противоположный пробой случился раньше, а теперь цена закрылась за уровень
        ev.upgraded = (ev.side == "A" and last_opp.side == "V" and ev.level <= last_opp.level) or (
            ev.side == "V" and last_opp.side == "A" and ev.level >= last_opp.level
        )


def dbo_signals(
    df: pd.DataFrame,
    mode: str = "retest",
    window: int = 12,
    tol_atr: float = 0.25,
    rr: float = 2.0,
    stop_atr: float = 1.5,
    buffer_atr: float = 0.25,
    scan_length: int = 500,
    upgraded_only: bool = False,
) -> pd.DataFrame:
    """Сигналы по DBO-уровням.

    mode="retest"   — вход на первом возврате к отмеченному уровню (как в описании);
    mode="breakout" — вход сразу на подтверждении двойного пробоя.
    """
    n = len(df)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)

    events = find_events(df, scan_length=scan_length)
    _upgrade_events(events)

    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    stop_price = np.full(n, np.nan)
    reason = np.empty(n, dtype=object)
    reason[:] = ""

    used: set[int] = set()

    for k, ev in enumerate(events):
        if upgraded_only and not ev.upgraded:
            continue
        if ev.bar + 1 >= n:
            continue

        if mode == "breakout":
            i = ev.bar + 1
            if long_sig[i] or short_sig[i]:
                continue
            a = atr[ev.bar]
            if not np.isfinite(a) or a <= 0:
                continue
            if ev.side == "A":
                long_sig[i] = True
                stop_price[i] = close[ev.bar] - stop_atr * a
            else:
                short_sig[i] = True
                stop_price[i] = close[ev.bar] + stop_atr * a
            reason[i] = (
                f"{'DBO A' if ev.side == 'A' else 'DBO V'}: двойной пробой, "
                f"уровень {ev.level:.2f}"
            )
            used.add(k)
            continue

        # retest: ждём возврата к уровню в пределах window баров
        for i in range(ev.bar + 1, min(ev.bar + 1 + window, n)):
            a = atr[i]
            if not np.isfinite(a) or a <= 0:
                continue
            if ev.side == "A":
                touched = low[i] <= ev.level + tol_atr * a
                held = close[i] > ev.level
                if touched and held:
                    long_sig[i] = True
                    stop_price[i] = min(low[i], ev.level) - buffer_atr * a
                    reason[i] = f"ретест DBO A уровня {ev.level:.2f} (двойной пробой вверх)"
                    used.add(k)
                    break
            else:
                touched = high[i] >= ev.level - tol_atr * a
                held = close[i] < ev.level
                if touched and held:
                    short_sig[i] = True
                    stop_price[i] = max(high[i], ev.level) + buffer_atr * a
                    reason[i] = f"ретест DBO V уровня {ev.level:.2f} (двойной пробой вниз)"
                    used.add(k)
                    break

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["stop_atr"] = stop_atr
    out["rr"] = rr
    out["stop_price"] = stop_price
    out["reason"] = reason
    return out
