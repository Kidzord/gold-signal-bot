"""Детальная валидация FVG-сетапа: фолды, годы, стороны, бутстрэп."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

import backtest as bt
import fvg
import indicators
import market

pd.set_option("display.width", 200)


def main() -> None:
    h1 = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    for tf, frame, bars in (("H1", h1, 48), ("H4", market.resample_bars(h1, "4h"), 30)):
        df = indicators.enrich(frame).dropna(subset=["ema200", "atr", "adx", "atr_median"])
        sig = fvg.fvg_signals(df, mode="confirm", min_gap_atr=0.25, rr=3.0)
        cfg = bt.BtConfig(spread=0.30, max_bars=bars, be_after_r=None, session=None, tp_r=3.0)
        tr = bt.simulate(df, sig, cfg)
        s = bt.stats(tr)
        print(f"\nXAUUSD {tf}: {s['trades']} сделок · {s['winrate']:.1f}% · PF {s['pf']:.2f} · "
              f"{s['expectancy_r']:+.3f}R · DD {s['max_dd_r']:.1f}R")

        edges = [int(len(df) * i / 4) for i in range(5)]
        folds = [round(bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]],
                                           sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"], 2)
                 for i in range(4)]
        print("  фолды:", folds)

        tr2 = tr.copy()
        tr2["year"] = pd.to_datetime(tr2["entry_time"]).dt.year
        print("  по годам:", {int(y): (round(g["r"].mean(), 2), len(g)) for y, g in tr2.groupby("year")})
        print("  по сторонам:", {k: (round(v["r"].mean(), 2), len(v)) for k, v in tr.groupby("side")})

        r = tr["r"].to_numpy()
        rng = np.random.default_rng(7)
        boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(3000)])
        print(f"  бутстрэп: 5% {np.percentile(boots, 5):+.1f}R · 50% {np.percentile(boots, 50):+.1f}R · "
              f"95% {np.percentile(boots, 95):+.1f}R · доля>0 {(boots > 0).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()
