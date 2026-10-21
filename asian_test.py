"""Проверка сетапа «азиатский диапазон» на золоте и форексе (H1)."""
from __future__ import annotations

import itertools
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import asian
import backtest as bt
import indicators
import market

pd.set_option("display.width", 230)

PAIRS = [
    ("GC=F", "XAUUSD", 0.30, 1.0),
    ("EURUSD=X", "EURUSD", 0.00012, 0.0001),
    ("GBPUSD=X", "GBPUSD", 0.00015, 0.0001),
]


def folds_min(df, sig, cfg, k=4) -> float:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
        for i in range(k)
    )


def main() -> None:
    rows = []
    for symbol, name, spread, _pip in PAIRS:
        raw = market.closed_bars(market.get_history(symbol, "1h", "730d", max_age_seconds=600), "1h")
        df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median"])
        print(f"\n=== {name}: {len(df)} баров")
        for start, stop_mode, buf, rr in itertools.product((0, 1), ("range", "atr"), (0.1, 0.3), (2.0,)):
            sig = asian.asian_range_signals(
                df, start=start, end=7, entry_from=7, entry_to=16,
                buffer_atr=buf, stop_mode=stop_mode, rr=rr,
            )
            if not (sig.long_signal.any() or sig.short_signal.any()):
                continue
            cfg = bt.BtConfig(spread=spread, max_bars=72, be_after_r=None, session=None, tp_r=rr)
            s = bt.stats(bt.simulate(df, sig, cfg))
            if s["trades"] < 30:
                continue
            rows.append({
                "pair": name, "start": start, "stop": stop_mode, "buf": buf, "rr": rr,
                "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                "exp": round(s["expectancy_r"], 3), "dd": round(s["max_dd_r"], 1),
                "per_month": round(s["trades_per_month"], 1),
                "fold_min": round(folds_min(df, sig, cfg), 3),
            })
    res = pd.DataFrame(rows).sort_values(["pair", "exp"], ascending=[True, False])
    print(res.to_string(index=False))
    res.to_csv("cache/asian_results.csv", index=False)


if __name__ == "__main__":
    main()
