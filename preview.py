"""Локальный предпросмотр сообщений бота — без Telegram и без токена."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import analysis
import storage


def main() -> None:
    config = storage.Config()
    name = config.get("display_name", "XAUUSD")
    tz = config.get("display_tz", "Europe/Minsk")
    strategy = config.get("strategy", "breakout")

    df = analysis.load_frame(config.get("symbol", "GC=F"))
    state = {"trade": None}

    print("=" * 70)
    print("ДАННЫЕ")
    print("=" * 70)
    print(f"Баров: {len(df)} | {df.index[0]} .. {df.index[-1]}")
    s = analysis.market_state(df)
    print(f"Цена {s['price']:.2f} | ATR {s['atr']:.2f} | ADX {s['adx']:.0f} | тренд {s['trend']}")
    print("\nПоследние 5 закрытых свечей:")
    print(df[["open", "high", "low", "close", "atr", "adx"]].tail(5).round(2).to_string())

    print("\n" + "=" * 70)
    print("СООБЩЕНИЕ /signal")
    print("=" * 70)
    print(analysis.format_state(df, state, name, tz, strategy))

    signal = analysis.detect_signal(df, strategy)

    print("\n" + "=" * 70)
    print("СООБЩЕНИЕ СИГНАЛА (реальный, если есть на последней свече)")
    print("=" * 70)
    if signal:
        print(analysis.format_signal(signal, name, tz))
    else:
        print("Сейчас сигнала нет. Образец формата:")
        sample = {
            "side": "long", "entry": s["price"], "stop": s["price"] - 1.5 * s["atr"],
            "tp": s["price"] + 3.0 * s["atr"], "risk": 1.5 * s["atr"], "rr": 2.0,
            "atr": s["atr"], "adx": s["adx"], "trend": s["trend"],
            "reason": "пробой максимума 24ч, восходящий тренд (цена и EMA50 выше EMA200), "
                      "волатильность выше нормы",
            "bar_time": df.index[-1],
        }
        print(analysis.format_signal(sample, name, tz))

    trade = signal or {
        "side": "long", "entry": s["price"] - 4 * s["atr"], "stop": s["price"] - 6.5 * s["atr"],
        "tp": s["price"] - 4 * s["atr"] + 2 * 1.5 * s["atr"], "risk": 1.5 * s["atr"], "rr": 2.0,
        "bar_time": df.index[-3], "atr": s["atr"], "adx": s["adx"], "trend": s["trend"],
        "reason": "пример", "status": "open",
    }
    result = {
        "exit": trade["tp"], "reason": "TP", "exit_time": df.index[-1].isoformat(),
        "bars": 7, "pnl_usd": trade["tp"] - trade["entry"] - 0.3,
        "r": (trade["tp"] - trade["entry"] - 0.3) / trade["risk"],
    }
    print("\n" + "=" * 70)
    print("СООБЩЕНИЕ О ЗАКРЫТИИ СДЕЛКИ")
    print("=" * 70)
    print(analysis.format_close(trade, result, name, tz))

    print("\n" + "=" * 70)
    print("СТАТИСТИКА")
    print("=" * 70)
    stats = analysis.backtest_summary(df, strategy)
    print(analysis.format_stats(stats, [], name))


if __name__ == "__main__":
    main()
