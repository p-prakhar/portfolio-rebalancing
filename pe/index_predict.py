"""Predict Nifty200 Momentum 30 reconstitution from public prices.

The index is rebuilt every June and December from the Nifty 200 using a normalised momentum
score (6m and 12m price return divided by annualised volatility, z-scored, averaged); data is
taken as of the last trading day of May / November and changes take effect at the end of the
following month. Passive funds tracking it must then buy the entrants and sell the exits,
in size (about Rs 16,000 crore round trip in Dec 2025). Knowing the likely list early is the
edge; it is a short-term trade, so gains are STCG at 20%.

This approximation ignores NSE's eligibility filters (listing age, F&O, free float caps), so
treat the output as a watchlist, and compare it with the official announcement.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _symbols(path: str) -> list[str]:
    df = pd.read_csv(path)
    col = next(c for c in df.columns if c.strip().lower() in ("symbol", "ticker", "tradingsymbol"))
    return [str(s).strip().upper() for s in df[col].dropna()]


def nms_scores(px: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=px.columns)
    for m, d in ((6, 126), (12, 252)):
        w = px.iloc[-d - 1:]
        ret = w.iloc[-1] / w.iloc[0] - 1
        vol = w.pct_change().std() * np.sqrt(252)
        mr = ret / vol
        out[f"ret_{m}m"] = ret
        out[f"z_{m}m"] = (mr - mr.mean()) / mr.std(ddof=0)
    out["score"] = (out["z_6m"] + out["z_12m"]) / 2
    return out.sort_values("score", ascending=False)


def predict(universe_csv: str, current_csv: str | None, size: int = 30, demo: bool = False) -> str:
    syms = _symbols(universe_csv)
    if demo:
        rng = np.random.default_rng(1)
        idx = pd.bdate_range(end=pd.Timestamp.today(), periods=300)
        px = pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(rng.uniform(-.0005, .001), .02, len(idx)))) for s in syms}, index=idx)
    else:
        import yfinance as yf
        raw = yf.download([f"{s}.NS" for s in syms], period="15mo", auto_adjust=True, progress=False)["Close"]
        px = raw.rename(columns=lambda c: c.replace(".NS", ""))
    px = px.dropna(axis=1, thresh=253).ffill()
    sc = nms_scores(px)
    top = list(sc.index[:size])
    lines = [f"# Predicted Nifty200 Momentum {size} (as of {px.index[-1].date()})", "",
             "| rank | symbol | score | 6m | 12m |", "|---|---|---|---|---|"]
    for i, s in enumerate(top, 1):
        r = sc.loc[s]
        lines.append(f"| {i} | {s} | {r.score:+.2f} | {r.ret_6m:+.1%} | {r.ret_12m:+.1%} |")
    if current_csv:
        cur = set(_symbols(current_csv))
        adds, drops = [s for s in top if s not in cur], sorted(cur - set(top))
        lines += ["", f"**Likely entrants ({len(adds)}):** {', '.join(adds) or 'none'}",
                  f"**Likely exits ({len(drops)}):** {', '.join(drops) or 'none'}",
                  "", f"Borderline names (ranks {max(1, size - 4)}-{size + 5}) are the least reliable predictions: "
                  + ", ".join(f"{s} (#{i + 1})" for i, s in enumerate(sc.index[max(0, size - 5):size + 5], max(0, size - 5)))]
    lines += ["", "_Watchlist only: NSE eligibility filters are not modelled. Passive buying usually lands on the "
              "effective date; prices often move after the announcement, so the edge is in being early and small._"]
    return "\n".join(lines)
