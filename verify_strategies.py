"""Быстрая проверка трёх стратегий через боевой пайплайн бота."""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import analysis

df = analysis.load_frame("GC=F")
for key in ("breakout", "msnr", "msnr_trend"):
    started = time.time()
    s = analysis.backtest_summary(df, key)
    print(
        f"{key:11s} {s['trades']:4d} сделок  WR {s['winrate']:4.1f}%  PF {s['pf']:.2f}  "
        f"exp {s['expectancy_r']:+.3f}R  DD {s['max_dd_r']:.1f}R  ({time.time() - started:.1f}s)"
    )

sig = analysis.detect_signal(df, "msnr")
if sig:
    print(f"сигнал msnr сейчас: {sig['side']} вход {sig['entry']:.2f} стоп {sig['stop']:.2f} тейк {sig['tp']:.2f}")
else:
    print("сигнал msnr сейчас: нет")
