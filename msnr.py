"""MSNR-уровни (Malaysian Support & Resistance) и сигналы на их основе.

Оригинальный индикатор TTQ / Milana Trades — с закрытым исходником, поэтому здесь
реализована механика подхода: горизонтальные зоны из подтверждённых пивотов, у которых
есть верхняя и нижняя граница (ширина зоны), с возможностью строить уровни на старшем
таймфрейме и проецировать их на рабочий.

Сигналы:
  * "bounce" — цена вошла в зону и закрылась обратно (отбой);
  * "break"  — цена закрылась за зоной (пробой).
Пивот подтверждается через `strength` баров после него — заглядывания в будущее нет.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Zone:
    kind: str                 # "support" | "resistance"
    top: float
    bottom: float
    born: pd.Timestamp        # бар, на котором зона подтверждена
    broken: pd.Timestamp | None = None

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def __repr__(self) -> str:  # компактно для логов
        return f"Zone({self.kind} {self.bottom:.2f}-{self.top:.2f})"


def build_zones(
    df: pd.DataFrame,
    strength: int = 3,
    width_atr: float = 0.25,
    max_zones: int = 8,
    ttl: int = 240,
) -> list[Zone]:
    """Полная история зон: пивот -> зона, живёт до пробоя, ttl или вытеснения."""
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)
    ts = df.index

    all_zones: list[Zone] = []
    alive: list[Zone] = []
    born_at: dict[int, int] = {}

    def register(zone: Zone, i: int, atr_j: float) -> None:
        for z in alive:
            if z.kind == zone.kind and abs(z.top - zone.top) < 0.6 * atr_j:
                return
        zone.born = ts[i]
        alive.append(zone)
        all_zones.append(zone)
        born_at[id(zone)] = i

    for i in range(len(df)):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        j = i - strength
        if j - strength >= 0:
            w_hi = h[j - strength: j + strength + 1]
            w_lo = l[j - strength: j + strength + 1]
            if len(w_hi) == 2 * strength + 1:
                if int(np.argmax(w_hi)) == strength:
                    register(Zone("resistance", h[j], h[j] - width_atr * atr[j], ts[i]), i, atr[j])
                if int(np.argmin(w_lo)) == strength:
                    register(Zone("support", l[j] + width_atr * atr[j], l[j], ts[i]), i, atr[j])

        for z in alive:
            if z.broken is not None:
                continue
            if z.kind == "resistance" and c[i] > z.top + 0.5 * a:
                z.broken = ts[i]
            elif z.kind == "support" and c[i] < z.bottom - 0.5 * a:
                z.broken = ts[i]

        for z in list(alive):
            if z.broken is None and (i - born_at[id(z)]) > ttl:
                z.broken = ts[i]

        alive = [z for z in alive if z.broken is None]
        while len(alive) > max_zones:
            alive.pop(0).broken = ts[i]

    return all_zones


def _np_time(value) -> np.datetime64:
    """Приводит метку к datetime64[ns] в UTC (сравнимо с индексом)."""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return np.datetime64(stamp.to_datetime64())


def _index_stamps(df: pd.DataFrame) -> np.ndarray:
    idx = df.index
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.to_numpy().astype("datetime64[ns]")


def signals_from_zones(
    df: pd.DataFrame,
    zones: list[Zone],
    mode: str = "bounce",
    trend_filter: bool = True,
    zone_stop: bool = True,
    stop_mult: float = 1.5,
    rr: float = 2.0,
    dedup_bars: int = 6,
    ttl_bars: int = 240,
) -> pd.DataFrame:
    """Сигналы на барах df по готовому списку зон (в т.ч. со старшего ТФ)."""
    n = len(df)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)
    ema50 = df["ema50"].to_numpy(float)
    ema200 = df["ema200"].to_numpy(float)

    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    stop_price = np.full(n, np.nan)
    reason = np.empty(n, dtype=object)
    reason[:] = ""

    # индекс зоны -> номер бара последнего сигнала
    last_signal: dict[int, int] = {}

    # окна жизни зон в номерах баров: быстрый свип вместо перебора всех зон на каждом баре
    stamps = _index_stamps(df)
    intervals: list[tuple[int, int, Zone]] = []
    for z in zones:
        start = int(np.searchsorted(stamps, _np_time(z.born), "left"))
        end = n if z.broken is None else int(np.searchsorted(stamps, _np_time(z.broken), "left"))
        if end > start:
            intervals.append((start, end, z))
    intervals.sort(key=lambda x: x[0])

    active: list[tuple[int, int, Zone]] = []
    ptr = 0

    for i in range(1, n):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        active = [item for item in active if item[1] > i]
        while ptr < len(intervals) and intervals[ptr][0] <= i:
            item = intervals[ptr]
            if item[1] > i:
                active.append(item)
            ptr += 1
        if not active:
            continue

        allow_long = (not trend_filter) or (c[i] > ema200[i] and ema50[i] > ema200[i])
        allow_short = (not trend_filter) or (c[i] < ema200[i] and ema50[i] < ema200[i])

        for k, _end, z in active:
            if i - last_signal.get(k, -10**6) <= dedup_bars:
                continue

            if mode == "bounce":
                if z.kind == "support" and allow_long:
                    if l[i] <= z.top and l[i] >= z.bottom - 0.35 * a and c[i] > z.top and c[i - 1] > z.bottom:
                        long_sig[i] = True
                        last_signal[k] = i
                        stop_price[i] = z.bottom - 0.5 * a if zone_stop else np.nan
                        reason[i] = f"отбой от поддержки {z.bottom:.2f}–{z.top:.2f} (MSNR)"
                        break
                elif z.kind == "resistance" and allow_short:
                    if h[i] >= z.bottom and h[i] <= z.top + 0.35 * a and c[i] < z.bottom and c[i - 1] < z.top:
                        short_sig[i] = True
                        last_signal[k] = i
                        stop_price[i] = z.top + 0.5 * a if zone_stop else np.nan
                        reason[i] = f"отбой от сопротивления {z.bottom:.2f}–{z.top:.2f} (MSNR)"
                        break

            elif mode == "break":
                if z.kind == "resistance" and allow_long:
                    if c[i] > z.top + 0.2 * a and c[i - 1] <= z.top:
                        long_sig[i] = True
                        last_signal[k] = i
                        stop_price[i] = (z.bottom - 0.3 * a) if zone_stop else np.nan
                        reason[i] = f"пробой сопротивления {z.bottom:.2f}–{z.top:.2f} (MSNR)"
                        break
                elif z.kind == "support" and allow_short:
                    if c[i] < z.bottom - 0.2 * a and c[i - 1] >= z.bottom:
                        short_sig[i] = True
                        last_signal[k] = i
                        stop_price[i] = (z.top + 0.3 * a) if zone_stop else np.nan
                        reason[i] = f"пробой поддержки {z.bottom:.2f}–{z.top:.2f} (MSNR)"
                        break

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["stop_atr"] = stop_mult
    out["rr"] = rr
    out["stop_price"] = stop_price
    out["reason"] = reason
    return out


def msnr_signals(df: pd.DataFrame, **kw) -> pd.DataFrame:
    """Сигналы по зонам, построенным на том же таймфрейме."""
    strength = kw.pop("strength", 3)
    width_atr = kw.pop("width_atr", 0.25)
    ttl = kw.pop("ttl_bars", 240)
    zones = build_zones(df, strength=strength, width_atr=width_atr, ttl=ttl)
    return signals_from_zones(df, zones, ttl_bars=ttl, **kw)


def htf_zones(df_h1: pd.DataFrame, rule: str = "4h", strength: int = 3,
              width_atr: float = 0.25) -> list[Zone]:
    """Зоны на старшем таймфрейме для проецирования на H1.

    Пивот подтверждается на закрытии htf-бара, поэтому время жизни зоны сдвигается
    на длину бара — иначе H1 увидел бы уровень раньше, чем он сформировался.
    """
    htf = df_h1.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    htf = _enrich_for_zones(htf)
    zones = build_zones(htf, strength=strength, width_atr=width_atr)

    shift = pd.Timedelta(rule)
    for z in zones:
        z.born = z.born + shift
        if z.broken is not None:
            z.broken = z.broken + shift
    return zones


def _enrich_for_zones(df: pd.DataFrame) -> pd.DataFrame:
    import indicators

    return indicators.enrich(df)


def nearest_levels(df: pd.DataFrame, zones: list[Zone]) -> dict:
    """Ближайшие незакрытые зоны относительно последней цены."""
    price = float(df["close"].iloc[-1])
    now = df.index[-1]
    live = [z for z in zones if z.born <= now and (z.broken is None or z.broken > now)]
    supports = sorted((z for z in live if z.kind == "support" and z.top < price), key=lambda z: -z.top)
    resist = sorted((z for z in live if z.kind == "resistance" and z.bottom > price), key=lambda z: z.bottom)
    return {
        "nearest_support": supports[0] if supports else None,
        "nearest_resistance": resist[0] if resist else None,
        "active": len(live),
    }
