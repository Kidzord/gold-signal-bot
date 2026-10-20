"""Валидация сетапа «азиатский диапазон» на золоте."""
from __future__ import annotations

import itertools
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

import asian
import backtest as bt
import indicators
import market

pd.set_option("display.width", 220)


def folds(df, sig, cfg, k=4) -> list[float]:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return [bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
            for i in range(k)]


def main() -> None:
    raw = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median"])

    cfg = bt.BtConfig(spread=0.30, max_bars=72, be_after_r=None, session=None, tp_r=2.0)
    sig = asian.asian_range_signals(df, start=1, end=7, entry_from=7, entry_to=16, buffer_atr=0.3, rr=2.0)
    tr = bt.simulate(df, sig, cfg)
    s = bt.stats(tr)
    print(f"БАЗОВАЯ КОНФИГУРАЦИЯ: {s['trades']} сделок · {s['winrate']:.1f}% · PF {s['pf']:.2f} · "
          f"{s['expectancy_r']:+.3f}R · DD {s['max_dd_r']:.1f}R · {s['trades_per_month']:.1f}/мес")
    print(f"  фолды: {[round(x, 3) for x in folds(df, sig, cfg)]}")

    tr2 = tr.copy()
    tr2["year"] = pd.to_datetime(tr2["entry_time"]).dt.year
    print("  по годам:", {int(y): (round(g["r"].mean(), 2), len(g)) for y, g in tr2.groupby("year")})
    print("  по сторонам:", {k: (round(v["r"].mean(), 2), len(v)) for k, v in tr.groupby("side")})

    print("\nИздержки:", end=" ")
    for sp in (0.30, 0.50, 0.80, 1.20):
        ss = bt.stats(bt.simulate(df, sig, bt.BtConfig(spread=sp, max_bars=72, be_after_r=None, session=None, tp_r=2.0)))
        print(f"{sp:.1f}$={ss['expectancy_r']:+.3f}R", end="  ")
    print()

    print("\nСетка (буфер × RR × окно входа):")
    rows = []
    for buf, rr, to in itertools.product((0.2, 0.3, 0.4), (1.5, 2.0, 2.5), (14, 16, 18)):
        sg = asian.asian_range_signals(df, start=1, end=7, entry_from=7, entry_to=to, buffer_atr=buf, rr=rr)
        c = bt.BtConfig(spread=0.30, max_bars=72, be_after_r=None, session=None, tp_r=rr)
        st = bt.stats(bt.simulate(df, sg, c))
        if st["trades"] < 60:
            continue
        rows.append({"buf": buf, "rr": rr, "to": to, "n": st["trades"], "wr": round(st["winrate"], 1),
                     "pf": round(st["pf"], 2), "exp": round(st["expectancy_r"], 3),
                     "dd": round(st["max_dd_r"], 1), "fold_min": round(min(folds(df, sg, c)), 3)})
    grid = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print(grid.to_string(index=False))

    print("\nЛимит удержания:", end=" ")
    for bars in (24, 48, 72, 120):
        c = bt.BtConfig(spread=0.30, max_bars=bars, be_after_r=None, session=None, tp_r=2.0)
        ss = bt.stats(bt.simulate(df, sig, c))
        print(f"{bars}бар={ss['expectancy_r']:+.3f}R", end="  ")
    print()

    r = tr["r"].to_numpy()
    rng = np.random.default_rng(7)
    boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(5000)])
    print(f"Бутстрэп: 5% {np.percentile(boots, 5):+.1f}R · 50% {np.percentile(boots, 50):+.1f}R · "
          f"95% {np.percentile(boots, 95):+.1f}R · доля>0 {(boots > 0).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()
