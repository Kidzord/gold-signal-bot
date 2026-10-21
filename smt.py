"""SMT-дивергенция «золото против серебра» (Smart Money Technique).

Идея: золото (GC=F) и серебро (SI=F) ходят синхронно. Если на экстремуме один
актив обновляет предыдущий экстремум, а второй — нет, возникает расхождение
(SMT), и цена «слабого» актива часто разворачивается в сторону лидера.

Правила (на закрытии бара, без заглядывания в будущее):
  * пивоты ищутся фракталом: экстремум выше/ниже `k` баров слева и справа;
  * пивот подтверждается через `k` баров после своего бара — сравнение идёт
    на баре подтверждения, поэтому вход возможен только после факта;
  * медвежий SMT: золото сделало higher high, серебро — lower high -> шорт;
  * бычий SMT: золото сделало lower low, серебро — higher low -> лонг.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def pivot_flags(high: np.ndarray, low: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Булевы маски подтверждённых пивотов (фрактал с окном k слева и справа)."""
    n = len(high)
    tops = np.zeros(n, bool)
    bottoms = np.zeros(n, bool)
    for i in range(k, n - k):
        if high[i] == high[i - k:i + k + 1].max():
            tops[i] = True
        if low[i] == low[i - k:i + k + 1].min():
            bottoms[i] = True
    return tops, bottoms


def smt_signals(
    gold: pd.DataFrame,
    silver: pd.DataFrame,
    k: int = 3,
    stop_atr: float = 1.5,
    rr: float = 2.0,
    min_gap: int = 0,
    trend_filter: bool = False,
    require_mss: bool = False,
) -> pd.DataFrame:
    """Сигналы SMT по золоту; `silver` выравнивается по индексу `gold`.

    `min_gap`       — минимальное число баров между соседними пивотами (фильтр шума);
    `trend_filter`  — торговать только в сторону EMA200 (нужна колонка ema200);
    `require_mss`   — ждать слома структуры: закрытие за экстремумом бара-пивота
                      в пределах 2*k баров после расхождения.
    """
    common = gold.index.intersection(silver.index)
    g = gold.loc[common]
    s = silver.loc[common]

    gh = g["high"].to_numpy(float)
    gl = g["low"].to_numpy(float)
    gc = g["close"].to_numpy(float)
    sh = s["high"].to_numpy(float)
    sl = s["low"].to_numpy(float)
    n = len(g)

    up = g["close"].to_numpy(float) > g["ema200"].to_numpy(float) if trend_filter else np.ones(n, bool)
    dn = ~up if trend_filter else np.ones(n, bool)

    g_tops, g_bottoms = pivot_flags(gh, gl, k)

    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    reason = np.empty(n, dtype=object)
    reason[:] = ""

    prev_top: int | None = None
    prev_bottom: int | None = None
    wait_top: int | None = None      # ждём слом структуры для шорта
    wait_bottom: int | None = None
    mss_window = 2 * k

    for i in range(k, n):
        p = i - k                      # бар, который подтверждается на баре i
        if g_tops[p]:
            if prev_top is not None and p - prev_top >= min_gap:
                if gh[p] > gh[prev_top] and sh[p] < sh[prev_top] and dn[i]:
                    if require_mss:
                        wait_top = p
                    else:
                        short_sig[i] = True
                    reason[i] = (
                        f"SMT: золото обновило максимум ({gh[p]:.1f} > {gh[prev_top]:.1f}), "
                        f"серебро нет ({sh[p]:.2f} < {sh[prev_top]:.2f})"
                    )
            prev_top = p
        if g_bottoms[p]:
            if prev_bottom is not None and p - prev_bottom >= min_gap:
                if gl[p] < gl[prev_bottom] and sl[p] > sl[prev_bottom] and up[i]:
                    if require_mss:
                        wait_bottom = p
                    else:
                        long_sig[i] = True
                    reason[i] = (
                        f"SMT: золото обновило минимум ({gl[p]:.1f} < {gl[prev_bottom]:.1f}), "
                        f"серебро нет ({sl[p]:.2f} > {sl[prev_bottom]:.2f})"
                    )
            prev_bottom = p

        # слом структуры: закрытие за экстремумом бара-пивота
        if wait_top is not None:
            if gc[i] < gl[wait_top]:
                short_sig[i] = True
                reason[i] = reason[i] or "SMT + слом структуры вниз"
                wait_top = None
            elif i - wait_top > mss_window:
                wait_top = None
        if wait_bottom is not None:
            if gc[i] > gh[wait_bottom]:
                long_sig[i] = True
                reason[i] = reason[i] or "SMT + слом структуры вверх"
                wait_bottom = None
            elif i - wait_bottom > mss_window:
                wait_bottom = None

    out = pd.DataFrame(index=common)
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["reason"] = reason

    out = out.reindex(gold.index)
    out["long_signal"] = out["long_signal"].fillna(False).astype(bool)
    out["short_signal"] = out["short_signal"].fillna(False).astype(bool)
    out["reason"] = out["reason"].fillna("").astype(str)
    out["stop_atr"] = float(stop_atr)
    out["rr"] = float(rr)
    return out
