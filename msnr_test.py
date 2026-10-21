"""Сравнение MSNR-подхода с текущей стратегией: чистые сигналы и фильтр-подтверждение."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

import backtest as bt
import indicators
import market
import msnr
import strategy as st

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 40)

CFG = dict(spread=0.30, max_bars=48, be_after_r=None, session=None)


def folds_min(df, sig, cfg) -> float:
    edges = [int(len(df) * k / 4) for k in range(5)]
    vals = []
    for k in range(4):
        part = df.iloc[edges[k]:edges[k + 1]]
        s = sig.iloc[edges[k]:edges[k + 1]]
        vals.append(bt.stats(bt.simulate(part, s, cfg))["expectancy_r"])
    return min(vals)


def near_zone_mask(df: pd.DataFrame, zones, width: float = 1.0) -> np.ndarray:
    """Бар считается «у уровня», если цена в пределах width*ATR от любой активной зоны."""
    n = len(df)
    stamps = msnr._index_stamps(df)
    atr = df["atr"].to_numpy(float)
    close = df["close"].to_numpy(float)
    near = np.zeros(n, bool)

    intervals = []
    for z in zones:
        start = int(np.searchsorted(stamps, msnr._np_time(z.born), "left"))
        end = n if z.broken is None else int(np.searchsorted(stamps, msnr._np_time(z.broken), "left"))
        if end > start:
            intervals.append((start, end, z))
    intervals.sort(key=lambda x: x[0])

    active, ptr = [], 0
    for i in range(n):
        active = [it for it in active if it[1] > i]
        while ptr < len(intervals) and intervals[ptr][0] <= i:
            if intervals[ptr][1] > i:
                active.append(intervals[ptr])
            ptr += 1
        for _start, _end, z in active:
            if z.bottom - width * atr[i] <= close[i] <= z.top + width * atr[i]:
                near[i] = True
                break
    return near


def main() -> None:
    raw = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])
    cfg = bt.BtConfig(**CFG)

    base_sig = st.breakout(df)
    base = bt.stats(bt.simulate(df, base_sig, cfg))
    print(f"БАЗА (пробой канала): {base['trades']} сделок · {base['winrate']:.0f}% · "
          f"PF {base['pf']:.2f} · {base['expectancy_r']:+.3f}R · {base['total_r']:+.0f}R · "
          f"{base['trades_per_month']:.1f}/мес\n")

    rows = []
    for source, strength in itertools.product(("h1", "h4", "d1"), (3, 5)):
        if source == "h1":
            zones = msnr.build_zones(df, strength=strength)
        else:
            zones = msnr.htf_zones(df, rule="4h" if source == "h4" else "1D", strength=strength)

        for mode, trend, zstop in itertools.product(("bounce", "break"), (True, False), (True, False)):
            sig = msnr.signals_from_zones(df, zones, mode=mode, trend_filter=trend, zone_stop=zstop)
            if not (sig.long_signal.any() or sig.short_signal.any()):
                continue
            tr = bt.simulate(df, sig, cfg)
            s = bt.stats(tr)
            if s["trades"] < 25:
                continue
            rows.append({
                "src": source, "k": strength, "mode": mode, "trend": trend, "zstop": zstop,
                "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                "exp": round(s["expectancy_r"], 3), "total": round(s["total_r"], 1),
                "dd": round(s["max_dd_r"], 1), "per_month": round(s["trades_per_month"], 1),
                "fold_min": round(folds_min(df, sig, cfg), 3),
            })

    res = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print("=== ЧИСТЫЕ СИГНАЛЫ MSNR (топ-12)")
    print(res.head(12).to_string(index=False))
    res.to_csv("cache/msnr_results.csv", index=False)

    print("\n=== КОМБИНАЦИИ: пробой канала + подтверждение уровнем MSNR")
    combos = []
    h1_zones = msnr.build_zones(df, strength=3)
    h4_zones = msnr.htf_zones(df, rule="4h", strength=3)
    for label, zones in (("h1", h1_zones), ("h4", h4_zones)):
        near = near_zone_mask(df, zones, width=1.0)
        for _need in (True,):
            s2 = base_sig.copy()
            s2["long_signal"] = s2["long_signal"] & pd.Series(near, index=df.index)
            s2["short_signal"] = s2["short_signal"] & pd.Series(near, index=df.index)
            tr = bt.simulate(df, s2, cfg)
            s = bt.stats(tr)
            combos.append({
                "filter": f"пробой у уровня MSNR({label}, 1 ATR)", "n": s["trades"],
                "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                "exp": round(s["expectancy_r"], 3), "total": round(s["total_r"], 1),
                "dd": round(s["max_dd_r"], 1), "per_month": round(s["trades_per_month"], 1),
                "fold_min": round(folds_min(df, s2, cfg), 3),
            })

    print(pd.DataFrame(combos).to_string(index=False))

    lv = msnr.nearest_levels(df, h4_zones)
    print(f"\nБлижайшие H4-уровни: поддержка {lv['nearest_support']}, сопротивление {lv['nearest_resistance']}")


if __name__ == "__main__":
    main()
