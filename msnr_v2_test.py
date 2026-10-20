"""Проверка MSNR v2 (спецификация LuxAlgo) на золоте H1: сетка по минимальному RR."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

import backtest as bt
import indicators
import market
import msnr_v2
import strategy as st

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 40)

CFG = bt.BtConfig(spread=0.30, max_bars=48, be_after_r=None, session=None)


def folds_min(df, sig, cfg, k=4) -> float:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
        for i in range(k)
    )


def main() -> None:
    raw = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])

    base = bt.stats(bt.simulate(df, st.breakout(df), CFG))
    v1 = bt.stats(bt.simulate(df, st.msnr_break(df), CFG))
    print(f"База пробой канала: {base['trades']} сделок · PF {base['pf']:.2f} · {base['expectancy_r']:+.3f}R")
    print(f"MSNR v1:            {v1['trades']} сделок · PF {v1['pf']:.2f} · {v1['expectancy_r']:+.3f}R\n")

    level_cache = {(t, c): msnr_v2.build_levels(df, turn=t, max_body_crosses=c)
                   for t, c in itertools.product((3, 5), (3,))}
    story = msnr_v2.storyline_direction(df, turn=5)
    flat = np.array(["flat"] * len(df), dtype=object)

    rows = []
    for turn, use_story, min_r, fb in itertools.product((3, 5), (True, False), (0.0, 1.5, 2.5, 4.0), (3.0, 5.0)):
        sig = msnr_v2.msnr_v2_signals(
            df, turn=turn, max_body_crosses=3, min_reward_r=min_r, fallback_r=fb,
            use_storyline=use_story, fresh_only=True,
            levels=level_cache[(turn, 3)], story=story if use_story else flat,
        )
        if not (sig.long_signal.any() or sig.short_signal.any()):
            continue
        s = bt.stats(bt.simulate(df, sig, CFG))
        if s["trades"] < 40:
            continue
        rows.append({
            "turn": turn, "story": use_story, "minR": min_r, "fallback": fb,
            "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
            "exp": round(s["expectancy_r"], 3), "total": round(s["total_r"], 1),
            "dd": round(s["max_dd_r"], 1), "per_month": round(s["trades_per_month"], 1),
            "fold_min": round(folds_min(df, sig, CFG), 3),
        })

    res = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print(res.to_string(index=False))
    res.to_csv("cache/msnr_v2_results.csv", index=False)


if __name__ == "__main__":
    main()
