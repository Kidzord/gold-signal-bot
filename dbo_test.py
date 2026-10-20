"""Проверка MSnR Double Breakout Level (RWBTradeLab) на золоте H1."""
from __future__ import annotations

import itertools

import pandas as pd

import backtest as bt
import dbo
import indicators
import market
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

    events = dbo.find_events(df)
    dbo._upgrade_events(events)
    print(f"Событий DBO: {len(events)} (A {sum(e.side == 'A' for e in events)}, "
          f"V {sum(e.side == 'V' for e in events)}, апгрейдов {sum(e.upgraded for e in events)})")

    cfg = bt.BtConfig(spread=0.30, max_bars=48, be_after_r=None, session=None)
    base = bt.stats(bt.simulate(df, st.breakout(df), cfg))
    print(f"База пробой канала: {base['trades']} сделок · PF {base['pf']:.2f} · {base['expectancy_r']:+.3f}R\n")

    rows = []
    for mode, window, tol, rr, upg in itertools.product(
        ("retest", "breakout"), (6, 12, 24), (0.15, 0.3), (2.0, 3.0), (False, True)
    ):
        if mode == "breakout" and (window != 6 or tol != 0.15):
            continue
        cfg_rr = bt.BtConfig(spread=0.30, max_bars=48, be_after_r=None, session=None, tp_r=rr)
        sig = dbo.dbo_signals(df, mode=mode, window=window, tol_atr=tol, rr=rr, upgraded_only=upg)
        if not (sig.long_signal.any() or sig.short_signal.any()):
            continue
        s = bt.stats(bt.simulate(df, sig, cfg_rr))
        if s["trades"] < 40:
            continue
        rows.append({
            "mode": mode, "window": window, "tol": tol, "rr": rr, "upgraded": upg,
            "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
            "exp": round(s["expectancy_r"], 3), "total": round(s["total_r"], 1),
            "dd": round(s["max_dd_r"], 1), "per_month": round(s["trades_per_month"], 1),
            "fold_min": round(folds_min(df, sig, cfg_rr), 3),
        })

    res = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print(res.to_string(index=False))
    res.to_csv("cache/dbo_results.csv", index=False)


if __name__ == "__main__":
    main()
