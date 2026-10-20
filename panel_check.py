"""Проверка вида панели на реальных данных (без сканирования и без сделок)."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import analysis
import web
from bot import Bot

bot = Bot()
items = []
for inst in bot.instruments:
    df = analysis.load_frame(inst.symbol, timeframe=inst.timeframe)
    item = bot._instrument_snapshot(inst, df)
    items.append(item)
    print(f"{inst.name:8s} {item['price']:.{inst.digits}f} · тренд {item['trend']} · "
          f"баров ок · риск {item['risk']}")

snapshot = {
    "updated": analysis._local(__import__("datetime").datetime.now(__import__("datetime").timezone.utc), bot.tz),
    "subscribers": len(bot.state.subscribers),
    "username": "Kidzord_bot",
    "instruments": items,
}
html = web.render_page(snapshot)
open("cache/panel_preview.html", "w", encoding="utf-8").write(html)
print(f"\nHTML: {len(html)} символов -> cache/panel_preview.html")
