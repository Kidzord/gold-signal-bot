"""Офлайн-тесты логики бота: команды, сигналы, сопровождение сделки, формат сообщений.

Запуск: python tests.py   (Telegram и интернет не нужны)
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

import analysis
import indicators
import storage
from bot import Bot


class FakeTg:
    """Заглушка Telegram API: складывает вызовы в список."""

    def __init__(self):
        self.sent: list[tuple] = []
        self.commands = None

    def send(self, chat_id, text, preview: bool = False):
        self.sent.append((chat_id, text))
        return {"message_id": len(self.sent)}

    def set_commands(self, commands):
        self.commands = commands
        return True

    def delete_webhook(self):
        return True

    def download(self, file_id: str, dest: str) -> str:
        with open(dest, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xd9")
        return dest


def make_frame(n: int = 700) -> pd.DataFrame:
    """Монотонный аптренд: на каждом баре пробой 24-часового максимума."""
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    close = np.arange(n, dtype=float) * 1.0 + 2000.0
    noise = np.sin(np.arange(n) / 3.0) * 0.3
    close = close + noise
    open_ = np.roll(close, 1)
    open_[0] = close[0] - 0.5
    high = np.maximum(open_, close) + 0.5
    low = np.minimum(open_, close) - 0.5
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                       "volume": 100.0}, index=idx)
    return indicators.enrich(df).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not condition:
        globals()["FAILED"] = globals().get("FAILED", 0) + 1


def main() -> None:
    tmp = tempfile.mkdtemp()
    cfg = storage.Config(os.path.join(tmp, "config.json"))
    cfg.data["display_name"] = "XAUUSD"
    cfg.data["display_tz"] = "Europe/Minsk"
    st = storage.State(os.path.join(tmp, "state.json"))

    bot = Bot(cfg, st)
    bot.api = FakeTg()
    bot.me = {"username": "gold_test_bot"}

    # --- сигнал на синтетике
    df = make_frame()
    sig = analysis.detect_signal(df, "breakout")
    check("detect_signal находит лонг", sig is not None and sig["side"] == "long")
    check("стоп ниже входа, тейк выше", sig["stop"] < sig["entry"] < sig["tp"])
    check("риск = 1.5*ATR", abs(sig["risk"] - 1.5 * sig["atr"]) < 1e-6)
    check("RR = 2", abs((sig["tp"] - sig["entry"]) / sig["risk"] - 2) < 1e-6)

    # --- сопровождение: тейк
    trade = dict(sig, bar_time=df.index[-1], status="open")
    nxt = pd.DataFrame(
        {"open": [trade["entry"] + 1], "high": [trade["tp"] + 5], "low": [trade["entry"] - 1],
         "close": [trade["tp"] + 4]},
        index=[df.index[-1] + pd.Timedelta(hours=1)],
    )
    res = analysis.check_open_trade(trade, nxt)
    check("тейк фиксируется", res is not None and res["reason"] == "TP" and res["r"] > 1.9,
          f"r={res['r']:.2f}" if res else "")

    # --- сопровождение: стоп
    nxt2 = pd.DataFrame(
        {"open": [trade["entry"] - 1], "high": [trade["entry"]], "low": [trade["stop"] - 5],
         "close": [trade["stop"] - 4]},
        index=[df.index[-1] + pd.Timedelta(hours=1)],
    )
    res2 = analysis.check_open_trade(trade, nxt2)
    check("стоп фиксируется", res2 is not None and res2["reason"] == "SL" and res2["r"] < -0.9,
          f"r={res2['r']:.2f}" if res2 else "")

    # --- сопровождение: время
    bars = []
    for k in range(1, 60):
        bars.append({"open": trade["entry"], "high": trade["entry"] + 1,
                     "low": trade["entry"] - 1, "close": trade["entry"] + 0.5})
    slow = pd.DataFrame(bars, index=[df.index[-1] + pd.Timedelta(hours=k) for k in range(1, 60)])
    res3 = analysis.check_open_trade(trade, slow)
    check("выход по времени на 48-м баре", res3 is not None and res3["reason"] == "TIME" and res3["bars"] == 48,
          f"bars={res3['bars']}" if res3 else "")

    # --- команды
    reply = bot.handle_command(111, 111, "/start", "Иван")
    check("/start подписывает", 111 in st.subscribers and "Привет" in reply)
    check("/start назначает админа", st.admin_id == 111)
    check("/start повторно не дублирует", "уже подписаны" in bot.handle_command(111, 111, "/start"))

    reply = bot.handle_command(222, 222, "/help")
    check("/help отвечает справкой", "Команды" in reply)

    reply = bot.handle_command(222, 222, "/params")
    check("/params описывает стратегию", "пробой" in reply.lower())

    reply = bot.handle_command(222, 222, "/stats")
    check("/stats содержит бэктест", "Profit factor" in reply, reply.split("\n")[2] if reply else "")

    s_asian = analysis.backtest_summary(df, "asian")
    check("стратегия asian считается", isinstance(s_asian["trades"], int) and "title" in s_asian,
          f"{s_asian['trades']} сделок")

    s_flip = analysis.backtest_summary(df, "flip")
    check("стратегия flip считается", isinstance(s_flip["trades"], int),
          f"{s_flip['trades']} сделок")

    s_fvg = analysis.backtest_summary(df, "fvg")
    check("стратегия fvg считается", isinstance(s_fvg["trades"], int),
          f"{s_fvg['trades']} сделок")

    reply = bot.handle_command(222, 222, "/signal")
    check("/signal даёт обзор", "Обзор" in reply and "XAUUSD" in reply, reply.split("\n")[2] if reply else "")

    reply = bot.handle_command(222, 222, "/signal gold")
    check("/signal gold детально", "Цена" in reply and "Канал 24 бар" in reply)

    reply = bot.handle_command(222, 222, "/status")
    check("/status показывает состояние", "Состояние" in reply and "Подписчиков: 1" in reply)
    check("/status перечисляет инструменты", "XAUUSD" in reply and "GBPUSD" in reply)

    reply = bot.handle_command(222, 222, "/channel -100123")
    check("/channel закрыт для не-админа", "только для админа" in reply)

    reply = bot.handle_command(111, 111, "/channel -100123")
    check("/channel работает для админа", "-100123" in reply and st.channel_id == "-100123")

    reply = bot.handle_command(111, 111, "/unsubscribe")
    check("/unsubscribe отписывает", 111 not in st.subscribers)

    # --- переключение стратегии
    reply = bot.handle_command(222, 222, "/strategy msnr")
    check("/strategy закрыт для не-админа", "только для админа" in reply)

    reply = bot.handle_command(111, 111, "/strategy msnr")
    check("/strategy переключает на MSNR", "MSNR" in reply and bot.strategy == "msnr")
    check("/params описывает MSNR", "MSNR" in bot.handle_command(111, 111, "/params"))

    reply = bot.handle_command(111, 111, "/strategy nope")
    check("/strategy отвергает неизвестное", "Нет так" in reply)

    reply = bot.handle_command(111, 111, "/strategy breakout")
    check("/strategy возвращает пробой", "пробой" in reply.lower() or "Пробой" in reply)
    check("стратегия снова breakout", bot.strategy == "breakout")

    reply = bot.handle_command(111, 111, "/strategy msnr_trend")
    check("/strategy включает высокий RR", "MSNR" in reply and bot.strategy == "msnr_trend")
    check("/params описывает высокий RR", "высокий RR" in bot.handle_command(111, 111, "/params"))

    long_hold = dict(trade, max_bars=120)
    check("max_bars берётся из сделки", analysis.check_open_trade(long_hold, slow) is None)

    bot.handle_command(111, 111, "/strategy breakout")

    # --- сбор материалов из каналов
    import bot as bot_module

    bot_module.MATERIALS_DIR = os.path.join(tmp, "materials")
    msg = {
        "from": {"id": 111}, "chat": {"id": 111, "type": "private"},
        "message_id": 5, "date": 1760000000,
        "text": "Разбор сделки: вход 4150, стоп 4140, цель 4200",
        "photo": [{"file_id": "AAA", "width": 100}],
    }
    note = bot.save_material(msg)
    check("пересланный пост сохраняется", note is not None and "Сохранено" in note)
    check("сохранились текст и фото", len(bot._material_files()) == 2)
    check("/materials считает материалы", "Материалов: 2" in bot.handle_command(111, 111, "/materials"))
    check("не-админ не может сохранять", bot.save_material({**msg, "from": {"id": 999}}) is None)

    post = {
        "chat": {"id": -100777, "type": "channel", "title": "Тестовый канал"},
        "message_id": 6, "date": 1760000600,
        "text": "Разбор: пробой уровня, стоп за локальным минимумом",
    }
    check("пост из канала сохраняется без пересылки", bot.save_material(post) is not None)
    folder = os.path.join(bot_module.MATERIALS_DIR, "2025-10-09")
    metas = [f for f in os.listdir(folder) if f.endswith(".meta.json")]
    sources = "".join(open(os.path.join(folder, f), encoding="utf-8").read() for f in metas)
    check("источник канала записан", "Тестовый канал" in sources)

    # --- сканер: полный проход на подменённых данных
    st.add_subscriber(333)
    original_load = analysis.load_frame
    analysis.load_frame = lambda *a, **k: df
    try:
        report = bot.scan_once(notify=True)
        gold_slot = bot._slot_key(bot.instruments[0], bot.instruments[0].slots[0])
        check("сканер создал сделку", st.trade_for(gold_slot) is not None and bool(report["signals"]))
        total_slots = sum(len(i.slots) for i in bot.instruments)
        check("сигналы по всем слотам", len(report["signals"]) == total_slots,
              f"{len(report['signals'])} из {total_slots}")
        check("сигнал ушёл подписчикам", any(t[0] == 333 for t in bot.api.sent))
        sent_text = [t for t in bot.api.sent if t[0] == 333][-1][1]
        check("сообщение < 4096 символов", len(sent_text) < 4096, f"{len(sent_text)}")
        check("сообщение содержит уровни", "Вход:" in sent_text and "Стоп:" in sent_text and "Тейк:" in sent_text)

        report2 = bot.scan_once(notify=True)
        check("повторный проход без изменений молчит", not report2["signals"])
    finally:
        analysis.load_frame = original_load

    # --- риск-лимиты (после сканера, чтобы не блокировать его сигналы)
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    bad_day = {
        "side": "long", "entry": 100.0, "exit": 98.0, "r": -2.5,
        "exit_time": (now - timedelta(minutes=5)).isoformat(),
        "reason": "SL", "bars": 3, "pnl_usd": -2.0,
    }
    st._histories().setdefault(gold_slot, []).append(bad_day)
    status = bot._risk_status(bot.instruments[0])
    check("дневной лимит срабатывает", status["blocked"] is not None and status["blocked"][0] == "day",
          f"day={status['sums']['day']:+.1f}R")
    check("/risk показывает паузу", "пауза" in bot.handle_command(111, 111, "/risk"))
    check("/risk содержит лимиты", "день" in bot.handle_command(111, 111, "/risk"))

    # --- тексты
    text = analysis.format_close(trade, {"exit": trade["tp"], "reason": "TP",
                                         "exit_time": df.index[-1].isoformat(), "bars": 5,
                                         "pnl_usd": 10.0, "r": 2.0}, "XAUUSD", "Europe/Minsk")
    check("сообщение о закрытии корректно", "ТЕЙК" in text and "+2.00R" in text)

    failed = globals().get("FAILED", 0)
    print("\n" + ("ВСЕ ТЕСТЫ ПРОЙДЕНЫ" if failed == 0 else f"ПРОВАЛОВ: {failed}"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
