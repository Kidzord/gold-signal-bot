"""Проверка «закол + BOS» на золоте и парах, с фильтром закола и без."""
from __future__ import annotations

import itertools
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import backtest as bt
import indicators
import market
import sweep_bos

pd.set_option("display.width", 230)

ASSETS = [
    ("GC=F", "XAUUSD", 0.30),
    ("EURUSD=X", "EURUSD", 0.00012),
    ("GBPUSD=X", "GBPUSD", 0.00015),
]


def folds_min(df, sig, cfg, k=4) -> float:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
        for i in range(k)
    )


def main() -> None:
    rows = []
    for symbol, name, spread in ASSETS:
        h1 = market.closed_bars(market.get_history(symbol, "1h", "730d", max_age_seconds=600), "1h")
        for tf, frame in (("H1", h1), ("H4", market.resample_bars(h1, "4h"))):
            df = indicators.enrich(frame).dropna(subset=["ema200", "atr", "adx", "atr_median"])
            for strength, rr, req in itertools.product((3, 5), (2.0, 3.0), (True, False)):
                sig = sweep_bos.sweep_bos_signals(df, strength=strength, rr=rr, require_sweep=req)
                if not (sig.long_signal.any() or sig.short_signal.any()):
                    continue
                cfg = bt.BtConfig(spread=spread, max_bars=48 if tf == "H1" else 30,
                                  be_after_r=None, session=None, tp_r=rr)
                s = bt.stats(bt.simulate(df, sig, cfg))
                if s["trades"] < 40:
                    continue
                rows.append({
                    "pair": name, "tf": tf, "k": strength, "rr": rr,
                    "sweep": "да" if req else "нет",
                    "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                    "exp": round(s["expectancy_r"], 3), "dd": round(s["max_dd_r"], 1),
                    "fold_min": round(folds_min(df, sig, cfg), 3),
                })
    res = pd.DataFrame(rows).sort_values(["pair", "tf", "exp"], ascending=[True, True, False])
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
