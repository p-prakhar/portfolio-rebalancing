"""Valuation and forecast signals for the Nifty 50, built to be point-in-time.

Inputs (all free, cached as CSV under data/valuation/):
  * Nifty 50 P/E, P/B and dividend yield, daily, from niftyindices.com (or your own data/manual/nifty_valuation.csv).
  * India 10-year government bond yield, monthly, from FRED (or data/manual/india_10y.csv).
  * Nifty 50 price history from Yahoo (^NSEI), for the forecast model's momentum feature and target.

Every signal on day t uses only data published on or before day t. Bond yields are lagged 60 days (monthly series are
published late). The forecast model is refit monthly on rows whose 1-year outcome was already known on the refit date.
Each signal becomes a scale factor in [floor, 1] applied to India equity weight; the rest goes to cash. No signal ever
adds leverage or goes beyond the original weight, so the worst case is lagging a rising market, not a bigger loss.
All thresholds are fixed in settings.yaml (valuation block) and were set before any result was seen.
"""
from __future__ import annotations

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT

log = logging.getLogger(__name__)
SIGNALS = ("pe", "spread", "fcst")
FWD = 252                    # trading days in the forecast horizon


def _dir(cfg: dict) -> Path:
    d = ROOT / cfg.get("cache_dir", "data/valuation")
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- fetching

NSE_ARCHIVES = ("https://archives.nseindia.com", "https://nsearchives.nseindia.com")   # either may 403 after heavy use
NSE_PATH = "/content/indices/ind_close_all_{:%d%m%Y}.csv"
_NIFTY50_NAMES = {"nifty 50", "cnx nifty", "s&p cnx nifty"}


def _nse_archive_day(day: pd.Timestamp):
    """One daily NSE index close file -> (date, pe, pb, div_yield) for the Nifty 50, or None (holiday / not published)."""
    import requests
    for attempt in range(6):
        host = NSE_ARCHIVES[attempt % 2]
        try:
            r = requests.get(host + NSE_PATH.format(day), headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        except Exception:
            continue
        if r.status_code in (403, 429, 502, 503):
            continue
        if r.status_code != 200 or not r.text.startswith("Index Name"):
            return None
        df = pd.read_csv(io.StringIO(r.text))
        row = df[df["Index Name"].str.strip().str.lower().isin(_NIFTY50_NAMES)]
        if row.empty:
            return None
        row = row.iloc[0]
        return (day, row.get("P/E"), row.get("P/B"), row.get("Div Yield"))
    return None


def _fetch_nse_archive(first: pd.Timestamp, last: pd.Timestamp) -> pd.DataFrame:
    """Fallback when niftyindices.com is down: daily NSE archive files carry P/E, P/B, Div Yield for every index."""
    days = pd.bdate_range(first, last)
    with ThreadPoolExecutor(4) as ex:
        out = [r for r in ex.map(_nse_archive_day, days) if r]
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out, columns=["date", "pe", "pb", "div_yield"]).set_index("date")
    return df.apply(pd.to_numeric, errors="coerce").sort_index()

def fetch_nifty_valuation(cfg: dict, start: int = 1999, refresh: bool = False) -> pd.DataFrame:
    """Daily Nifty 50 pe, pb, div_yield. Manual CSV (date,pe,pb,div_yield) wins; else niftyindices.com in one-year chunks."""
    man = ROOT / "data" / "manual" / "nifty_valuation.csv"
    if man.exists():
        return _read_val(man)
    cache = _dir(cfg) / "nifty_valuation.csv"
    have = _read_val(cache) if cache.exists() else pd.DataFrame()
    if refresh or have.empty or (pd.Timestamp.today().normalize() - have.index[-1]).days > 7:
        import requests
        sess = requests.Session()
        sess.headers.update({"User-Agent": "Mozilla/5.0", "Content-Type": "application/json; charset=UTF-8",
                             "Origin": "https://niftyindices.com", "Referer": "https://niftyindices.com/reports/historical-data",
                             "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"})
        try:
            sess.get("https://niftyindices.com/reports/historical-data", timeout=30)
        except Exception as exc:
            log.warning("niftyindices warm-up failed: %s", exc)
        first = start if have.empty else have.index[-1].year
        rows = []
        for y in range(first, pd.Timestamp.today().year + 1):
            body = {"cinfo": json.dumps({"name": "NIFTY 50", "startDate": f"01-Jan-{y}", "endDate": f"31-Dec-{y}", "indexName": "NIFTY 50"})}
            try:
                r = sess.post("https://niftyindices.com/Backpage.aspx/getpepbHistoricaldataDBtoken", data=json.dumps(body), timeout=60)
                data = json.loads(r.json()["d"])
            except Exception as exc:
                log.warning("niftyindices %s failed: %s", y, exc)
                continue
            for d in data:
                rows.append((d.get("DATE") or d.get("Date"), d.get("pe") or d.get("P/E"), d.get("pb") or d.get("P/B"),
                             d.get("divYield") or d.get("Div Yield")))
        if not rows:
            # NSE archive only goes back to about 2012, so history is shorter than the niftyindices route
            lo = max(pd.Timestamp("2011-01-01"), have.index[-1] if not have.empty else pd.Timestamp("2011-01-01"))
            fb = _fetch_nse_archive(lo, pd.Timestamp.today().normalize())
            if not fb.empty:
                log.warning("niftyindices unavailable; used NSE daily archive from %s", fb.index[0].date())
                fb = fb.dropna(subset=["pe"])
                df = pd.concat([have, fb]) if not have.empty else fb
                df = df[~df.index.duplicated(keep="last")]
                df.rename_axis("date").to_csv(cache)
                have = df
        if rows:
            df = pd.DataFrame(rows, columns=["date", "pe", "pb", "div_yield"])
            df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=True, errors="coerce")
            df = df.dropna(subset=["date"]).set_index("date").apply(pd.to_numeric, errors="coerce").sort_index()
            df = pd.concat([have, df]) if not have.empty else df
            df = df[~df.index.duplicated(keep="last")].dropna(subset=["pe"])
            df.rename_axis("date").to_csv(cache)
            have = df
    if have.empty:
        raise RuntimeError("No Nifty valuation data. Put a CSV (date,pe,pb,div_yield) at data/manual/nifty_valuation.csv "
                           "(download from niftyindices.com > Historical Data > P/E, P/B, Div Yield).")
    return have


