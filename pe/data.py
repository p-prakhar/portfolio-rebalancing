"""Price data: Yahoo Finance via yfinance, with a CSV cache and manual overrides.

All prices are returned in INR (USD assets converted with USD/INR), total-return
adjusted where Yahoo provides it, on the NSE trading calendar.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, Settings

log = logging.getLogger(__name__)


def _cache_path(settings: Settings, ticker: str) -> Path:
    d = ROOT / settings["data"]["cache_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{ticker.replace('^', '_').replace('=', '_')}.csv"


def _read_csv(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
    return df["Close"].astype(float)


def _download(tickers: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf  # imported lazily so offline/demo mode needs no network stack

    df = yf.download(tickers, start=start, auto_adjust=True, progress=False, group_by="column")
    if df is None or df.empty:
        return pd.DataFrame()
    close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": tickers[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close


def fetch_closes(settings: Settings, refresh: bool = False) -> pd.DataFrame:
    """Return raw closes keyed by ticker (native currency)."""
    cfg = settings["data"]
    tickers = [a.ticker for a in settings.assets.values() if a.ticker]
    tickers += [cfg["fx_ticker"], cfg["vix_ticker"]]
    max_age = cfg.get("cache_max_age_hours", 12) * 3600

    out, stale = {}, []
    for t in tickers:
        p = _cache_path(settings, t)
        if p.exists() and not refresh and time.time() - p.stat().st_mtime < max_age:
            out[t] = _read_csv(p)
        else:
            stale.append(t)
    if stale:
        try:
            fresh = _download(stale, cfg["history_start"])
        except Exception as exc:  # network down etc.: fall back to whatever is cached
            log.warning("Download failed (%s); using cache where available", exc)
            fresh = pd.DataFrame()
        for t in stale:
            s = fresh[t].dropna() if t in fresh else pd.Series(dtype=float)
            p = _cache_path(settings, t)
            if not s.empty:
                s.rename("Close").to_frame().rename_axis("Date").to_csv(p)
                out[t] = s
            elif p.exists():
                out[t] = _read_csv(p)
            else:
                log.warning("No data for %s", t)
    # manual overrides (e.g. broker exports) win
    mdir = ROOT / cfg["manual_dir"]
    for a in settings.assets.values():
        f = mdir / f"{a.symbol}.csv"
        if f.exists() and a.ticker:
            out[a.ticker] = _read_csv(f)
    return pd.DataFrame(out).sort_index()


def drop_bad_prints(closes: pd.DataFrame, tol: float = 2.0) -> pd.DataFrame:
    """Blank out isolated one-day prints that are off by more than `tol`x from their neighbours.

    Yahoo occasionally returns a face-value-split artefact for a single day (e.g. NIFTYBEES and GOLDBEES on
    2019-12-19 print at 1/10 and 1/100 of the real price, then recover). A real split or crash is a lasting step,
    so it is not flagged: the median of the surrounding 5 days follows it.
    """
    med = closes.rolling(5, center=True, min_periods=3).median()
    ratio = closes / med
    bad = (ratio < 1 / tol) | (ratio > tol)
    if bad.values.any():
        n = int(bad.values.sum())
        log.warning("Dropped %d isolated bad price prints (%s)", n, ", ".join(sorted(bad.columns[bad.any()])))
    return closes.mask(bad)


def build_prices(settings: Settings, closes: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series | None]:
    """INR prices per symbol on the NSE calendar, plus India VIX if available."""
    cfg = settings["data"]
    closes = drop_bad_prints(closes)
    fx = closes.get(cfg["fx_ticker"])
    anchor = closes.get("NIFTYBEES.NS")
    cal = anchor.dropna().index if anchor is not None and anchor.notna().any() else closes.dropna(how="all").index
    filled = closes.reindex(closes.index.union(cal)).sort_index().ffill(limit=5).reindex(cal)

    prices = {}
    for sym, a in settings.assets.items():
        if sym == "CASH":
            continue
        if a.ticker not in filled:
            continue
        s = filled[a.ticker]
        if a.currency == "USD":
            if fx is None:
                log.warning("No FX series; dropping %s", sym)
                continue
            s = s * filled[cfg["fx_ticker"]]
        prices[sym] = s
    px = pd.DataFrame(prices, index=cal)
    px["CASH"] = cash_series(cal, settings["cash"]["rate"])
    vix = filled[cfg["vix_ticker"]] if cfg["vix_ticker"] in filled else None
    return px, vix


def cash_series(index: pd.DatetimeIndex, rate: float) -> pd.Series:
    days = (index - index[0]).days.values
    return pd.Series(100.0 * (1 + rate) ** (days / 365.0), index=index)


def synthetic_prices(settings: Settings, start="2023-06-01", end="2026-10-22", seed=7) -> tuple[pd.DataFrame, pd.Series]:
    """Random-walk prices for smoke tests ONLY. Never use for decisions."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end)
    px = {}
    for i, (sym, a) in enumerate(settings.assets.items()):
        if sym == "CASH":
            continue
        mu, sig = rng.uniform(-0.05, 0.25), rng.uniform(0.12, 0.30)
        r = rng.normal(mu / 252, sig / np.sqrt(252), len(idx))
        px[sym] = 100 * np.exp(np.cumsum(r)) * (1 + i)
    df = pd.DataFrame(px, index=idx)
    df["CASH"] = cash_series(idx, settings["cash"]["rate"])
    vix = pd.Series(14 + 6 * np.abs(np.sin(np.arange(len(idx)) / 40)), index=idx)
    return df, vix
