"""Plain-English summaries of each calendar year, and which strategy won it. Rule-based: no language model involved.

Each rule looks at rupee returns of a few market gauges for the year and fires a short phrase when its threshold is
crossed; the year's summary is the strongest two or three phrases. Thresholds are deliberately round numbers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GAUGES = {"nifty": "NIFTYBEES", "next50": "JUNIORBEES", "mid": "MID150BEES", "bank": "BANKBEES", "psu": "PSUBNKBEES",
          "gold": "GOLDBEES", "silver": "SILVERBEES", "sp500": "SPY", "nasdaq": "QQQ", "chips": "SMH", "bonds": "TLT", "copper": "CPER"}


def _yr(s: pd.Series, y: int) -> tuple[float | None, float | None]:
    s = s.dropna()
    prev = s[s.index < f"{y}-01-01"]
    cur = s[(s.index >= f"{y}-01-01") & (s.index <= f"{y}-12-31")]
    if cur.empty or prev.empty:
        return None, None
    path = pd.concat([prev.iloc[-1:], cur])
    return float(cur.iloc[-1] / prev.iloc[-1] - 1), float((path / path.cummax() - 1).min())


def year_facts(px: pd.DataFrame, fx: pd.Series | None, years: list[int]) -> dict[int, dict]:
    out = {}
    for y in years:
        f = {}
        for k, sym in GAUGES.items():
            if sym in px:
                r, dd = _yr(px[sym], y)
                if r is not None:
                    f[k] = r
                    if k == "nifty":
                        f["nifty_dd"] = dd
        if fx is not None:
            r, _ = _yr(fx, y)
            if r is not None:
                f["usdinr"] = r
        out[y] = f
    return out


def describe(f: dict) -> str:
    """Two or three short phrases, strongest first."""
    n = f.get("nifty")
    if n is None:
        return "Not enough data."
    cands = []   # (strength, phrase)
    dd = f.get("nifty_dd") or 0
    if dd <= -0.20:
        cands.append((abs(dd) * 3, f"Crash: the Nifty fell {abs(dd):.0%} at its worst" + (f" and still ended {n:+.0%}" if n > 0 else f" and ended {n:+.0%}")))
    elif dd <= -0.12:
        cands.append((abs(dd) * 2, f"A {abs(dd):.0%} correction in Indian shares"))
    if n >= 0.20:
        cands.append((n * 2, f"Strong year for Indian shares (Nifty {n:+.0%})"))
    elif abs(n) < 0.05 and dd > -0.12:
        cands.append((0.15, f"Flat year for the Nifty ({n:+.0%})"))
    elif n <= -0.05:
        cands.append((abs(n) * 2, f"Indian shares fell (Nifty {n:+.0%})"))
    g = f.get("gold")
    if g is not None and g >= 0.20 and g > n + 0.10:
        cands.append((g * 2, f"Gold boom (gold {g:+.0%} in rupees)"))
    s = f.get("silver")
    if s is not None and s >= 0.30:
        cands.append((s * 1.5, f"Silver surged {s:+.0%}"))
    c, q = f.get("chips"), f.get("nasdaq")
    if c is not None and c >= 0.40:
        cands.append((c * 1.5, f"Chip rally (semiconductors {c:+.0%} in rupees)"))
    elif q is not None and q >= 0.30:
        cands.append((q * 1.4, f"US tech rally (Nasdaq 100 {q:+.0%} in rupees)"))
    elif q is not None and q <= -0.20:
        cands.append((abs(q) * 1.5, f"US tech sell-off (Nasdaq 100 {q:+.0%} in rupees)"))
    for k, label in (("mid", "Mid caps"), ("next50", "Next 50 stocks")):
        v = f.get(k)
        if v is not None and v - n >= 0.10:
            cands.append(((v - n) * 1.5, f"{label} beat the Nifty by {(v - n) * 100:.0f} points"))
            break
        if v is not None and v - n <= -0.10:
            cands.append(((n - v) * 1.5, f"{label} lagged the Nifty by {(n - v) * 100:.0f} points"))
            break
    p = f.get("psu")
    if p is not None and p >= 0.40:
        cands.append((p, f"PSU bank rally ({p:+.0%})"))
    u = f.get("usdinr")
    if u is not None and u >= 0.04:
        cands.append((u * 3, f"Rupee fell {u:.0%} against the dollar, lifting US assets"))
    elif u is not None and u <= -0.03:
        cands.append((abs(u) * 3, f"Rupee strengthened {abs(u):.0%}"))
    cu = f.get("copper")
    if cu is not None and abs(cu) >= 0.25:
        cands.append((abs(cu), f"Copper {'jumped' if cu > 0 else 'slumped'} {cu:+.0%}"))
    cands.sort(key=lambda x: -x[0])
    phrases = [p for _, p in cands[:3]] or [f"An ordinary year (Nifty {n:+.0%})"]
    return ". ".join(phrases) + "."


def strategy_years(sim_all: dict, horizon: int = 10) -> tuple[list[int], dict[str, dict[int, float]]]:
    """Calendar-year returns of each strategy from the daily-simulation curves (before tax still owed at year end)."""
    rows = [r for r in sim_all["results"] if r["years"] == horizon]
    out, years = {}, set()
    for r in rows:
        s = pd.Series(r["curve"]["values"], index=pd.to_datetime(r["curve"]["dates"]))
        yr = {}
        for y in sorted(set(s.index.year)):
            prev = s[s.index < f"{y}-01-01"]
            cur = s[s.index.year == y]
            base = prev.iloc[-1] if len(prev) else cur.iloc[0]
            yr[int(y)] = float(cur.iloc[-1] / base - 1)
            years.add(int(y))
        out[r["label"]] = yr
    return sorted(years), out


def build(sim_all: dict, px: pd.DataFrame, fx: pd.Series | None, horizon: int = 10) -> dict:
    years, strat = strategy_years(sim_all, horizon)
    base = next(r["label"] for r in sim_all["results"] if r["years"] == horizon and r["policy"] == "buy_hold")
    facts = year_facts(px, fx, years)
    first, last = min(years), max(years)
    rows = []
    for y in years:
        rets = {k: v.get(y) for k, v in strat.items()}
        others = {k: v for k, v in rets.items() if k != base and v is not None}
        win = max(others, key=others.get) if others else None
        beat = sum(1 for v in others.values() if rets.get(base) is not None and v > rets[base])
        rows.append({"year": y, "partial": y in (first, last), "insight": describe(facts.get(y, {})), "facts": facts.get(y, {}),
                     "returns": rets, "winner": win, "beat_hold": beat, "n": len(others)})
    return {"horizon": horizon, "hold": base, "strategies": list(strat), "rows": rows}
