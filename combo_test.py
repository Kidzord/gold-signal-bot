"""Связка breakout + SMT: даёт ли подтверждение расхождением прирост к базе?"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

import backtest as bt
import indicators
import market
import smt
import strategy as st

pd.set_option("display.width", 200)

GOLD, SILVER, SPREAD = "GC=F", "SI=F", 0.30


def folds_min(df: pd.DataFrame, sig: pd.DataFrame, cfg: bt.BtConfig, k: int = 4) -> float:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
        for i in range(k)
    )


def recent(flags, window: int) -> np.ndarray:
    """Был ли флаг хотя бы раз за последние `window` баров (включая текущий)."""
    s = pd.Series(np.asarray(flags, dtype=float))
    return s.rolling(window, min_periods=1).max().fillna(0).to_numpy() > 0


def main() -> None:
    gold_raw = market.closed_bars(market.get_history(GOLD, "1h", "730d", max_age_seconds=600), "1h")
    silver = market.closed_bars(market.get_history(SILVER, "1h", "730d", max_age_seconds=600), "1h")
    gold = indicators.enrich(gold_raw).dropna(subset=["ema200", "atr", "adx", "atr_median"])
    print(f"золото H1: {len(gold)} баров, серебро H1: {len(silver)} баров")

    base = st.breakout(gold)
    base_long = base["long_signal"].to_numpy(bool)
    base_short = base["short_signal"].to_numpy(bool)

    smt_sig = smt.smt_signals(gold, silver, k=2, stop_atr=1.5, rr=2.0)
    smt_long = smt_sig["long_signal"].to_numpy(bool)
    smt_short = smt_sig["short_signal"].to_numpy(bool)

    def cfg() -> bt.BtConfig:
        return bt.BtConfig(spread=SPREAD, max_bars=48, be_after_r=None, session=None)

    def variant(long_, short_) -> pd.DataFrame:
        out = base.copy()
        out["long_signal"] = base_long & np.asarray(long_)
        out["short_signal"] = base_short & np.asarray(short_)
        return out

    def smt_variant(long_, short_) -> pd.DataFrame:
        out = smt_sig.copy()
        out["rr"] = 2.0
        out["long_signal"] = smt_long & np.asarray(long_)
        out["short_signal"] = smt_short & np.asarray(short_)
        return out

    rows: list[dict] = []

    def add(name: str, sig: pd.DataFrame) -> None:
        s = bt.stats(bt.simulate(gold, sig, cfg()))
        rows.append({
            "вариант": name, "n": s["trades"], "wr": round(s["winrate"], 1),
            "pf": round(s["pf"], 2), "exp": round(s["expectancy_r"], 3),
            "tot": round(s["total_r"], 1), "dd": round(s["max_dd_r"], 1),
            "fold_min": round(folds_min(gold, sig, cfg()), 3),
        })

    add("breakout (база)", base)
    for n in (12, 24, 48):
        add(f"breakout + SMT-конфлюенс ≤{n} бар", variant(recent(smt_long, n), recent(smt_short, n)))
    for n in (12, 24, 48):
        add(f"breakout, вето при встречном SMT ≤{n} бар", variant(~recent(smt_short, n), ~recent(smt_long, n)))
    add("SMT + подтверждение breakout ≤24 бар",
        smt_variant(recent(base_long, 24), recent(base_short, 24)))

    res = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print("\n=== breakout + SMT (золото H1) ===")
    print(res.to_string(index=False))
    res.to_csv("cache/combo_results.csv", index=False)


if __name__ == "__main__":
    main()
