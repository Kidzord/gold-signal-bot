"""Включает параллельный режим у золота: breakout + asian на одном инструменте."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import storage

CFG = storage.Config()
items = CFG.data.get("instruments") or []
changed = False
for item in items:
    if item.get("key") == "gold":
        item["strategies"] = ["breakout", "asian"]
        changed = True
if changed:
    CFG.data["instruments"] = items
    CFG.save()
    print("gold: включены breakout + asian")
for i in items:
    slots = i.get("strategies") or [i.get("strategy")]
    print(f"  {i['key']:8s} {i['symbol']:9s} {i['timeframe']:3s} {', '.join(slots)}")
