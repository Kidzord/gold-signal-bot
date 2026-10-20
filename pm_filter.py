"""Фильтр премиум/дисконт для flip: покупаем только в нижней половине диапазона."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import backtest as bt
import flip
import indicators
import market

pd.set_option("display.width", 200)


def main() -> None:
    h1 = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    df = indicators.enrich(market.resample_bars(h1, "4h")).dropna(subset=["ema200", "atr", "adx", "atr_median"])
    cfg = bt.BtConfig(spread=0.30, max_bars=72, be_after_r=None, session=None, tp_r=2.0)
    base = flip.flip_signals(df, buffer_atr=0.2, stop_atr=0.8, rr=2.0)
    s0 = bt.stats(bt.simulate(df, base, cfg))
    print(f"база flip: {s0['trades']} сделок · {s0['winrate']:.1f}% · PF {s0['pf']:.2f} · "
          f"{s0['expectancy_r']:+.3f}R · DD {s0['max_dd_r']:.1f}R")

    for look in (30, 50, 100):
        hi = df["high"].rolling(look).max().shift(1)
        lo = df["low"].rolling(look).min().shift(1)
        pos = (df["close"] - lo) / (hi - lo)
        for cut in (0.5, 0.4, 0.6):
            sig = base.copy()
            sig.loc[pos >= cut, "long_signal"] = False   # лонг только в дисконте
            sig.loc[pos <= 1 - cut, "short_signal"] = False  # шорт только в премиуме
            s = bt.stats(bt.simulate(df, sig, cfg))
            if s["trades"] < 20:
                continue
            print(f"  look {look:3d} · cut {cut:.1f}: {s['trades']:3d} сделок · {s['winrate']:4.1f}% · "
                  f"PF {s['pf']:.2f} · {s['expectancy_r']:+.3f}R · DD {s['max_dd_r']:.1f}R")


if __name__ == "__main__":
    main()
