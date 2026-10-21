"""Добавляет инструмент gold4h (Flipped SNR на H4) в config.json."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import storage

CFG = storage.Config()
items = CFG.data.get("instruments") or []
keys = {i.get("key") for i in items}
if "gold4h" in keys:
    print("gold4h уже есть")
else:
    items.append({
        "key": "gold4h",
        "symbol": "GC=F",
        "name": "XAUUSD",
        "timeframe": "4h",
        "strategy": "flip",
        "params": {},
        "spread": 0.30,
        "max_bars": 72,
        "pip": 1.0,
    })
    CFG.data["instruments"] = items
    CFG.save()
    print("добавлен gold4h")
for i in CFG.data["instruments"]:
    print(f"  {i['key']:8s} {i['symbol']:9s} {i['timeframe']:3s} {i['strategy']}")
