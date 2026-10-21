"""Что даёт параллельный режим: две стратегии на одном золоте против каждой по отдельности."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import analysis
import backtest as bt
import strategy as st

df = analysis.load_frame("GC=F")
cfg = bt.BtConfig(spread=0.30, max_bars=48, be_after_r=None, session=None)
cfg_asian = bt.BtConfig(spread=0.30, max_bars=72, be_after_r=None, session=None)

ta = bt.simulate(df, st.breakout(df), cfg)
tb = bt.simulate(df, st.asian_breakout(df), cfg_asian)

def daily_r(trades: pd.DataFrame) -> pd.Series:
    s = trades.copy()
    s["day"] = pd.to_datetime(s["exit_time"]).dt.date
    return s.groupby("day")["r"].sum()

a, b = daily_r(ta), daily_r(tb)
idx = sorted(set(a.index) | set(b.index))
a = a.reindex(idx, fill_value=0.0)
b = b.reindex(idx, fill_value=0.0)
comb = a + b

def stats(series: pd.Series, label: str) -> dict:
    eq = series.cumsum()
    peak = eq.cummax()
    dd = (peak - eq).max()
    return {"стратегия": label, "сумма R": round(eq.iloc[-1], 1), "макс. просадка R": round(dd, 1),
            "дней": int((series != 0).sum()), "сделок": None}

rows = [
    {"вариант": "breakout", "итог R": round(a.sum(), 1), "просадка R": round((a.cumsum().cummax() - a.cumsum()).max(), 1)},
    {"вариант": "asian", "итог R": round(b.sum(), 1), "просадка R": round((b.cumsum().cummax() - b.cumsum()).max(), 1)},
    {"вариант": "оба (сумма)", "итог R": round(comb.sum(), 1),
     "просадка R": round((comb.cumsum().cummax() - comb.cumsum()).max(), 1)},
]
out = pd.DataFrame(rows)
out["R на просадку"] = (out["итог R"] / out["просадка R"]).round(2)
print(out.to_string(index=False))
print(f"\nкорреляция дневных результатов: {a.corr(b):.2f}")
print(f"дней со сделками: breakout {int((a != 0).sum())}, asian {int((b != 0).sum())}, "
      f"пересечение {int(((a != 0) & (b != 0)).sum())}")
print(f"сделок: breakout {len(ta)}, asian {len(tb)}")
