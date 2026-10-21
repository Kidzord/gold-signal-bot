"""Проверка SMT-дивергенции «золото против серебра» (H1 и H4)."""
from __future__ import annotations

import itertools
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import backtest as bt
import indicators
import market
import smt

pd.set_option("display.width", 240)

GOLD, SILVER, SPREAD = "GC=F", "SI=F", 0.30


def folds_min(df: pd.DataFrame, sig: pd.DataFrame, cfg: bt.BtConfig, k: int = 4) -> float:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
        for i in range(k)
    )


def main() -> None:
    gold_h1 = market.closed_bars(market.get_history(GOLD, "1h", "730d", max_age_seconds=600), "1h")
    silver_h1 = market.closed_bars(market.get_history(SILVER, "1h", "730d", max_age_seconds=600), "1h")
    print(f"золото H1: {len(gold_h1)} баров, серебро H1: {len(silver_h1)} баров, "
          f"пересечение: {len(gold_h1.index.intersection(silver_h1.index))}")

    rows = []
    for tf in ("H1", "H4"):
        if tf == "H1":
            g_raw, s_raw = gold_h1, silver_h1
        else:
            g_raw = market.resample_bars(gold_h1, "4h")
            s_raw = market.resample_bars(silver_h1, "4h")
        gold = indicators.enrich(g_raw).dropna(subset=["ema200", "atr", "adx", "atr_median"])
        silver = s_raw.dropna(subset=["high", "low"])

        for k, rr, session, trend, mss in itertools.product(
            (2, 3), (2.0, 3.0), (None, (7, 20)), (False, True), (False, True)
        ):
            sig = smt.smt_signals(gold, silver, k=k, stop_atr=1.5, rr=rr,
                                  trend_filter=trend, require_mss=mss)
            if not (sig["long_signal"].any() or sig["short_signal"].any()):
                continue
            cfg = bt.BtConfig(spread=SPREAD, max_bars=48 if tf == "H1" else 30,
                              be_after_r=None, session=session, tp_r=rr)
            s = bt.stats(bt.simulate(gold, sig, cfg))
            if s["trades"] < 30:
                continue
            rows.append({
                "tf": tf, "k": k, "rr": rr,
                "sess": "все" if session is None else f"{session[0]}-{session[1]}",
                "trend": int(trend), "mss": int(mss),
                "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                "exp": round(s["expectancy_r"], 3), "tot": round(s["total_r"], 1),
                "dd": round(s["max_dd_r"], 1),
                "fold_min": round(folds_min(gold, sig, cfg), 3),
            })

    res = pd.DataFrame(rows).sort_values(["tf", "exp"], ascending=[True, False])
    print("\n=== SMT (золото/серебро) ===")
    print(res.to_string(index=False))
    res.to_csv("cache/smt_results.csv", index=False)

    # ориентир: рабочая стратегия бота на том же золоте H1
    base = indicators.enrich(gold_h1).dropna(subset=["ema200", "atr", "adx", "atr_median"])
    import strategy
    bsig = strategy.breakout(base)
    bcfg = bt.BtConfig(spread=SPREAD, max_bars=48, be_after_r=None, session=None)
    bs = bt.stats(bt.simulate(base, bsig, bcfg))
    print("\n=== ориентир: breakout на золоте H1 ===")
    print(f"n={bs['trades']} wr={bs['winrate']:.1f}% pf={bs['pf']:.2f} "
          f"exp={bs['expectancy_r']:+.3f}R tot={bs['total_r']:+.1f}R dd={bs['max_dd_r']:.1f}R")


if __name__ == "__main__":
    main()
