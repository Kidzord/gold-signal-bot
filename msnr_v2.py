"""MSNR v2 — по публичной спецификации LuxAlgo «Malaysian SnR».

Отличия от первой версии (msnr.py), которая строила зоны из high/low пивотов:
  * уровни берутся из ПИВОТОВ ЛИНЕЙНОГО ГРАФИКА (по close), а не по экстремумам свечей;
  * уровень «свежий» (fresh), пока к нему не прикасались — торгуем только свежие;
  * уровень выбывает после N пробоев телом свечи или по возрасту;
  * вход: фитиль коснулся уровня, а закрытие вернулось на исходную сторону;
  * стоп: за уровень/фитиль + буфер в ATR;
  * цель: следующий свежий уровень в направлении сделки, иначе фолбэк в R;
  * минимальный RR: сделка отбрасывается, если цель ближе порога;
  * «storyline»: направление старшего (более крупного) линейного графика.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from msnr import _index_stamps, _np_time


@dataclass
class Level:
    price: float
    kind: str                    # "support" | "resistance"
    born: pd.Timestamp
    crosses: int = 0
    touches: int = 0
    first_touch: pd.Timestamp | None = None
    dead: pd.Timestamp | None = None

    def is_fresh(self, at: pd.Timestamp) -> bool:
        """Свежий ли уровень на момент `at` (без заглядывания в будущее)."""
        return self.first_touch is None or self.first_touch >= at


def _pivot_series(close: pd.Series, turn: int) -> tuple[np.ndarray, np.ndarray]:
    """Маски подтверждённых пивотов сверху/снизу (по close)."""
    n = len(close)
    vals = close.to_numpy(float)
    hi = np.zeros(n, bool)
    lo = np.zeros(n, bool)
    for i in range(2 * turn, n):
        j = i - turn
        window = vals[j - turn: j + turn + 1]
        if len(window) != 2 * turn + 1:
            continue
        if int(np.argmax(window)) == turn:
            hi[i] = True
        if int(np.argmin(window)) == turn:
            lo[i] = True
    return hi, lo


def storyline_direction(df: pd.DataFrame, turn: int = 5) -> np.ndarray:
    """Направление старшего графика на каждом баре: up / down / flat."""
    close = df["close"]
    hi_mask, lo_mask = _pivot_series(close, turn)
    vals = close.to_numpy(float)
    n = len(df)

    highs: list[float] = []
    lows: list[float] = []
    out = np.empty(n, dtype=object)
    out[:] = "flat"

    for i in range(n):
        if hi_mask[i]:
            highs.append(vals[i - turn])
        if lo_mask[i]:
            lows.append(vals[i - turn])
        direction = "flat"
        if len(highs) >= 2 and len(lows) >= 2:
            hh = highs[-1] > highs[-2]
            hl = lows[-1] > lows[-2]
            lh = highs[-1] < highs[-2]
            ll = lows[-1] < lows[-2]
            if hh and hl:
                direction = "up"
            elif lh and ll:
                direction = "down"
        out[i] = direction
    return out


def build_levels(
    df: pd.DataFrame,
    turn: int = 3,
    max_body_crosses: int = 1,
    lifetime: int = 240,
    dedupe_atr: float = 0.5,
) -> list[Level]:
    close = df["close"]
    high, low = df["high"], df["low"]
    atr = df["atr"]
    ts = df.index
    hi_mask, lo_mask = _pivot_series(close, turn)

    levels: list[Level] = []
    alive: list[Level] = []
    born_idx: dict[int, int] = {}

    def register(price: float, kind: str, i: int) -> None:
        a = atr.iloc[i]
        if not np.isfinite(a) or a <= 0:
            return
        for lv in alive:
            if abs(lv.price - price) < dedupe_atr * a:
                return
        lv = Level(price=float(price), kind=kind, born=ts[i])
        levels.append(lv)
        alive.append(lv)
        born_idx[id(lv)] = i

    for i in range(len(df)):
        if hi_mask[i]:
            register(close.iloc[i - turn], "resistance", i)
        if lo_mask[i]:
            register(close.iloc[i - turn], "support", i)

        prev = close.iloc[i - 1]
        cur = close.iloc[i]
        for lv in alive:
            if (prev < lv.price <= cur) or (prev > lv.price >= cur):
                lv.crosses += 1
            if (lv.kind == "resistance" and high.iloc[i] >= lv.price) or (
                lv.kind == "support" and low.iloc[i] <= lv.price
            ):
                lv.touches += 1
                if lv.first_touch is None:
                    lv.first_touch = ts[i]
            if lv.crosses > max_body_crosses or (i - born_idx[id(lv)]) > lifetime:
                lv.dead = ts[i]

        alive = [lv for lv in alive if lv.dead is None]

    return levels


def _next_fresh(levels: list[Level], kind: str, current: float, at: pd.Timestamp) -> float | None:
    """Ближайший свежий уровень нужного типа в направлении сделки."""
    if kind == "resistance":
        cand = [lv.price for lv in levels
                if lv.kind == "resistance" and lv.price > current and lv.is_fresh(at)]
        return min(cand) if cand else None
    cand = [lv.price for lv in levels
            if lv.kind == "support" and lv.price < current and lv.is_fresh(at)]
    return max(cand) if cand else None


def msnr_v2_signals(
    df: pd.DataFrame,
    turn: int = 3,
    max_body_crosses: int = 3,
    lifetime: int = 240,
    stop_buffer_atr: float = 0.25,
    fallback_r: float = 3.0,
    use_storyline: bool = True,
    storyline_turn: int = 5,
    fresh_only: bool = True,
    max_touch_depth_atr: float = 1.0,
    min_reward_r: float = 0.0,
    levels: list[Level] | None = None,
    story: np.ndarray | None = None,
) -> pd.DataFrame:
    n = len(df)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)
    ts = df.index

    if levels is None:
        levels = build_levels(df, turn=turn, max_body_crosses=max_body_crosses, lifetime=lifetime)
    if use_storyline and story is None:
        story = storyline_direction(df, turn=storyline_turn)
    if story is None:
        story = np.array(["flat"] * n, dtype=object)

    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    stop_price = np.full(n, np.nan)
    tp_price = np.full(n, np.nan)
    reason = np.empty(n, dtype=object)
    reason[:] = ""

    # окна жизни уровней -> свип по барам
    stamps = _index_stamps(df)
    intervals: list[tuple[int, int, Level]] = []
    for lv in levels:
        start = int(np.searchsorted(stamps, _np_time(lv.born), "left"))
        end = n if lv.dead is None else int(np.searchsorted(stamps, _np_time(lv.dead), "left"))
        if end > start:
            intervals.append((start, end, lv))
    intervals.sort(key=lambda x: x[0])

    active: list[tuple[int, int, Level]] = []
    ptr = 0
    used: set[int] = set()

    for i in range(2, n):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        active = [it for it in active if it[1] > i]
        while ptr < len(intervals) and intervals[ptr][0] <= i:
            item = intervals[ptr]
            if item[1] > i:
                active.append(item)
            ptr += 1
        if not active:
            continue

        candidates = [
            lv for _s, _e, lv in active
            if (lv.is_fresh(ts[i]) or not fresh_only) and id(lv) not in used and lv.born < ts[i]
        ]
        if not candidates:
            continue

        direction = story[i]

        for lv in candidates:
            if lv.kind == "support":
                if direction == "down":
                    continue
                touched = low[i] <= lv.price and low[i] >= lv.price - max_touch_depth_atr * a
                if touched and close[i] > lv.price:
                    stop = min(low[i], lv.price) - stop_buffer_atr * a
                    tgt = _next_fresh(candidates, "resistance", close[i], ts[i])
                    long_sig[i] = True
                    stop_price[i] = stop
                    tp_price[i] = tgt if tgt is not None else np.nan
                    reason[i] = (
                        f"свежая поддержка {lv.price:.2f} (линейный пивот), "
                        f"фитиль и возврат закрытием"
                    )
                    used.add(id(lv))
                    break
            else:
                if direction == "up":
                    continue
                touched = high[i] >= lv.price and high[i] <= lv.price + max_touch_depth_atr * a
                if touched and close[i] < lv.price:
                    stop = max(high[i], lv.price) + stop_buffer_atr * a
                    tgt = _next_fresh(candidates, "support", close[i], ts[i])
                    short_sig[i] = True
                    stop_price[i] = stop
                    tp_price[i] = tgt if tgt is not None else np.nan
                    reason[i] = (
                        f"свежее сопротивление {lv.price:.2f} (линейный пивот), "
                        f"фитиль и возврат закрытием"
                    )
                    used.add(id(lv))
                    break

    # валидация: цель не ближе min_reward_r, иначе фолбэк в R
    for i in range(n):
        if not (long_sig[i] or short_sig[i]):
            continue
        risk = abs(close[i] - stop_price[i])
        if not np.isfinite(risk) or risk <= 0:
            long_sig[i] = short_sig[i] = False
            continue
        target = tp_price[i]
        if np.isfinite(target) and abs(target - close[i]) / risk < min_reward_r:
            target = np.nan
        if not np.isfinite(target):
            if fallback_r < min_reward_r:
                long_sig[i] = short_sig[i] = False
                continue
            target = close[i] + fallback_r * risk if long_sig[i] else close[i] - fallback_r * risk
        tp_price[i] = target

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["stop_atr"] = 1.5
    out["rr"] = fallback_r
    out["stop_price"] = stop_price
    out["tp_price"] = tp_price
    out["reason"] = reason
    return out
