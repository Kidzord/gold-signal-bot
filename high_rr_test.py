"""Проверка идеи «высокий RR» (5–10R), как в MSNR-канале, на наших стратегиях."""
from __future__ import annotations

import itertools

import pandas as pd

import backtest as bt
import indicators
import market
import strategy as st

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 40)


def folds_min(df, sig, cfg) -> float:
    edges = [int(len(df) * k / 4) for k in range(5)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[k]:edges[k + 1]], sig.iloc[edges[k]:edges[k + 1]], cfg))["expectancy_r"]
        for k in range(4)
    )


def main() -> None:
    raw = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])

    sigs = {"breakout": st.breakout(df), "msnr": st.msnr_break(df)}
    base = bt.BtConfig(spread=0.30, max_bars=48, be_after_r=None, session=None)
    for name, sig in sigs.items():
        s = bt.stats(bt.simulate(df, sig, base))
        print(f"база {name}: {s['trades']} сделок · {s['winrate']:.0f}% · PF {s['pf']:.2f} · {s['expectancy_r']:+.3f}R")

    rows = []
    for name, sig in sigs.items():
        for stop, rr, bars, be, trail in itertools.product(
            (1.0, 1.5), (3.0, 5.0, 8.0), (120, 240), (None, 1.0), (None, 3.0)
        ):
            cfg = bt.BtConfig(spread=0.30, max_bars=bars, be_after_r=be, session=None,
                              trail_atr=trail, tp_r=rr)
            tr = bt.simulate(df, sig, cfg)
            s = bt.stats(tr)
            if s["trades"] < 40:
                continue
            rows.append({
                "strategy": name, "stop": stop, "rr": rr, "bars": bars,
                "be": be, "trail": trail, "n": s["trades"],
                "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                "exp": round(s["expectancy_r"], 3), "total": round(s["total_r"], 1),
                "dd": round(s["max_dd_r"], 1),
                "fold_min": round(folds_min(df, sig, cfg), 3),
            })

    res = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print("\nТОП-15 по ожиданию (высокий RR):")
    print(res.head(15).to_string(index=False))
    res.to_csv("cache/high_rr.csv", index=False)

    print("\nЛучший в каждой стратегии:")
    best = res.groupby("strategy", group_keys=False).head(1)
    print(best.to_string(index=False))


if __name__ == "__main__":
    main()
