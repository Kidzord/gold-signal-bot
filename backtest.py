"""Бэктест: сигнал на закрытии бара -> вход по открытию следующего бара.

Учитывает спред, стоп/тейк внутри бара (консервативно: стоп проверяется первым),
перевод в безубыток после +1R и ограничение по времени удержания.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BtConfig:
    spread: float = 0.30            # полный спред в долларах на унцию
    max_bars: int = 48              # максимум часов в сделке
    be_after_r: float | None = 1.0  # перевод стопа в безубыток после +1R
    session: tuple[int, int] | None = (7, 20)  # часы UTC [from, to)
    trail_atr: float | None = None  # трейлинг-стоп: N*ATR от экстремума с момента входа
    tp_r: float | None = None       # переопределить тейк (в R); None => из стратегии


def _exit_check(pos: dict, o: float, h: float, l: float) -> tuple[float, str] | None:
    side, stop, tp = pos["side"], pos["stop"], pos["tp"]
    if side == "long":
        if l <= stop:
            return (stop if o >= stop else o), "SL"
        if tp is not None and h >= tp:
            return (tp if o <= tp else o), "TP"
    else:
        if h >= stop:
            return (stop if o <= stop else o), "SL"
        if tp is not None and l <= tp:
            return (tp if o >= tp else o), "TP"
    return None


def simulate(df: pd.DataFrame, sig: pd.DataFrame, cfg: BtConfig) -> pd.DataFrame:
    n = len(df)
    ts = df.index
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float)
    hours = ts.hour.to_numpy()

    long_s = sig["long_signal"].to_numpy(bool)
    short_s = sig["short_signal"].to_numpy(bool)
    stop_mult = float(sig["stop_atr"].iloc[0])
    rr = float(cfg.tp_r if cfg.tp_r is not None else sig["rr"].iloc[0])
    stop_prices = sig["stop_price"].to_numpy(float) if "stop_price" in sig.columns else None
    tp_prices = sig["tp_price"].to_numpy(float) if "tp_price" in sig.columns else None

    allowed = np.ones(n, bool)
    if cfg.session:
        start, end = cfg.session
        allowed = (hours >= start) & (hours < end)

    trades: list[dict] = []
    pos: dict | None = None

    def close(position: dict, i: int, price: float, reason: str) -> None:
        side, entry, risk = position["side"], position["entry"], position["risk"]
        gross = (price - entry) if side == "long" else (entry - price)
        pnl = gross - cfg.spread
        trades.append(
            {
                "entry_time": position["time"],
                "exit_time": ts[i],
                "side": side,
                "entry": entry,
                "exit": price,
                "stop": position["stop0"],
                "tp": position["tp"],
                "pnl_usd": pnl,
                "r": pnl / risk if risk > 0 else 0.0,
                "bars": i - position["bar"],
                "reason": reason,
            }
        )

    for i in range(n):
        if pos is not None:
            res = _exit_check(pos, o[i], h[i], l[i])
            if res is None and (i - pos["bar"]) >= cfg.max_bars:
                res = (c[i], "TIME")
            if res is not None:
                close(pos, i, res[0], res[1])
                pos = None
            else:
                if cfg.be_after_r is not None and not pos["be"] and i > pos["bar"]:
                    entry, risk = pos["entry"], pos["risk"]
                    hit = (
                        h[i] >= entry + risk * cfg.be_after_r
                        if pos["side"] == "long"
                        else l[i] <= entry - risk * cfg.be_after_r
                    )
                    if hit:
                        pos["stop"] = entry
                        pos["be"] = True
                if cfg.trail_atr is not None:
                    a_i = atr[i]
                    if np.isfinite(a_i) and a_i > 0:
                        if pos["side"] == "long":
                            pos["hh"] = max(pos.get("hh", pos["entry"]), h[i])
                            new_stop = pos["hh"] - cfg.trail_atr * a_i
                            pos["stop"] = max(pos["stop"], new_stop)
                        else:
                            pos["ll"] = min(pos.get("ll", pos["entry"]), l[i])
                            new_stop = pos["ll"] + cfg.trail_atr * a_i
                            pos["stop"] = min(pos["stop"], new_stop)

        if pos is not None or i == 0 or not allowed[i]:
            continue
        if not (long_s[i - 1] or short_s[i - 1]) or (long_s[i - 1] and short_s[i - 1]):
            continue

        a = atr[i - 1]
        if not np.isfinite(a) or a <= 0:
            continue

        side = "long" if long_s[i - 1] else "short"
        entry = o[i]
        sp = stop_prices[i - 1] if stop_prices is not None else np.nan
        if np.isfinite(sp) and sp > 0 and ((side == "long" and sp < entry) or (side == "short" and sp > entry)):
            risk = abs(entry - sp)
            stop = sp
        else:
            risk = stop_mult * a
            stop = entry - risk if side == "long" else entry + risk
        tp = None if rr <= 0 else (entry + risk * rr if side == "long" else entry - risk * rr)
        tp_fixed = tp_prices[i - 1] if tp_prices is not None else np.nan
        if np.isfinite(tp_fixed) and tp_fixed > 0 and ((side == "long" and tp_fixed > entry) or (side == "short" and tp_fixed < entry)):
            tp = float(tp_fixed)
        pos = {
            "side": side, "entry": entry, "stop": stop, "stop0": stop, "tp": tp,
            "risk": risk, "bar": i, "time": ts[i], "be": False,
        }
        # проверяем стоп/тейк уже на баре входа (консервативно)
        res = _exit_check(pos, o[i], h[i], l[i])
        if res is not None:
            close(pos, i, res[0], res[1])
            pos = None

    cols = ["entry_time", "exit_time", "side", "entry", "exit", "stop", "tp", "pnl_usd", "r", "bars", "reason"]
    return pd.DataFrame(trades, columns=cols)


def stats(trades: pd.DataFrame) -> dict:
    base = {
        "trades": 0, "winrate": 0.0, "pf": 0.0, "expectancy_r": 0.0,
        "total_r": 0.0, "max_dd_r": 0.0, "trades_per_month": 0.0,
        "avg_bars": 0.0, "long_trades": 0, "short_trades": 0,
    }
    if trades.empty:
        return base

    r = trades["r"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    equity = np.cumsum(r)
    peak = np.maximum.accumulate(equity)
    dd = float((peak - equity).max())

    days = (trades["exit_time"].max() - trades["entry_time"].min()).total_seconds() / 86400
    months = max(days / 30.44, 0.1)
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())
    return {
        "trades": int(len(trades)),
        "winrate": float(len(wins) / len(trades) * 100),
        "pf": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "expectancy_r": float(r.mean()),
        "total_r": float(r.sum()),
        "max_dd_r": dd,
        "trades_per_month": float(len(trades) / months),
        "avg_bars": float(trades["bars"].mean()),
        "long_trades": int((trades["side"] == "long").sum()),
        "short_trades": int((trades["side"] == "short").sum()),
    }


def fold_report(df: pd.DataFrame, runner, folds: int = 4) -> list[dict]:
    """Walk-forward по времени: одинаковые параметры на последовательных участках."""
    n = len(df)
    edges = [int(n * k / folds) for k in range(folds + 1)]
    out = []
    for k in range(folds):
        part = df.iloc[edges[k]:edges[k + 1]]
        st = stats(runner(part))
        st["from"] = str(part.index[0].date())
        st["to"] = str(part.index[-1].date())
        out.append(st)
    return out
