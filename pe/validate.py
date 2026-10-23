"""Long-history robustness check: do the strategies beat buy & hold across many different windows?

A single backtest is one sample. This runs every strategy variant from a plain lump sum in the Nifty 50 ETF
over ~10 years, then over rolling windows (default 3 years, starting every 12 months), and reports for each
strategy: whole-period CAGR after liquidation tax, max drawdown, and across windows the median and worst
excess return over buy & hold plus the share of windows it won. Parameters are fixed in settings.yaml and
are not tuned on these windows; the split table shows an early (development) and late (holdout) half so
you can see whether an edge exists in both. Today's tax rules are applied to the whole history, which is
a simplification (rates were different before July 2024).
"""
from __future__ import annotations

import copy
import json
import logging
from datetime import date

import numpy as np
import pandas as pd

from .backtest import VARIANTS, run_all
from .config import ROOT, Lot, Settings, load_settings
from .data import build_prices, fetch_closes


def load_long(years: int = 10, refresh: bool = False):
    s = load_settings()
    end = pd.Timestamp.today()
    s.raw["data"]["history_start"] = str((end - pd.DateOffset(years=years + 2)).date())
    s.raw["data"]["cache_dir"] = "data/cache_long"
    s.raw["data"]["cache_max_age_hours"] = 24 * 7
    closes = fetch_closes(s, refresh)
    px, vix = build_prices(s, closes)
    return s, px, vix, closes


def _cagr(r: float, years: float) -> float:
    return (1 + r) ** (1 / years) - 1 if years > 0 and r > -1 else float("nan")


def run_window(settings: Settings, px, vix, fx, start: pd.Timestamp, end: pd.Timestamp, lump: float, variants=VARIANTS):
    sub = px.loc[:end]
    idx = sub.index[sub.index >= start]
    if len(idx) < 60:
        return None
    p0 = float(sub.loc[idx[0], "NIFTYBEES"])
    lots = [Lot("NIFTYBEES", lump / p0, idx[0].date(), p0)]
    curves, table, logs = run_all(lots, sub, vix, settings, idx[0], fx, variants)
    return curves, table, logs


def validate(years: int = 10, lump: float = 1_000_000, window_years: int = 3, step_months: int = 12,
             refresh: bool = False, variants=VARIANTS) -> dict:
    s, px, vix, closes = load_long(years, refresh)
    fx = closes[s["data"]["fx_ticker"]].reindex(px.index).ffill() if s["data"]["fx_ticker"] in closes else None
    end = px.index[-1]
    first_signal = px.index[0] + pd.DateOffset(months=14)       # signals need ~13 months of history
    full_start = max(first_signal, end - pd.DateOffset(years=years))
    base = variants[0][0]

    full = run_window(s, px, vix, fx, full_start, end, lump, variants)
    curves, ftab, flogs = full
    yrs = (end - full_start).days / 365.25
    out = {"start": str(full_start.date()), "end": str(end.date()), "years": round(yrs, 2), "lump": lump,
           "missing_assets": [a for a in s.assets if a not in px or px[a].dropna().empty]}
    full_rows = {}
    for name, r in ftab.iterrows():
        full_rows[name] = {"cagr_after_tax": _cagr(r["after_tax_return_liquidated"], yrs), "max_drawdown": r["max_drawdown"],
                           "taxes_paid": r["taxes_paid"], "costs": r["costs"], "turnover_x": r["turnover_x"],
                           "volatility": r["volatility"], "sharpe": r["sharpe"]}
    out["full"] = full_rows
    out["curves"] = {"dates": [str(d.date()) for d in curves.index[::5]],
                     "series": {c: [round(float(v), 0) for v in curves[c].iloc[::5]] for c in curves.columns}}

    wins = []
    t = full_start
    while t + pd.DateOffset(years=window_years) <= end + pd.Timedelta(days=5):
        wins.append((t, min(t + pd.DateOffset(years=window_years), end)))
        t += pd.DateOffset(months=step_months)
    rows = {n: [] for n, *_ in variants}
    for a, b in wins:
        res = run_window(s, px, vix, fx, a, b, lump, variants)
        if res is None:
            continue
        tab = res[1]
        wy = (b - a).days / 365.25
        bh = tab.loc[base, "after_tax_return_liquidated"]
        for n in rows:
            rows[n].append({"start": str(a.date()), "end": str(b.date()),
                            "cagr": _cagr(tab.loc[n, "after_tax_return_liquidated"], wy),
                            "excess": _cagr(tab.loc[n, "after_tax_return_liquidated"], wy) - _cagr(bh, wy),
                            "mdd": tab.loc[n, "max_drawdown"], "mdd_bh": tab.loc[base, "max_drawdown"]})
        logging.info("window %s..%s done", a.date(), b.date())
    summ = {}
    mid = full_start + (end - full_start) / 2
    for n, rs in rows.items():
        ex = np.array([r["excess"] for r in rs])
        dd = np.array([r["mdd"] - r["mdd_bh"] for r in rs])
        early = [r["excess"] for r in rs if pd.Timestamp(r["end"]) <= mid + pd.Timedelta(days=200)]
        late = [r["excess"] for r in rs if pd.Timestamp(r["start"]) >= mid - pd.Timedelta(days=200)]
        summ[n] = {"windows": len(rs), "median_excess": float(np.median(ex)) if len(ex) else None,
                   "worst_excess": float(ex.min()) if len(ex) else None, "win_rate": float((ex > 0).mean()) if len(ex) else None,
                   "median_dd_improvement": float(np.median(dd)) if len(dd) else None,
                   "early_median_excess": float(np.median(early)) if early else None,
                   "late_median_excess": float(np.median(late)) if late else None}
    out["windows"] = summ
    out["window_detail"] = rows
    out["window_years"] = window_years
    return out


