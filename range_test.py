"""Проверка диапазонной идеи («ЛП от границы диапазона») на золоте H1."""
from __future__ import annotations

import itertools

import pandas as pd

import backtest as bt
import indicators
import market
import ranges
import strategy as st

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 40)


def folds_min(df, sig, cfg, k=4) -> float:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
        for i in range(k)
    )


def main() -> None:
    raw = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])

    cfg = bt.BtConfig(spread=0.30, max_bars=72, be_after_r=None, session=None)
    base = bt.stats(bt.simulate(df, st.breakout(df), cfg))
    print(f"БАЗА (пробой канала): {base['trades']} сделок · {base['winrate']:.0f}% · "
          f"PF {base['pf']:.2f} · {base['expectancy_r']:+.3f}R\n")

    rows = []
    for n, adx_max, stop_atr, target in itertools.product(
        (24, 48, 72), (20, 25), (0.5, 0.8), ("edge", "ext")
    ):
        sig = ranges.range_signals(df, n=n, adx_max=adx_max, stop_atr=stop_atr, target=target)
        if not (sig.long_signal.any() or sig.short_signal.any()):
            continue
        tr = bt.simulate(df, sig, cfg)
        s = bt.stats(tr)
        if s["trades"] < 40:
            continue
        rows.append({
            "n": n, "adx": adx_max, "stop": stop_atr, "target": target,
            "n_tr": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
            "exp": round(s["expectancy_r"], 3), "total": round(s["total_r"], 1),
            "dd": round(s["max_dd_r"], 1), "per_month": round(s["trades_per_month"], 1),
            "fold_min": round(folds_min(df, sig, cfg), 3),
        })

    res = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print(res.to_string(index=False))

    if not res.empty:
        best = res.iloc[0]
        print(f"\nЛучший: n={best['n']} adx<{best['adx']} stop={best['stop']} target={best['target']} → "
              f"{best['n_tr']} сделок, {best['wr']}% побед, PF {best['pf']}, {best['exp']:+.3f}R")
    res.to_csv("cache/range_results.csv", index=False)


if __name__ == "__main__":
    main()
