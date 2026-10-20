"""Чувствительность к длине канала и спреду на EURUSD/GBPUSD."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import backtest as bt
import indicators
import market

pd.set_option("display.width", 240)

PAIRS = {"EURUSD=X": ("EURUSD", 0.0001), "GBPUSD=X": ("GBPUSD", 0.0001)}


def channel_signals(df: pd.DataFrame, n: int) -> pd.DataFrame:
    hi = df["high"].rolling(n).max().shift(1)
    lo = df["low"].rolling(n).min().shift(1)
    up = (df["close"] > df["ema200"]) & (df["ema50"] > df["ema200"])
    dn = (df["close"] < df["ema200"]) & (df["ema50"] < df["ema200"])
    vol_ok = df["atr"] > 0.8 * df["atr_median"]
    out = pd.DataFrame(index=df.index)
    out["long_signal"] = (df["close"] > hi) & up & vol_ok & (df["adx"] > 18)
    out["short_signal"] = (df["close"] < lo) & dn & vol_ok & (df["adx"] > 18)
    out["stop_atr"] = 1.5
    out["rr"] = 2.0
    out["reason"] = ""
    return out


def main() -> None:
    rows = []
    for symbol, (name, pip) in PAIRS.items():
        raw = market.closed_bars(market.get_history(symbol, "1h", "730d", max_age_seconds=600), "1h")
        df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median"])
        for n in (12, 24, 48):
            sig = channel_signals(df, n)
            for spread_pips in (0.5, 1.0, 1.5):
                cfg = bt.BtConfig(spread=spread_pips * pip, max_bars=48, be_after_r=None, session=None)
                s = bt.stats(bt.simulate(df, sig, cfg))
                rows.append({
                    "pair": name, "channel": n, "spread_pips": spread_pips,
                    "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                    "exp": round(s["expectancy_r"], 3), "dd": round(s["max_dd_r"], 1),
                })
    res = pd.DataFrame(rows).sort_values(["pair", "exp"], ascending=[True, False])
    print(res.to_string(index=False))
    res.to_csv("cache/forex_sens.csv", index=False)


if __name__ == "__main__":
    main()
