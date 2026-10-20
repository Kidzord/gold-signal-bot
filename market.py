"""Загрузка котировок золота с Yahoo Finance (без API-ключа) + локальный кэш.

Символ по умолчанию GC=F — фьючерс на золото COMEX, ближайший контракт.
Он ликвиднее и точнее, чем XAUUSD=X, и Yahoo отдаёт по нему H1 за ~730 дней.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GoldSignalBot/1.0"


class MarketDataError(RuntimeError):
    pass


@dataclass
class Quote:
    symbol: str
    price: float
    ts: datetime

    @property
    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.ts).total_seconds()


def _http_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MarketDataError(f"Yahoo HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MarketDataError(f"Yahoo request failed: {exc}") from exc


def _chart_url(symbol: str, interval: str, rng: str, host: str) -> str:
    sym = urllib.parse.quote(symbol, safe="")
    return (
        f"https://{host}/v8/finance/chart/{sym}"
        f"?interval={interval}&range={rng}&includePrePost=false&events=div%2Csplit"
    )


def _parse_chart(payload: dict, symbol: str) -> pd.DataFrame:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise MarketDataError(f"Yahoo error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise MarketDataError("Yahoo вернул пустой результат")
    res = results[0]
    ts = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    if not ts:
        raise MarketDataError("Нет свечей в ответе Yahoo")

    df = pd.DataFrame(
        {
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        },
        index=pd.to_datetime(ts, unit="s", utc=True),
    )
    df.index.name = "time"
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.attrs["symbol"] = symbol
    return df


def fetch_candles(symbol: str = "GC=F", interval: str = "1h", rng: str = "730d") -> pd.DataFrame:
    """Свечи с Yahoo. 1h доступен максимум за 730 дней, 1d — за всю историю."""
    last_err: Exception | None = None
    for host in YAHOO_HOSTS:
        try:
            payload = _http_json(_chart_url(symbol, interval, rng, host))
            return _parse_chart(payload, symbol)
        except MarketDataError as exc:
            last_err = exc
    raise MarketDataError(str(last_err))


def fetch_quote(symbol: str = "GC=F") -> Quote:
    payload = _http_json(_chart_url(symbol, "1m", "1d", YAHOO_HOSTS[0]))
    res = (payload.get("chart", {}).get("result") or [{}])[0]
    meta = res.get("meta") or {}
    price = meta.get("regularMarketPrice")
    ts = meta.get("regularMarketTime")
    if price is None:
        raise MarketDataError("Нет текущей цены в ответе Yahoo")
    when = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
    return Quote(symbol=symbol, price=float(price), ts=when)


# ---------------------------------------------------------------- кэш

def _cache_path(symbol: str, interval: str, rng: str) -> str:
    safe = symbol.replace("=", "_").replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{interval}_{rng}.csv")


def load_cached(symbol: str, interval: str, rng: str) -> pd.DataFrame | None:
    path = _cache_path(symbol, interval, rng)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=["time"], index_col="time")
        df.index = pd.to_datetime(df.index, utc=True)
        return df.sort_index()
    except (ValueError, OSError):
        return None


def save_cached(df: pd.DataFrame, symbol: str, interval: str, rng: str) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(_cache_path(symbol, interval, rng), index_label="time")


def get_history(
    symbol: str = "GC=F",
    interval: str = "1h",
    rng: str = "730d",
    max_age_seconds: int = 600,
) -> pd.DataFrame:
    """История свечей: из кэша, если он моложе max_age_seconds, иначе — из сети."""
    path = _cache_path(symbol, interval, rng)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_seconds:
        cached = load_cached(symbol, interval, rng)
        if cached is not None and len(cached) > 100:
            return cached

    try:
        df = fetch_candles(symbol, interval, rng)
        save_cached(df, symbol, interval, rng)
        return df
    except MarketDataError:
        cached = load_cached(symbol, interval, rng)
        if cached is not None and len(cached) > 100:
            return cached
        raise


def closed_bars(df: pd.DataFrame, interval: str = "1h") -> pd.DataFrame:
    """Отбрасывает последнюю, ещё не закрытую свечу."""
    step = {"1h": "1h", "30m": "30min", "15m": "15min", "4h": "4h", "1d": "1D"}.get(interval, interval)
    if df.empty:
        return df
    last_start = df.index[-1]
    end = last_start + pd.Timedelta(step)
    now = pd.Timestamp.now(tz="UTC")
    if now < end:
        return df.iloc[:-1]
    return df


RESAMPLE_RULES = {"4h": "4h", "1d": "1D"}


def resample_bars(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Собирает старший таймфрейм из H1 и отбрасывает незакрытый последний бар."""
    rule = RESAMPLE_RULES.get(timeframe)
    if rule is None or timeframe in ("1h", "60m", ""):
        return df
    out = (
        df.resample(rule)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    if not out.empty:
        end = out.index[-1] + pd.Timedelta(rule)
        if pd.Timestamp.now(tz="UTC") < end:
            out = out.iloc[:-1]
    return out

