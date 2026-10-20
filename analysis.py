"""Аналитика: состояние рынка, поиск сигнала, сопровождение сделки, тексты сообщений."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import backtest as bt
import indicators
import market
import msnr
import strategy as st
import tg

log = logging.getLogger(__name__)

SPREAD = 0.30
MAX_BARS = 48


# ---------------------------------------------------------------- данные

def load_frame(symbol: str, max_age: int = 300, only_closed: bool = True,
               timeframe: str = "1h") -> pd.DataFrame:
    """Свечи инструмента: H1 с Yahoo, при необходимости — старший таймфрейм."""
    raw = market.get_history(symbol, "1h", "730d", max_age_seconds=max_age)
    raw = market.closed_bars(raw, "1h") if only_closed else raw
    if timeframe and timeframe != "1h":
        raw = market.resample_bars(raw, timeframe)
    df = indicators.enrich(raw)
    return df.dropna(subset=["ema200", "atr", "adx", "atr_median"])


def market_state(df: pd.DataFrame) -> dict:
    row = df.iloc[-1]
    trend = "вверх" if row["ema50"] > row["ema200"] else "вниз"
    if row["close"] > row["ema200"] and trend == "вниз":
        trend = "коррекция вверх"
    elif row["close"] < row["ema200"] and trend == "вверх":
        trend = "коррекция вниз"
    return {
        "price": float(row["close"]),
        "time": df.index[-1],
        "atr": float(row["atr"]),
        "atr_pct": float(row["atr_pct"]),
        "adx": float(row["adx"]),
        "ema50": float(row["ema50"]),
        "ema200": float(row["ema200"]),
        "don_hi": float(row["don_hi"]),
        "don_lo": float(row["don_lo"]),
        "trend": trend,
        "rsi": float(row["rsi"]),
    }


# ---------------------------------------------------------------- сигнал

def detect_signal(df: pd.DataFrame, strategy: str = "breakout", params: dict | None = None,
                  max_bars: int | None = None, spread: float = SPREAD) -> dict | None:
    meta, _ = st.get_strategy(strategy)
    sig = st.signals_for(strategy, df, params)
    row = sig.iloc[-1]
    long_ = bool(row["long_signal"])
    short_ = bool(row["short_signal"])
    if not (long_ ^ short_):
        return None

    side = "long" if long_ else "short"
    bar = df.iloc[-1]
    entry = float(bar["close"])

    sp = row.get("stop_price", np.nan)
    if pd.notna(sp) and float(sp) > 0:
        stop = float(sp)
        risk = abs(entry - stop)
        if (side == "long" and stop >= entry) or (side == "short" and stop <= entry):
            risk = 0.0  # некорректный уровень — уходим на ATR-стоп
    else:
        risk = 0.0

    if risk <= 0:
        risk = float(row["stop_atr"]) * bar["atr"]
        stop = entry - risk if side == "long" else entry + risk

    tp = entry + risk * row["rr"] if side == "long" else entry - risk * row["rr"]
    tp_fixed = row.get("tp_price", np.nan)
    if pd.notna(tp_fixed) and float(tp_fixed) > 0 and (
        (side == "long" and float(tp_fixed) > entry) or (side == "short" and float(tp_fixed) < entry)
    ):
        tp = float(tp_fixed)
    return {
        "id": f"{side}-{df.index[-1].strftime('%Y%m%d%H%M')}",
        "side": side,
        "entry": entry,
        "stop": stop,
        "tp": tp,
        "risk": risk,
        "rr": float(row["rr"]),
        "atr": float(bar["atr"]),
        "adx": float(bar["adx"]),
        "trend": market_state(df)["trend"],
        "reason": str(row["reason"]),
        "bar_time": df.index[-1].isoformat(),
        "max_bars": int(max_bars or meta.max_bars),
        "spread": float(spread),
        "status": "open",
    }


def check_open_trade(trade: dict, df: pd.DataFrame) -> dict | None:
    """Проверяет, не закрылась ли сделка по стопу/тейку/времени на закрытых барах."""
    opened = pd.Timestamp(trade["bar_time"])
    bars = df[df.index > opened]
    if bars.empty:
        return None

    side, entry, stop, tp = trade["side"], trade["entry"], trade["stop"], trade["tp"]
    risk = trade["risk"]
    max_bars = int(trade.get("max_bars", MAX_BARS))
    cost = float(trade.get("spread", SPREAD))
    for n, (ts, row) in enumerate(bars.iterrows(), start=1):
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        price = reason = None
        if side == "long":
            if l <= stop:
                price, reason = (stop if o >= stop else o), "SL"
            elif h >= tp:
                price, reason = (tp if o <= tp else o), "TP"
        else:
            if h >= stop:
                price, reason = (stop if o <= stop else o), "SL"
            elif l <= tp:
                price, reason = (tp if o >= tp else o), "TP"

        if price is None and n >= max_bars:
            price, reason = c, "TIME"
        if price is not None:
            gross = (price - entry) if side == "long" else (entry - price)
            pnl = gross - cost
            return {
                "exit": float(price),
                "reason": reason,
                "exit_time": ts.isoformat(),
                "bars": n,
                "pnl_usd": float(pnl),
                "r": float(pnl / risk) if risk else 0.0,
            }
    return None


def current_risk(trade: dict, price: float) -> float:
    """Текущий результат в R по последней цене (для /signal)."""
    if not trade:
        return 0.0
    gross = (price - trade["entry"]) if trade["side"] == "long" else (trade["entry"] - price)
    cost = float(trade.get("spread", SPREAD))
    return (gross - cost) / trade["risk"] if trade["risk"] else 0.0


# ---------------------------------------------------------------- тексты

def _local(ts, tz_name: str) -> str:
    stamp = pd.Timestamp(ts)
    if stamp.tz is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert(ZoneInfo(tz_name)).strftime("%d.%m.%Y %H:%M")


def _unit(digits: int) -> str:
    return "п." if digits >= 4 else "$"


def _dist(value: float, digits: int) -> str:
    """Расстояние в удобных единицах: пипсы для форекса, доллары для золота."""
    if digits >= 4:
        return f"{value / 0.0001:.1f} п."
    return f"{value:.{digits}f} $"


def _signed_dist(value: float, digits: int) -> str:
    sign = "+" if value >= 0 else "−"
    return sign + _dist(abs(value), digits)


def format_signal(sig: dict, name: str, tz_name: str, timeframe: str = "1h",
                  digits: int = 2, strategy_title: str | None = None) -> str:
    long_ = sig["side"] == "long"
    emoji = "🟢" if long_ else "🔴"
    word = "ПОКУПКА" if long_ else "ПРОДАЖА"
    arrow = "↗" if long_ else "↘"
    r_dist = abs(sig["entry"] - sig["stop"])
    d = digits
    sub = f"\n<i>{tg.esc(strategy_title)}</i>" if strategy_title else ""
    return (
        f"🔔 <b>СИГНАЛ {tg.esc(name)} · {timeframe.upper()}</b>{sub}\n"
        f"<b>{emoji} {word} {arrow}</b>\n"
        f"────────────────\n"
        f"Вход: <b>{sig['entry']:.{d}f}</b>\n"
        f"Стоп: {sig['stop']:.{d}f} <i>(-{_dist(r_dist, d)})</i>\n"
        f"Тейк: {sig['tp']:.{d}f} <i>(+{_dist(r_dist * sig['rr'], d)})</i>\n"
        f"Риск/прибыль: 1 : {sig['rr']:.1f}\n"
        f"────────────────\n"
        f"📊 ADX {sig['adx']:.0f} · ATR {_dist(sig['atr'], d)} · тренд {tg.esc(sig['trend'])}\n"
        f"🧩 {tg.esc(sig['reason'])}\n"
        f"⏱ {_local(sig['bar_time'], tz_name)} ({tz_name.split('/')[-1]})\n\n"
        f"<i>Вход по рынку. Сделка живёт до стопа/тейка, максимум {sig.get('max_bars', MAX_BARS)} бар.\n"
        f"Не является индивидуальной инвестиционной рекомендацией.</i>"
    )


def format_close(trade: dict, result: dict, name: str, tz_name: str, digits: int = 2,
                 strategy_title: str | None = None) -> str:
    long_ = trade["side"] == "long"
    word = "LONG" if long_ else "SHORT"
    if result["reason"] == "TP":
        head = "✅ <b>ТЕЙК ВЗЯТ</b>"
    elif result["reason"] == "SL":
        head = "❌ <b>СТОП</b>"
    else:
        head = "⏱ <b>ЗАКРЫТО ПО ВРЕМЕНИ</b>"
    sign = "+" if result["r"] >= 0 else "−"
    d = digits
    sub = f"\n<i>{tg.esc(strategy_title)}</i>" if strategy_title else ""
    return (
        f"{head} · {word} · {sign}{abs(result['r']):.2f}R{sub}\n"
        f"────────────────\n"
        f"{tg.esc(name)}: {trade['entry']:.{d}f} → {result['exit']:.{d}f} "
        f"({_signed_dist(result['pnl_usd'], d)})\n"
        f"Причина: {result['reason']} · в сделке {result['bars']} бар.\n"
        f"⏱ {_local(result['exit_time'], tz_name)}"
    )


def msnr_levels(df: pd.DataFrame, rule: str = "4h") -> dict | None:
    """Ближайшие уровни MSNR со старшего ТФ (H4) — для справочного блока."""
    try:
        zones = msnr.htf_zones(df, rule=rule, strength=3)
        return msnr.nearest_levels(df, zones)
    except Exception:  # noqa: BLE001 — уровни не должны ломать сообщение
        log.debug("MSNR levels failed", exc_info=True)
        return None


def format_state(df: pd.DataFrame, state: dict, name: str, tz_name: str, strategy: str,
                 timeframe: str = "1h", params: dict | None = None, digits: int = 2) -> str:
    s = market_state(df)
    unit = _unit(digits)
    d = digits
    chan = int((params or {}).get("channel", 24))
    chan_hi = float(df["high"].rolling(chan).max().shift(1).iloc[-1])
    chan_lo = float(df["low"].rolling(chan).min().shift(1).iloc[-1])
    lines = [
        f"📊 <b>{tg.esc(name)} · {timeframe.upper()}</b>",
        f"Цена: <b>{s['price']:.{d}f}</b>  ({_local(s['time'], tz_name)})",
        f"Тренд: {tg.esc(s['trend'])} · ADX {s['adx']:.0f} · RSI {s['rsi']:.0f}",
        f"ATR: {_dist(s['atr'], d)} ({s['atr_pct']:.2f}%)",
        f"Канал {chan} бар: {chan_lo:.{d}f} … {chan_hi:.{d}f}",
    ]

    lv = msnr_levels(df)
    if lv:
        parts = []
        if lv.get("nearest_support"):
            z = lv["nearest_support"]
            parts.append(f"поддержка {z.bottom:.{d}f}–{z.top:.{d}f}")
        if lv.get("nearest_resistance"):
            z = lv["nearest_resistance"]
            parts.append(f"сопротивление {z.bottom:.{d}f}–{z.top:.{d}f}")
        if parts:
            lines.append("Уровни MSNR (H4): " + " · ".join(parts))

    lines.append("")

    trade = state.get("trade")
    if trade:
        r_now = current_risk(trade, s["price"])
        lines += [
            f"🔄 <b>Открытая сделка: {'LONG' if trade['side'] == 'long' else 'SHORT'}</b>",
            f"Вход {trade['entry']:.{d}f} · стоп {trade['stop']:.{d}f} · тейк {trade['tp']:.{d}f}",
            f"Текущий результат: {r_now:+.2f}R",
        ]
    else:
        lines.append("Открытой сделки нет.")

    sig = st.signals_for(strategy, df, params)
    last = sig.iloc[-1]
    if bool(last["long_signal"]):
        lines.append("⚡ На последней свече был сигнал на покупку.")
    elif bool(last["short_signal"]):
        lines.append("⚡ На последней свече был сигнал на продажу.")
    else:
        lines.append("Сигналов на последней закрытой свече нет — ждём.")
    return "\n".join(lines)


def backtest_summary(df: pd.DataFrame, strategy: str = "breakout", params: dict | None = None,
                     spread: float = SPREAD, max_bars: int | None = None) -> dict:
    meta, _ = st.get_strategy(strategy)
    sig = st.signals_for(strategy, df, params)
    trades = bt.simulate(
        df, sig,
        bt.BtConfig(spread=spread, max_bars=int(max_bars or meta.max_bars), be_after_r=None, session=None),
    )
    s = bt.stats(trades)
    s["days"] = int((df.index[-1] - df.index[0]).days)
    s["title"] = meta.title
    return s


def format_stats(bt_stats: dict, history: list[dict], name: str, timeframe: str = "1h") -> str:
    lines = [f"📈 <b>Статистика · {tg.esc(name)} {timeframe.upper()}</b>", ""]
    if bt_stats and bt_stats["trades"]:
        lines += [
            f"<b>Бэктест (~{bt_stats['days']} дн.)</b>",
            f"<i>{tg.esc(bt_stats.get('title', name))}</i>",
            f"Сделок: {bt_stats['trades']} · побед {bt_stats['winrate']:.0f}%",
            f"Profit factor: {bt_stats['pf']:.2f}",
            f"Ожидание: {bt_stats['expectancy_r']:+.2f}R на сделку",
            f"Суммарно: {bt_stats['total_r']:+.0f}R · просадка {bt_stats['max_dd_r']:.0f}R",
            "",
        ]
    if history:
        rs = [t["r"] for t in history]
        wins = sum(1 for r in rs if r > 0)
        total = sum(rs)
        gross_win = sum(r for r in rs if r > 0)
        gross_loss = -sum(r for r in rs if r <= 0)
        pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
        equity = np.cumsum(rs)
        drawdown = float((np.maximum.accumulate(equity) - equity).max()) if len(equity) else 0.0
        lines += [
            "<b>Live-сигналы</b>",
            f"Закрыто сделок: {len(rs)} · побед {wins / len(rs) * 100:.0f}%",
            f"Profit factor: {pf:.2f}",
            f"Итог: {total:+.2f}R · макс. просадка {drawdown:.1f}R",
        ]
    else:
        lines.append("<b>Live-сигналы</b>: пока ни одной закрытой сделки.")
    return "\n".join(lines)
