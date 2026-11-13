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
from .global_markets import apply_dividend_drag

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

    from . import quiet
    with quiet():
        df = yf.download(tickers, start=start, auto_adjust=True, progress=False, group_by="column")
    if df is None or df.empty:
        return pd.DataFrame()
    close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": tickers[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close


def splice_history(old: pd.Series, new: pd.Series, gap_days: int = 10) -> tuple[pd.Series, bool]:
    """Keep older cached rows when a fresh download comes back starting later than the cache did.

    Yahoo sometimes serves only the recent stub of a series it used to serve in full (SETFNIF50.NS and MID150BEES.NS
    did in Nov 2026). Replacing the cache with the stub would silently erase the history every signal and backtest
    needs. The older rows are rescaled by the median new/old ratio where the two overlap, so a split or dividend
    re-adjustment in between does not leave a step. Returns (series, spliced?)."""
    old, new = old.dropna(), new.dropna()
    if old.empty or new.empty or new.index[0] <= old.index[0] + pd.Timedelta(days=gap_days):
        return new, False
    head = old[old.index < new.index[0]]
    both = old.index.intersection(new.index)
    k = float((new[both] / old[both]).median()) if len(both) else 1.0
    if not np.isfinite(k) or k <= 0:
        k = 1.0
    return pd.concat([head * k, new]), True


def fetch_closes(settings: Settings, refresh: bool = False) -> pd.DataFrame:
    """Return raw closes keyed by ticker (native currency)."""
    cfg = settings["data"]
    tickers = [a.ticker for a in settings.assets.values() if a.ticker and not a.ticker.startswith("MFAPI:")]
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
                if p.exists():
                    s, spliced = splice_history(_read_csv(p), s)
                    if spliced:
                        log.warning("%s: the download starts on %s, later than the cached history; kept the older cached rows",
                                    t, fresh[t].dropna().index[0].date())
                s.rename("Close").to_frame().rename_axis("Date").to_csv(p)
                out[t] = s
            elif p.exists():
                out[t] = _read_csv(p)
            else:
                log.warning("No data for %s", t)
    # mutual funds: daily NAVs from mfapi.in (AMFI data)
    mf = [a.ticker for a in settings.assets.values() if a.ticker and a.ticker.startswith("MFAPI:")]
    if mf:
        from .mf import nav_series
        for t in mf:
            try:
                out[t] = nav_series(t.split(":", 1)[1], refresh=refresh)
            except Exception as exc:
                log.warning("No NAV history for %s (%s)", t, exc)
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


def backfill_equivalents(settings: Settings, prices: dict[str, pd.Series], gap_days: int = 10) -> list[str]:
    """Give a fund that tracks the same index as another (`equivalent_of`) the other's prices where its own are missing:
    before its history starts, and after its feed stops.

    The primary's prices are scaled to meet the fund's own (median ratio over the nearest 20 common days), so there is
    no step at the join. Without this a holding with a short or dead price feed is valued at a stale figure and cannot
    be sold in a backtest. Returns the symbols that were filled."""
    done = []
    for sym, a in settings.assets.items():
        prim = a.equivalent_of
        if not prim or sym not in prices or prim not in prices:
            continue
        own, ref = prices[sym].dropna(), prices[prim].dropna()
        both = own.index.intersection(ref.index)
        if own.empty or ref.empty or not len(both):
            continue
        s, how = prices[sym].copy(), []
        if own.index[0] > ref.index[0] + pd.Timedelta(days=gap_days):
            early = s.index < own.index[0]
            s[early] = prices[prim][early] * float((own[both[:20]] / ref[both[:20]]).median())
            how.append(f"history before {own.index[0].date()}")
        late = (s.index > own.index[-1]) & prices[prim].notna()
        if late.any():
            s[late] = prices[prim][late] * float((own[both[-20:]] / ref[both[-20:]]).median())
            how.append(f"prices after {own.index[-1].date()}")
        if how:
            prices[sym] = s
            done.append(sym)
            log.warning("%s: %s taken from %s (same index), scaled to match", sym, " and ".join(how), prim)
    return done


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
            s = apply_dividend_drag(settings, a, s)
        prices[sym] = s
    backfill_equivalents(settings, prices)
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