def _read_val(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower().replace("/", "").replace(" ", "_") for c in df.columns]
    df = df.rename(columns={"div_yield": "div_yield", "divyield": "div_yield"})
    df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=True)
    return df.set_index("date").sort_index().apply(pd.to_numeric, errors="coerce")


def fetch_bond_yield(cfg: dict, refresh: bool = False) -> pd.Series:
    """India 10y yield in decimal (0.07 = 7%), monthly. Empty series if unavailable (spread signal then stays neutral)."""
    man = ROOT / "data" / "manual" / "india_10y.csv"
    cache = _dir(cfg) / "india_10y.csv"
    for p in (man, cache):
        if p.exists() and not (p is cache and refresh):
            df = pd.read_csv(p)
            s = pd.Series(df.iloc[:, 1].astype(float).values / (100 if df.iloc[:, 1].max() > 1.5 else 1),
                          index=pd.to_datetime(df.iloc[:, 0]))
            return s.sort_index()
    try:
        s = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=INDIRLTLT01STM")
        s.columns = ["date", "y"]
        s["y"] = pd.to_numeric(s["y"], errors="coerce")
        s = s.dropna()
        s.to_csv(cache, index=False)
        return pd.Series(s["y"].values / 100, index=pd.to_datetime(s["date"])).sort_index()
    except Exception as exc:
        log.warning("India 10y yield unavailable (%s); spread signal disabled", exc)
        return pd.Series(dtype=float)


def fetch_nifty_price(cfg: dict, refresh: bool = False) -> pd.Series:
    cache = _dir(cfg) / "nsei.csv"
    if cache.exists() and not refresh and (pd.Timestamp.now().timestamp() - cache.stat().st_mtime) < 7 * 86400:
        return pd.read_csv(cache, parse_dates=["Date"], index_col="Date")["Close"]
    import yfinance as yf

    from . import quiet
    with quiet():
        df = yf.download("^NSEI", start="2007-09-01", auto_adjust=True, progress=False)
    c = df["Close"].squeeze()
    c.index = pd.to_datetime(c.index).tz_localize(None)
    c.rename("Close").to_frame().rename_axis("Date").to_csv(cache)
    return c


# ---------------------------------------------------------------- point-in-time signals
def expanding_pct(s: pd.Series, min_obs: int) -> pd.Series:
    """Rank of today's value among all values up to and including today (0..1). NaN until min_obs."""
    v = s.values
    out = np.full(len(v), np.nan)
    for i in range(min_obs - 1, len(v)):
        w = v[: i + 1]
        w = w[~np.isnan(w)]
        out[i] = (w <= v[i]).mean() if len(w) >= min_obs and not np.isnan(v[i]) else np.nan
    return pd.Series(out, index=s.index)


def expanding_z(s: pd.Series, min_obs: int) -> pd.Series:
    m, sd = s.expanding(min_obs).mean(), s.expanding(min_obs).std()
    return (s - m) / sd


def forecast_series(feat: pd.DataFrame, price: pd.Series, cash_rate: float, min_train: int = 1250, refit_every: int = 21) -> pd.DataFrame:
    """Walk-forward OLS forecast of the next-252-day Nifty return minus cash.

    feat: daily features (columns used as regressors). At each refit date t0 only rows whose outcome ended on or before t0
    are used. Returns columns yhat (forecast) and bench (expanding mean of past realised outcomes, the no-skill forecast)."""
    px = price.reindex(feat.index).ffill()
    y = (px.shift(-FWD) / px - 1) - cash_rate                 # known only FWD days later
    X = feat.copy()
    n = len(X)
    yhat, bench = np.full(n, np.nan), np.full(n, np.nan)
    beta = None
    mu = np.nan
    for i in range(n):
        if i % refit_every == 0 or beta is None:
            tr = slice(0, max(0, i - FWD))                      # outcomes complete by day i
            Xt, yt = X.iloc[tr].values, y.iloc[tr].values
            ok = ~np.isnan(Xt).any(axis=1) & ~np.isnan(yt)
            if ok.sum() >= min_train:
                A = np.c_[np.ones(ok.sum()), Xt[ok]]
                beta = np.linalg.lstsq(A, yt[ok], rcond=None)[0]
                mu = yt[ok].mean()
        if beta is not None and not np.isnan(X.iloc[i].values).any():
            yhat[i] = beta[0] + X.iloc[i].values @ beta[1:]
            bench[i] = mu
    return pd.DataFrame({"yhat": yhat, "bench": bench, "y": y.values}, index=X.index)


