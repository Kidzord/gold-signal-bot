"""Стратегии генерации сигналов по золоту (H1).

Каждая стратегия возвращает DataFrame с колонками:
    long_signal / short_signal : bool  — сигнал на закрытии бара (вход на следующем открытии)
    stop_atr                   : float — множитель ATR для стопа
    rr                         : float — тейк-профит в R
    reason                     : str   — человекочитаемое обоснование
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Strategy:
    name: str
    title: str
    stop_atr: float
    rr: float
    max_bars: int = 48
    params: dict = field(default_factory=dict)


def _reason_long(row) -> str:
    return (
        f"цена {row['close']:.2f} выше EMA200 ({row['ema200']:.2f}), "
        f"ADX {row['adx']:.0f}, импульс вверх"
    )


def trend_pullback(df: pd.DataFrame) -> pd.DataFrame:
    """A. Тренд + откат: EMA50/EMA200 + RSI-откат + ADX."""
    out = pd.DataFrame(index=df.index)
    up = (df["close"] > df["ema200"]) & (df["ema50"] > df["ema200"])
    dn = (df["close"] < df["ema200"]) & (df["ema50"] < df["ema200"])
    trend_ok = df["adx"] > 18

    rsi_prev = df["rsi"].shift(1)
    cross_up = (rsi_prev < 45) & (df["rsi"] >= 45)
    cross_dn = (rsi_prev > 55) & (df["rsi"] <= 55)

    out["long_signal"] = up & trend_ok & cross_up & (df["close"] > df["ema50"])
    out["short_signal"] = dn & trend_ok & cross_dn & (df["close"] < df["ema50"])
    out["stop_atr"] = 1.5
    out["rr"] = 2.0
    out["reason"] = ""
    out.loc[out["long_signal"], "reason"] = "откат к EMA50 в восходящем тренде, RSI развернулся вверх"
    out.loc[out["short_signal"], "reason"] = "откат к EMA50 в нисходящем тренде, RSI развернулся вниз"
    return out


def channel_breakout(df: pd.DataFrame, channel: int = 24, stop_atr: float = 1.5,
                     rr: float = 2.0) -> pd.DataFrame:
    """Пробой канала заданной длины в направлении тренда.

    Условия (на закрытии бара):
      * закрытие выше максимума предыдущих `channel` баров (или ниже минимума);
      * тренд согласован: цена и EMA50 по одну сторону от EMA200;
      * ADX > 18; ATR выше 0.8 медианы ATR(200).

    Золото H1: channel=24 (сутки). EURUSD H4: 48 (8 дней), GBPUSD H4: 24 (4 дня).
    """
    hi = df["high"].rolling(channel).max().shift(1)
    lo = df["low"].rolling(channel).min().shift(1)
    vol_ok = df["atr"] > 0.8 * df["atr_median"]

    up = (df["close"] > df["ema200"]) & (df["ema50"] > df["ema200"])
    dn = (df["close"] < df["ema200"]) & (df["ema50"] < df["ema200"])

    out = pd.DataFrame(index=df.index)
    out["long_signal"] = (df["close"] > hi) & up & vol_ok & (df["adx"] > 18)
    out["short_signal"] = (df["close"] < lo) & dn & vol_ok & (df["adx"] > 18)
    out["stop_atr"] = stop_atr
    out["rr"] = rr
    out["reason"] = ""
    out.loc[out["long_signal"], "reason"] = (
        f"пробой максимума {channel} баров, тренд вверх (цена и EMA50 выше EMA200), "
        "волатильность выше нормы"
    )
    out.loc[out["short_signal"], "reason"] = (
        f"пробой минимума {channel} баров, тренд вниз (цена и EMA50 ниже EMA200), "
        "волатильность выше нормы"
    )
    return out


def breakout(df: pd.DataFrame) -> pd.DataFrame:
    """B. Пробой 24-часового канала (базовая стратегия для золота H1)."""
    return channel_breakout(df, channel=24)


def macd_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """C. Импульс MACD в направлении EMA200."""
    out = pd.DataFrame(index=df.index)
    hist_prev = df["macd_hist"].shift(1)
    cross_up = (hist_prev <= 0) & (df["macd_hist"] > 0)
    cross_dn = (hist_prev >= 0) & (df["macd_hist"] < 0)

    out["long_signal"] = cross_up & (df["close"] > df["ema200"]) & (df["adx"] > 20)
    out["short_signal"] = cross_dn & (df["close"] < df["ema200"]) & (df["adx"] > 20)
    out["stop_atr"] = 1.5
    out["rr"] = 1.5
    out["reason"] = ""
    out.loc[out["long_signal"], "reason"] = "MACD развернулся вверх выше EMA200"
    out.loc[out["short_signal"], "reason"] = "MACD развернулся вниз ниже EMA200"
    return out


def msnr_break(df: pd.DataFrame) -> pd.DataFrame:
    """D. MSNR: отбой от свежего уровня (спецификация LuxAlgo «Malaysian SnR»).

    Уровни — подтверждённые пивоты линейного графика (по close), торгуем только свежие,
    вход на фитиле с возвратом закрытия, стоп за фитиль/уровень + буфер ATR,
    цель — следующий свежий уровень (иначе 3R), фильтр по направлению storyline.
    """
    import msnr_v2

    return msnr_v2.msnr_v2_signals(
        df, turn=3, max_body_crosses=3, stop_buffer_atr=0.25,
        fallback_r=3.0, use_storyline=True, fresh_only=True, min_reward_r=0.0,
    )


def msnr_trend(df: pd.DataFrame) -> pd.DataFrame:
    """E. MSNR + высокий RR: пробой дневного уровня с целью 8R.

    Идея взята из разборов MSNR-сообщества: маленький стоп за уровнем и большая цель
    (5–10R), за счёт чего система живёт при винрейте ~30–35 %. Удержание до 5 суток.
    """
    import msnr

    zones = msnr.htf_zones(df, rule="1D", strength=3)
    return msnr.signals_from_zones(
        df, zones, mode="break", trend_filter=False, zone_stop=True, rr=8.0
    )


def asian_breakout(df: pd.DataFrame) -> pd.DataFrame:
    """F. Азиатский диапазон (сетап из методички Malaysian SNR).

    Диапазон 01:00–07:00 UTC — зона. В окне Лондона/Нью-Йорка (07:00–18:00 UTC) вход
    на закрытии за границей диапазона с буфером 0.2 ATR, стоп за противоположной
    границей, цель 2R, удержание до 72 баров.
    """
    import asian

    return asian.asian_range_signals(
        df, start=1, end=7, entry_from=7, entry_to=18,
        buffer_atr=0.2, stop_mode="range", rr=2.0,
    )


def flip_break(df: pd.DataFrame) -> pd.DataFrame:
    """G. Flipped SNR: смена роли уровня по правилам Malaysian SNR.

    Уровень строится от close первой свечи к open второй. Пробой телом = fresh flip:
    вход в сторону пробоя, стоп за уровнем (0.8 ATR), цель 2R, удержание до 72 баров.
    Лучше всего работает на золоте H4.
    """
    import flip

    return flip.flip_signals(df, buffer_atr=0.2, stop_atr=0.8, rr=2.0)


def fvg_retest(df: pd.DataFrame) -> pd.DataFrame:
    """H. Имбаланс (FVG) + подтверждение закрытием — сетап из разбора видео.

    Имбаланс — разрыв между свечой i-2 и свечой i. Цена возвращается в зону и
    закрывается обратно за границей (подтверждение), вход в сторону импульса,
    стоп за зоной, цель 3R.
    """
    import fvg

    return fvg.fvg_signals(df, mode="confirm", min_gap_atr=0.25, rr=3.0)


def smt_divergence(df: pd.DataFrame, sibling: str = "SI=F", k: int = 2,
                   stop_atr: float = 1.5, rr: float = 3.0) -> pd.DataFrame:
    """I. SMT: расхождение «золото против серебра» (экспериментальная).

    Если на экстремуме золото обновляет предыдущий максимум, а серебро — нет
    (или наоборот по минимумам), ждём разворот золота в сторону серебра.
    Свечи серебра подтягиваются отдельно и выравниваются по сетке инструмента.

    ⚠️ На H1 даёт PF ~1.16 / ожидание +0.11R при 206 сделках — заметно слабее
    breakout (PF 1.41 / +0.24R), walk-forward нестабилен. По умолчанию не включена.
    """
    import market
    import smt

    silver = market.get_history(sibling, "1h", "730d")
    if len(df) > 2:
        step = df.index.to_series().diff().median()
        hours = max(int(round(step.total_seconds() / 3600)), 1)
        if hours > 1:
            silver = (
                silver.resample(f"{hours}h")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna()
            )
    return smt.smt_signals(df, silver, k=k, stop_atr=stop_atr, rr=rr)


CATALOG: dict[str, tuple[Strategy, object]] = {
    "pullback": (Strategy("pullback", "Тренд + откат (EMA50/200, RSI, ADX)", 1.5, 2.0), trend_pullback),
    "breakout": (Strategy("breakout", "Пробой канала 24ч + тренд", 1.5, 2.0), breakout),
    "channel": (Strategy("channel", "Пробой канала (длина настраивается)", 1.5, 2.0), channel_breakout),
    "asian": (Strategy("asian", "Азиатский диапазон (пробой в Лондон/НЙ)", 1.5, 2.0, max_bars=72), asian_breakout),
    "flip": (Strategy("flip", "Flipped SNR (смена роли уровня)", 0.8, 2.0, max_bars=72), flip_break),
    "fvg": (Strategy("fvg", "Имбаланс (FVG) + подтверждение", 1.0, 3.0, max_bars=30), fvg_retest),
    "macd": (Strategy("macd", "Импульс MACD + тренд", 1.5, 1.5), macd_momentum),
    "msnr": (Strategy("msnr", "MSNR: отбой от свежего уровня, 2R", 1.5, 2.0), msnr_break),
    "msnr_trend": (Strategy("msnr_trend", "MSNR + высокий RR: цель 8R", 1.5, 8.0, max_bars=120), msnr_trend),
    "smt": (Strategy("smt", "SMT: расхождение золото/серебро (эксперимент)", 1.5, 3.0), smt_divergence),
}

CHANNEL_DEFAULTS = {"channel": 24, "stop_atr": 1.5, "rr": 2.0}
SMT_DEFAULTS = {"sibling": "SI=F", "k": 2, "stop_atr": 1.5, "rr": 3.0}


def signals_for(name: str, df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Сигналы стратегии с учётом параметров инструмента."""
    meta, fn = get_strategy(name)
    if name == "channel":
        opts = dict(CHANNEL_DEFAULTS)
        for key in list(opts):
            if params and key in params:
                opts[key] = params[key]
        return channel_breakout(df, **opts)
    if name == "smt":
        opts = dict(SMT_DEFAULTS)
        for key in list(opts):
            if params and key in params:
                opts[key] = params[key]
        return smt_divergence(df, **opts)
    return fn(df)

# Стратегия, выбранная по результатам бэктеста (см. REPORT.md)
DEFAULT_STRATEGY = "breakout"


def get_strategy(name: str | None = None):
    key = name or DEFAULT_STRATEGY
    if key not in CATALOG:
        raise KeyError(f"Неизвестная стратегия: {key}. Доступны: {', '.join(CATALOG)}")
    meta, fn = CATALOG[key]
    return meta, fn