def verdicts(res: dict, base: str) -> dict:
    """Robust = beats buy & hold in a majority of windows AND median excess positive in both halves
    AND the worst window loses less than 5 points a year. Labels, not guarantees."""
    out = {}
    for n, w in res["windows"].items():
        if n == base:
            continue
        ok = (w["win_rate"] or 0) >= 0.6 and (w["early_median_excess"] or -1) > 0 and (w["late_median_excess"] or -1) > 0 \
            and (w["worst_excess"] or -1) > -0.05
        dd_only = (w["median_dd_improvement"] or 0) > 0.03 and (w["median_excess"] or -1) > -0.02
        promising = (w["win_rate"] or 0) >= 0.7 and (w["median_excess"] or -1) > 0 and (w["worst_excess"] or -1) > -0.05
        out[n] = ("robust edge" if ok else "promising, not proven" if promising else
                  "cuts drawdown at little cost" if dd_only else "no reliable edge")
    return out


def report(res: dict, base: str) -> str:
    v = verdicts(res, base)
    L = [f"# Robustness check: {res['start']} to {res['end']} ({res['years']} years)", "",
         f"Start: Rs {res['lump']:,.0f} lump sum in Nifty 50 ETF (baseline = hold it). Every strategy then runs the live planner day by day "
         f"with lots, costs and Indian capital-gains tax (today's rules applied to all years). Rolling {res['window_years']}-year windows test whether "
         "an edge repeats or was one lucky stretch. Parameters were not tuned on these windows.", ""]
    if res["missing_assets"]:
        L.append(f"_No history for: {', '.join(res['missing_assets'])}; they enter the universe only once data exists._\n")
    L += ["| strategy | CAGR after tax | max drawdown | tax paid | costs | windows won | median excess/yr | worst window | early half | late half | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda x: "-" if x is None else f"{x:+.1%}"
    for n, r in res["full"].items():
        w = res["windows"][n]
        L.append(f"| {n} | {r['cagr_after_tax']:.1%} | {r['max_drawdown']:.1%} | {r['taxes_paid']:,.0f} | {r['costs']:,.0f} | "
                 f"{'-' if n == base else f'{w['win_rate']:.0%}'} | {'-' if n == base else f(w['median_excess'])} | {'-' if n == base else f(w['worst_excess'])} | "
                 f"{'-' if n == base else f(w['early_median_excess'])} | {'-' if n == base else f(w['late_median_excess'])} | {v.get(n, 'baseline')} |")
    L += ["", "_excess = annualised after-tax return minus buy & hold in the same window. 'robust edge' needs a win in at least 60% of windows, "
              "a positive median in both halves, and no window worse than -5 points a year. 'promising' wins 70%+ of windows but fails one of those tests; "
              "variants added after seeing earlier results (the last three) were chosen on this same data, so treat their numbers as optimistic._"]
    return "\n".join(L)


def save(res: dict) -> None:
    d = ROOT / "reports"
    d.mkdir(exist_ok=True)
    (d / "validation.json").write_text(json.dumps(res, default=str))
    (d / "validation.md").write_text(report(res, VARIANTS[0][0]) + "\n")