def build_signals(val: pd.DataFrame, bond: pd.Series, price: pd.Series, cfg: dict, cash_rate: float) -> pd.DataFrame:
    """Daily scale factors (1 = fully invested, floor = cut to that fraction) for each signal, plus the raw inputs."""
    mo = cfg["min_history_days"]
    pe = val["pe"].dropna()
    out = pd.DataFrame(index=pe.index)
    out["pe"] = pe
    out["pe_pct"] = expanding_pct(pe, mo)
    lo, hi, fl = cfg["pe"]["start_pct"], cfg["pe"]["full_cut_pct"], cfg["floor"]
    out["f_pe"] = (1 - (1 - fl) * ((out["pe_pct"] - lo) / (hi - lo)).clip(0, 1)).fillna(1.0)
    if len(bond):
        b = bond.copy()
        b.index = b.index + pd.Timedelta(days=cfg["bond_lag_days"])
        y10 = b.reindex(b.index.union(pe.index)).ffill().reindex(pe.index)
        out["spread"] = 1 / pe - y10                              # earnings yield minus bond yield
        out["spread_z"] = expanding_z(out["spread"], mo)
        z0, z1 = cfg["spread"]["start_z"], cfg["spread"]["full_cut_z"]
        out["f_spread"] = (1 - (1 - fl) * ((z0 - out["spread_z"]) / (z0 - z1)).clip(0, 1)).fillna(1.0)
    else:
        out["f_spread"] = 1.0
    feat = pd.DataFrame({"pe_pct": out["pe_pct"], "mom12": price.reindex(pe.index).ffill().pct_change(252)})
    fc = forecast_series(feat, price, cash_rate, cfg["fcst"]["min_train_days"])
    out["yhat"], out["bench"], out["y"] = fc["yhat"], fc["bench"], fc["y"]
    out["f_fcst"] = np.where(out["yhat"] < cfg["fcst"]["cut_below"], fl, 1.0)
    out.loc[out["yhat"].isna(), "f_fcst"] = 1.0
    return out


def scale_for(sig: pd.DataFrame, kind: str, ts: pd.Timestamp) -> float:
    """Scale factor on day ts using data up to the previous day (one-day publication safety margin)."""
    prior = sig.loc[: ts - pd.Timedelta(days=1)]
    if prior.empty:
        return 1.0
    parts = [kind] if kind in SIGNALS else list(SIGNALS)       # "all" = most cautious of the three
    return float(min(prior[f"f_{k}"].iloc[-1] for k in parts))


# ---------------------------------------------------------------- do these signals predict anything?
def diagnose(sig: pd.DataFrame, price: pd.Series, horizons=(252, 756)) -> dict:
    """Out-of-sample evidence, before any trading rule: rank correlation of each signal with the realised forward return,
    and the forecast model's out-of-sample R-squared against the no-skill (past mean) forecast.
    Overlapping daily windows inflate the sample, so we also report the number of independent horizons."""
    px = price.reindex(sig.index).ffill()
    out = {}
    for h in horizons:
        fwd = px.shift(-h) / px - 1
        d = pd.DataFrame({"pe_pct": sig["pe_pct"], "spread_z": sig.get("spread_z"), "yhat": sig["yhat"], "fwd": fwd}).dropna()
        if len(d) < 250:
            continue
        eff = len(d) / h
        row = {"obs": len(d), "independent_periods": round(eff, 1), "start": str(d.index[0].date()), "end": str(d.index[-1].date())}
        for c in ("pe_pct", "spread_z", "yhat"):
            if c in d and d[c].notna().sum() > 250:
                rho = d[c].rank().corr(d["fwd"].rank())
                row[c] = {"rank_corr": round(float(rho), 3), "t_stat_approx": round(float(rho * np.sqrt(max(eff - 2, 1)) / np.sqrt(1 - rho ** 2)), 2)}
        out[f"{h}d"] = row
    f = sig.dropna(subset=["yhat", "bench", "y"])
    if len(f) > 250:
        sse = ((f["y"] - f["yhat"]) ** 2).sum()
        sse0 = ((f["y"] - f["bench"]) ** 2).sum()
        out["forecast_oos_r2_vs_mean"] = round(float(1 - sse / sse0), 3)
        out["forecast_period"] = [str(f.index[0].date()), str(f.index[-1].date())]
    return out
