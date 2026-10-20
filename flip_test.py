"""Проверка Flipped SNR на золоте (H1 и H4)."""
from __future__ import annotations

import itertools
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import backtest as bt
import flip
import indicators
import market

pd.set_option("display.width", 220)


def folds_min(df, sig, cfg, k=4) -> float:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
        for i in range(k)
    )


def main() -> None:
    raw = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    h1 = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median"])
    h4 = indicators.enrich(market.resample_bars(raw, "4h")).dropna(subset=["ema200", "atr", "adx", "atr_median"])

    rows = []
    for tf, df in (("H1", h1), ("H4", h4)):
        for buf, stop, rr in itertools.product((0.05, 0.1, 0.2), (0.8, 1.2), (1.5, 2.0)):
            sig = flip.flip_signals(df, buffer_atr=buf, stop_atr=stop, rr=rr)
            if not (sig.long_signal.any() or sig.short_signal.any()):
                continue
            cfg = bt.BtConfig(spread=0.30, max_bars=72, be_after_r=None, session=None, tp_r=rr)
            s = bt.stats(bt.simulate(df, sig, cfg))
            if s["trades"] < 40:
                continue
            rows.append({
                "tf": tf, "buf": buf, "stop": stop, "rr": rr, "n": s["trades"],
                "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                "exp": round(s["expectancy_r"], 3), "dd": round(s["max_dd_r"], 1),
                "fold_min": round(folds_min(df, sig, cfg), 3),
            })
    res = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
