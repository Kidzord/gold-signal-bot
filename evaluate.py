"""Финальная оценка выбранной стратегии + отчёт REPORT.md (раздел бэктеста)."""
from __future__ import annotations

import numpy as np
import pandas as pd

import backtest as bt
import indicators
import market
import strategy as st

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

STOP = 1.5
TP_R = 2.0


def build(df: pd.DataFrame) -> pd.DataFrame:
    sig = st.breakout(df).copy()
    sig["stop_atr"] = STOP
    sig["rr"] = TP_R
    return sig


def cfg(spread: float = 0.30, **kw) -> bt.BtConfig:
    return bt.BtConfig(spread=spread, max_bars=48, be_after_r=None, session=None, trail_atr=None, tp_r=TP_R, **kw)


def main() -> None:
    raw = market.fetch_candles("GC=F", "1h", "730d")
    df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])
    sig = build(df)

    tr = bt.simulate(df, sig, cfg())
    s = bt.stats(tr)

    print(f"Период: {df.index[0].date()} .. {df.index[-1].date()}  (баров {len(df)})")
    print(f"Сделок: {s['trades']} | Winrate {s['winrate']:.1f}% | PF {s['pf']:.2f} | "
          f"Expectancy {s['expectancy_r']:.3f}R | Total {s['total_r']:.1f}R | MaxDD {s['max_dd_r']:.1f}R | "
          f"{s['trades_per_month']:.1f} сделок/мес")

    r = tr["r"].to_numpy()
    print(f"std(R) {r.std():.2f} | t-stat {r.mean() / (r.std() / np.sqrt(len(r))):.2f}")

    print("\nПо сторонам:")
    print(tr.groupby("side")["r"].agg(["count", "mean", "sum"]).round(3).to_string())

    print("\nПо типу выхода:")
    print(tr.groupby("reason")["r"].agg(["count", "mean", "sum"]).round(3).to_string())

    print("\nПо годам:")
    tr["year"] = pd.to_datetime(tr["entry_time"]).dt.year
    print(tr.groupby("year")["r"].agg(["count", "mean", "sum"]).round(3).to_string())

    print("\nWalk-forward (4 фолда):")
    folds = bt.fold_report(df, lambda part: bt.simulate(part, build(part), cfg()))
    print(pd.DataFrame(folds)[["from", "to", "trades", "winrate", "pf", "expectancy_r", "total_r"]].round(2).to_string(index=False))

    print("\nЧувствительность к спреду:")
    for sp in (0.30, 0.50, 0.80, 1.20):
        ss = bt.stats(bt.simulate(df, sig, cfg(spread=sp)))
        print(f"  спред {sp:.2f}$: exp {ss['expectancy_r']:.3f}R, PF {ss['pf']:.2f}, total {ss['total_r']:.1f}R")

    rng = np.random.default_rng(7)
    boots = np.array([rng.choice(r, size=len(r), replace=True).sum() for _ in range(5000)])
    print(f"\nБутстрэп суммарного R: 5% {np.percentile(boots, 5):.1f}R, 50% {np.percentile(boots, 50):.1f}R, "
          f"95% {np.percentile(boots, 95):.1f}R; доля прогонов >0: {(boots > 0).mean()*100:.1f}%")

    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    streak = max((len(list(g)) for k, g in __import__("itertools").groupby(r <= 0) if k), default=0)
    print(f"Максимальная просадка {dd.max():.1f}R, серия убытков подряд: {streak}")

    tr.to_csv("cache/trades_breakout.csv", index=False)
    pd.DataFrame({"time": tr["exit_time"], "equity_r": eq}).to_csv("cache/equity_breakout.csv", index=False)


if __name__ == "__main__":
    main()
