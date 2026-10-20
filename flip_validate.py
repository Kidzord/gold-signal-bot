"""Валидация Flipped SNR: фолды, годы, стороны, издержки, бутстрэп, другие активы."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

import backtest as bt
import flip
import indicators
import market

pd.set_option("display.width", 220)

ASSETS = [
    ("GC=F", "XAUUSD", 0.30),
    ("EURUSD=X", "EURUSD", 0.00012),
    ("GBPUSD=X", "GBPUSD", 0.00015),
]


def folds(df, sig, cfg, k=4) -> list[float]:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return [bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
            for i in range(k)]


def load(symbol: str) -> pd.DataFrame:
    h1 = market.closed_bars(market.get_history(symbol, "1h", "730d", max_age_seconds=600), "1h")
    h4 = market.resample_bars(h1, "4h")
    return indicators.enrich(h4).dropna(subset=["ema200", "atr", "adx", "atr_median"])


def main() -> None:
    for symbol, name, spread in ASSETS:
        df = load(symbol)
        best = None
        for buf, stop in ((0.1, 1.2), (0.2, 0.8)):
            sig = flip.flip_signals(df, buffer_atr=buf, stop_atr=stop, rr=2.0)
            cfg = bt.BtConfig(spread=spread, max_bars=72, be_after_r=None, session=None, tp_r=2.0)
            s = bt.stats(bt.simulate(df, sig, cfg))
            if best is None or s["expectancy_r"] > best[0]:
                best = (s["expectancy_r"], buf, stop, sig, cfg, s)
        _, buf, stop, sig, cfg, s = best
        print(f"\n{'=' * 72}\n{name} H4 · buf {buf} · стоп {stop} ATR: {s['trades']} сделок · "
              f"{s['winrate']:.1f}% · PF {s['pf']:.2f} · {s['expectancy_r']:+.3f}R · DD {s['max_dd_r']:.1f}R")
        print(f"  фолды: {[round(x, 2) for x in folds(df, sig, cfg)]}")

        tr = bt.simulate(df, sig, cfg)
        tr["year"] = pd.to_datetime(tr["entry_time"]).dt.year
        print("  по годам:", {int(y): (round(g["r"].mean(), 2), len(g)) for y, g in tr.groupby("year")})
        print("  по сторонам:", {k: (round(v["r"].mean(), 2), len(v)) for k, v in tr.groupby("side")})

        print("  издержки:", end=" ")
        for mult in (1.0, 2.0, 4.0):
            ss = bt.stats(bt.simulate(df, sig, bt.BtConfig(spread=spread * mult, max_bars=72,
                                                          be_after_r=None, session=None, tp_r=2.0)))
            print(f"x{mult:g}={ss['expectancy_r']:+.2f}R", end="  ")
        print()

        print("  удержание:", end=" ")
        for bars in (24, 48, 72, 120):
            ss = bt.stats(bt.simulate(df, sig, bt.BtConfig(spread=spread, max_bars=bars,
                                                          be_after_r=None, session=None, tp_r=2.0)))
            print(f"{bars}б={ss['expectancy_r']:+.2f}R", end="  ")
        print()

        r = tr["r"].to_numpy()
        rng = np.random.default_rng(7)
        boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(4000)])
        print(f"  бутстрэп: 5% {np.percentile(boots, 5):+.1f}R · 50% {np.percentile(boots, 50):+.1f}R · "
              f"95% {np.percentile(boots, 95):+.1f}R · доля>0 {(boots > 0).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()
