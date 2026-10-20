"""Проверка многoинструментного бота на реальных данных."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from bot import Bot

bot = Bot()
for inst in bot.instruments:
    text = bot._stats_text(inst)
    print(f"--- {inst.key} ---")
    print(text)
    print()

print("=== /signal (обзор) ===")
print(bot._signal_text(None))
print()
print("=== /signal eurusd ===")
print(bot._signal_text(bot.instruments[1]))
