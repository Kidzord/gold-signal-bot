"""Проверка всех наших методов на EURUSD и GBPUSD (H1, Yahoo)."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import backtest as bt
import dbo
import indicators
import market
import ranges
import strategy as st

pd.set_option("display.width", 240)

# спред в единицах цены: EURUSD ~1.2 пипса, GBPUSD ~1.5 пипса
PAIRS = {
    "EURUSD=X": {"name": "EURUSD", "spread": 0.00012, "pip": 0.0001},
    "GBPUSD=X": {"name": "GBPUSD", "spread": 0.00015, "pip": 0.0001},
}


def folds_min(df, sig, cfg, k=4) -> float:
    edges = [int(len(df) * i / k) for i in range(k + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[i]:edges[i + 1]], sig.iloc[edges[i]:edges[i + 1]], cfg))["expectancy_r"]
        for i in range(k)
    )


def main() -> None:
    rows = []
    for symbol, meta in PAIRS.items():
        raw = market.get_history(symbol, "1h", "730d", max_age_seconds=600)
        raw = market.closed_bars(raw, "1h")
        df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])
        pip = meta["pip"]
        print(f"\n=== {meta['name']}: {len(df)} баров, {df.index[0].date()} .. {df.index[-1].date()}, "
              f"цена {df['close'].iloc[-1]:.5f}, ATR {df['atr'].mean() / pip:.1f} пипсов")

        cfg48 = bt.BtConfig(spread=meta["spread"], max_bars=48, be_after_r=None, session=None)

        methods = {
            "breakout": (st.breakout(df), cfg48),
            "msnr": (st.msnr_break(df), cfg48),
            "msnr_trend": (st.msnr_trend(df), bt.BtConfig(spread=meta["spread"], max_bars=120, be_after_r=None, session=None)),
            "ranges": (ranges.range_signals(df, n=72, adx_max=25, stop_atr=1.5, target="mid"), cfg48),
            "dbo": (dbo.dbo_signals(df, mode="breakout", rr=3.0),
                    bt.BtConfig(spread=meta["spread"], max_bars=48, be_after_r=None, session=None, tp_r=3.0)),
        }

        for name, (sig, cfg) in methods.items():
            if not (sig.long_signal.any() or sig.short_signal.any()):
                print(f"  {name:11s} сигналов нет")
                continue
            s = bt.stats(bt.simulate(df, sig, cfg))
            rows.append({
                "pair": meta["name"], "method": name,
                "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                "exp": round(s["expectancy_r"], 3), "total": round(s["total_r"], 1),
                "dd": round(s["max_dd_r"], 1), "per_month": round(s["trades_per_month"], 1),
                "fold_min": round(folds_min(df, sig, cfg), 3),
            })
            print(f"  {name:11s} {s['trades']:4d} сделок · {s['winrate']:4.1f}% · PF {s['pf']:.2f} · "
                  f"exp {s['expectancy_r']:+.3f}R · DD {s['max_dd_r']:.1f}R")

    res = pd.DataFrame(rows)
    res.to_csv("cache/forex_results.csv", index=False)
    print("\n", res.to_string(index=False))


if __name__ == "__main__":
    main()
