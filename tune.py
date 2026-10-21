"""Подбор выходов (стоп/тейк/трейлинг) для стратегий. Служебный скрипт."""
from __future__ import annotations

import itertools

import pandas as pd

import backtest as bt
import indicators
import market
import strategy as st

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)


def folds_min_expectancy(df, sig, cfg, folds=4) -> float:
    n = len(df)
    edges = [int(n * k / folds) for k in range(folds + 1)]
    vals = []
    for k in range(folds):
        part = df.iloc[edges[k]:edges[k + 1]]
        s = sig.iloc[edges[k]:edges[k + 1]]
        tr = bt.simulate(part, s, cfg)
        vals.append(bt.stats(tr)["expectancy_r"])
    return min(vals)


def main() -> None:
    df = indicators.enrich(market.fetch_candles("GC=F", "1h", "730d"))
    df = df.dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])

    exits = []
    for rr in (0.75, 1.0, 1.5, 2.0):
        exits.append(dict(label=f"tp{rr}R", tp_r=rr, trail_atr=None, be_after_r=None))
    for trail in (2.0, 3.0):
        exits.append(dict(label=f"trail{trail}", tp_r=0.0, trail_atr=trail, be_after_r=None))

    rows = []
    for key, (_meta, fn) in st.CATALOG.items():
        sig = fn(df)
        for stop_mult, ex, max_bars, sess in itertools.product(
            (0.8, 1.0, 1.2, 1.5), exits, (12, 24, 48), (None, (7, 20))
        ):
            s2 = sig.copy()
            s2["stop_atr"] = stop_mult
            cfg = bt.BtConfig(
                spread=0.30, max_bars=max_bars, session=sess,
                be_after_r=ex["be_after_r"], trail_atr=ex["trail_atr"], tp_r=ex["tp_r"],
            )
            tr = bt.simulate(df, s2, cfg)
            r = bt.stats(tr)
            if r["trades"] < 60:
                continue
            rows.append(
                {
                    "strategy": key, "stop": stop_mult, "exit": ex["label"], "bars": max_bars,
                    "sess": "all" if sess is None else "07-20",
                    "n": r["trades"], "wr": r["winrate"], "pf": r["pf"],
                    "exp": r["expectancy_r"], "total_r": r["total_r"], "dd": r["max_dd_r"],
                    "per_month": r["trades_per_month"],
                    "fold_min": folds_min_expectancy(df, s2, cfg),
                }
            )

    res = pd.DataFrame(rows).sort_values(["strategy", "exp"], ascending=[True, False])
    print(res.round(2).to_string(index=False))
    res.to_csv("cache/tune_results.csv", index=False)

    print("\n=== Лучшие по expectancy в каждой стратегии (fold_min > 0)")
    good = res[res["fold_min"] > 0].groupby("strategy", group_keys=False).head(5)
    print(good.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
