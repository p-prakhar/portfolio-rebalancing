"""Daily closes from Yahoo's chart endpoint with a plain HTTP client.

Used where yfinance cannot be installed (the Android app: yfinance needs curl_cffi, which has no Android build).
Same numbers as `yf.download(..., auto_adjust=True)`: the adjusted close, on the exchange's own calendar dates.
The client identifies itself honestly and does nothing to get around rate limits; when Yahoo refuses, the caller
falls back to the cache and reports the gap.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote

import pandas as pd

log = logging.getLogger(__name__)

HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
HEADERS = {"User-Agent": "portfolio-engine/1.0 (personal portfolio tracker)", "Accept": "application/json"}
last_errors: list[str] = []      # filled by download(); the app shows these when nothing could be fetched
_fetcher = None


def set_fetcher(fn) -> None:
    """Swap the HTTP transport: a callable url -> response text, or an object with .get(url) (the Android app's HTTP client)."""
    global _fetcher
    _fetcher = fn


def _get(url: str) -> str:
    if _fetcher is not None:
        return str(_fetcher(url) if callable(_fetcher) else _fetcher.get(url))
    import requests
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def _get_json(path: str) -> dict:
    err = None
    for host in HOSTS:
        try:
            return json.loads(_get(f"https://{host}{path}"))
        except Exception as exc:       # try the other host, then give up
            err = exc
    raise err


def parse_chart(payload: dict) -> pd.Series:
    """Adjusted daily closes from a /v8/finance/chart response, indexed by the exchange's local date."""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(str(chart["error"].get("description") or chart["error"]))
    res = (chart.get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        return pd.Series(dtype=float)
    ind = res.get("indicators") or {}
    vals = ((ind.get("adjclose") or [{}])[0].get("adjclose")) or ((ind.get("quote") or [{}])[0].get("close")) or []
    off = int((res.get("meta") or {}).get("gmtoffset") or 0)
    idx = pd.to_datetime([t + off for t in res["timestamp"]], unit="s").normalize()
    s = pd.Series(vals, index=idx, dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def history(ticker: str, start: str = "2023-06-01") -> pd.Series:
    p1 = int(datetime.fromisoformat(str(start)[:10]).replace(tzinfo=timezone.utc).timestamp())
    p2 = int(time.time()) + 86400
    return parse_chart(_get_json(f"/v8/finance/chart/{quote(ticker)}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits"))


def download(tickers: list[str], start: str, workers: int = 6) -> pd.DataFrame:
    """Closes for many tickers, one column each. Tickers that fail are left out and noted in last_errors."""
    last_errors.clear()

    def one(t):
        try:
            return t, history(t, start)
        except Exception as exc:
            last_errors.append(f"{t}: {type(exc).__name__} {str(exc)[:120]}")
            return t, pd.Series(dtype=float)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        got = dict(ex.map(one, tickers))
    if last_errors:
        log.warning("Price download: %d of %d tickers failed (%s)", len(last_errors), len(tickers), "; ".join(last_errors[:3]))
    return pd.DataFrame({t: s for t, s in got.items() if not s.empty}).sort_index()


def search(q: str, limit: int = 12) -> list[dict]:
    """Symbol lookup: [{ticker, name, exchange, type}] for stocks, ETFs and funds."""
    j = _get_json(f"/v1/finance/search?q={quote(q)}&quotesCount={limit}&newsCount=0")
    out = []
    for r in j.get("quotes") or []:
        if r.get("quoteType") not in ("EQUITY", "ETF", "MUTUALFUND", "INDEX"):
            continue
        out.append({"ticker": r.get("symbol", ""), "name": r.get("longname") or r.get("shortname") or r.get("symbol", ""),
                    "exchange": r.get("exchDisp") or r.get("exchange") or "", "type": r.get("quoteType", "")})
    return out
