"""Do valuation and forecast signals improve on the existing strategies? One study, run once, honest about trials.

1. Predictive check (no trading): do P/E percentile, earnings-yield-minus-bond-yield and a walk-forward regression forecast
   Nifty returns out of sample over ~18 years? Reports rank correlation, independent-period count and out-of-sample R-squared.
2. Trading check: the same engine (lots, costs, Indian tax, 10-year rolling windows) with each signal as an overlay on a
   Nifty-only strategy and on the current best multi-asset strategy, against buy & hold and the unadorned strategies.
3. Overfitting guard: a stationary-bootstrap reality check on all variants tried (White 2000 style). It asks whether the BEST
   variant's excess return could be the best of N coin flips. Thresholds were fixed in settings.yaml before any run.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import ROOT
from .validate import load_long, validate
from . import valuation as V

BASE = "Buy & hold Nifty 50"
VARIANTS = [
    (BASE, "buy_hold", "immediate", False),
    ("Nifty + P/E percentile", "nifty+pe", "immediate", True),
    ("Nifty + earnings yield vs bond yield", "nifty+spread", "immediate", True),
    ("Nifty + regression forecast", "nifty+fcst", "immediate", True),
    ("Nifty + all three (most cautious)", "nifty+all", "immediate", True),
    ("Core-satellite momentum (current best)", "core_xs", "immediate", True),
    ("Core-satellite + P/E percentile", "core_xs+pe", "immediate", True),
    ("Core-satellite + earnings yield vs bond", "core_xs+spread", "immediate", True),
    ("Core-satellite + regression forecast", "core_xs+fcst", "immediate", True),
]
N_NEW = sum(1 for v in VARIANTS if "+" in v[1])


def prepare(years: int = 10, refresh: bool = False):
    """Settings with the valuation signals attached, plus the signal table and Nifty price."""
    s, px, vix, closes = load_long(years, refresh)
    cfg = s.strategy["valuation"]
    val = V.fetch_nifty_valuation(cfg, refresh=refresh)
    bond = V.fetch_bond_yield(cfg, refresh=refresh)
    price = V.fetch_nifty_price(cfg, refresh=refresh)
    sig = V.build_signals(val, bond, price, cfg, s["cash"]["rate"])
    s.raw["_valuation_signals"] = sig
    return s, sig, price


def reality_check(curves: dict[str, list[float]], base: str, block: int = 12, n: int = 2000, seed: int = 11) -> dict:
    """Stationary bootstrap on paired returns (curves are every 5th trading day). Returns per-variant mean excess, CI, and a
    family-wise p-value for 'the best of these variants beats the baseline by chance'."""
    rng = np.random.default_rng(seed)
    r = {k: np.diff(np.log(np.array(v, float))) for k, v in curves.items()}
    ex = {k: r[k] - r[base] for k in r if k != base}
    T = len(next(iter(ex.values())))
    stats = {k: v.mean() for k, v in ex.items()}
    obs_max = max(stats.values())
    boot = np.zeros((n, len(ex)))
    keys = list(ex)
    for b in range(n):
        idx = np.empty(T, int)
        i = 0
        while i < T:
            start = rng.integers(0, T)
            ln = min(rng.geometric(1 / block), T - i)
            idx[i:i + ln] = (start + np.arange(ln)) % T
            i += ln
        boot[b] = [ex[k][idx].mean() - stats[k] for k in keys]      # centred: null of no edge
    fam_p = float((boot.max(axis=1) >= obs_max).mean())
    out = {}
    for j, k in enumerate(keys):
        se = boot[:, j].std()
        ann = 252 / 5
        out[k] = {"excess_per_year": float(stats[k] * ann), "ci95_lo": float((stats[k] - 1.96 * se) * ann), "ci95_hi": float((stats[k] + 1.96 * se) * ann),
                  "p_single": float((boot[:, j] >= stats[k]).mean())}
    return {"variants": out, "family_p_best_by_chance": fam_p, "trials": len(keys), "best": max(stats, key=stats.get)}


def run(years: int = 10, window_years: int = 3, refresh: bool = False) -> dict:
    s, sig, price = prepare(years, refresh)
    diag = V.diagnose(sig, price)
    import pe.validate as pv
    # validate() reloads data through load_long, so hand it our signal-carrying settings
    orig = pv.load_long
    pv.load_long = lambda y, r=False: (s, *orig(y, r)[1:])
    try:
        res = validate(years=years, window_years=window_years, refresh=refresh, variants=VARIANTS)
    finally:
        pv.load_long = orig
    rc = reality_check(res["curves"]["series"], BASE)
    out = {"diagnostics": diag, "validation": res, "reality_check": rc, "signal_tail": sig.tail(1).round(4).to_dict("records")}
    d = ROOT / "reports"
    d.mkdir(exist_ok=True)
    (d / "forecast_study.json").write_text(json.dumps(out, default=str))
    (d / "forecast_study.md").write_text(report(out) + "\n")
    return out


def report(o: dict) -> str:
    res, rc, dg = o["validation"], o["reality_check"], o["diagnostics"]
    L = ["# Forecasts and fundamentals: do they beat the backtest?", "",
         f"Period {res['start']} to {res['end']}. Same engine as the daily simulation: lots, costs, Indian tax, rolling {res['window_years']}-year windows.", "",
         "## 1. Do the signals predict returns at all? (no trading rule yet)", ""]
    for k, v in dg.items():
        if k.endswith("d") and isinstance(v, dict):
            L.append(f"- **{k} ahead** ({v['start']} to {v['end']}, about {v['independent_periods']} independent periods): " +
                     "; ".join(f"{c} rank corr {v[c]['rank_corr']:+.2f} (t ≈ {v[c]['t_stat_approx']})" for c in ("pe_pct", "spread_z", "yhat") if c in v))
    if "forecast_oos_r2_vs_mean" in dg:
        L.append(f"- Walk-forward regression forecast, out-of-sample R² against the plain past-average forecast: **{dg['forecast_oos_r2_vs_mean']:+.3f}** "
                 f"({dg['forecast_period'][0]} to {dg['forecast_period'][1]}). Below zero means it forecast worse than not forecasting.")
    L += ["", "## 2. Trading results", "",
          "| strategy | CAGR after tax | max drawdown | windows won | median excess/yr | worst window | early half | late half |", "|---|---|---|---|---|---|---|---|"]
    f = lambda x: "-" if x is None else f"{x:+.1%}"
    for n, r in res["full"].items():
        w = res["windows"][n]
        b = n == BASE
        L.append(f"| {n} | {r['cagr_after_tax']:.1%} | {r['max_drawdown']:.1%} | {'-' if b else f'{w['win_rate']:.0%}'} | {'-' if b else f(w['median_excess'])} | "
                 f"{'-' if b else f(w['worst_excess'])} | {'-' if b else f(w['early_median_excess'])} | {'-' if b else f(w['late_median_excess'])} |")
    L += ["", "## 3. Could the best of these be luck?", "",
          f"{rc['trials']} variants were tried against the baseline (plus about 10 strategies already tested earlier, so the real number of trials is higher). "
          f"Block-bootstrap reality check: probability that the best variant ({rc['best']}) looks this good by chance across all {rc['trials']}: **{rc['family_p_best_by_chance']:.2f}**. "
          "Below 0.05 would be evidence of a real edge; above 0.10 means we cannot tell it from luck.", "",
          "| variant | excess per year | 95% interval | p (alone) |", "|---|---|---|---|"]
    for k, v in rc["variants"].items():
        L.append(f"| {k} | {v['excess_per_year']:+.1%} | {v['ci95_lo']:+.1%} to {v['ci95_hi']:+.1%} | {v['p_single']:.2f} |")
    return "\n".join(L)
