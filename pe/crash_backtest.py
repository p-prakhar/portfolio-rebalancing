"""Did the crash guard earn its keep? Real crashes versus the whipsaws it caused, after costs and Indian tax.

`python main.py crash-test` replays the live planner day by day over ~10 years (needs Yahoo data; same loader as
`validate`) for buy & hold and the core strategy, each with and without the guard. It then reports:

  1. whole-period result: CAGR after liquidation tax, max drawdown, tax and costs paid
  2. every drawdown of 10%+ in the market proxy: how far the guard let you fall, how fast it moved, what the exit cost
  3. the whipsaw ledger: every time the guard went to "elevated" or worse, whether the market then fell a further 10%
     within 120 days (a justified alarm) or not (a false alarm), and what the false alarms cost

The guard's parameters are fixed in config/settings.yaml and were not tuned on this data. Crashes are rare, so the
episode list is short: read it as a few case studies, not a statistic.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import crash
from .backtest import VARIANTS, run_all
from .config import Lot, Settings

PICK = ["Buy & hold (your current portfolio)", "Buy & hold + crash guard", "Core-satellite without core overlay",
        "Core + momentum + crash guard", "Dual momentum (Nifty/Gold/Cash)", "Trend filter + vol targeting"]
FALSE_ALARM_FALL = 0.10
HORIZON_DAYS = 120


def drawdown_episodes(s: pd.Series, min_dd: float = 0.10) -> list[dict]:
    """Peak-to-trough falls of at least `min_dd`, with the date the old peak was regained (None if not yet)."""
    out, peak_i, i, n = [], 0, 0, len(s)
    v = s.to_numpy()
    while i < n:
        if v[i] >= v[peak_i]:
            peak_i = i
            i += 1
            continue
        j, trough = i, i
        while j < n and v[j] < v[peak_i]:
            if v[j] < v[trough]:
                trough = j
            j += 1
        if v[trough] / v[peak_i] - 1 <= -min_dd:
            out.append({"peak": s.index[peak_i], "trough": s.index[trough], "recovered": s.index[j] if j < n else None,
                        "depth": float(v[trough] / v[peak_i] - 1)})
        peak_i = j if j < n else peak_i
        i = j
    return out


def alarm_ledger(proxy: pd.Series, level: pd.Series, min_level: int = 2) -> list[dict]:
    """Each stretch at `min_level`+ : did the proxy fall a further 10% in the next 120 days?"""
    up = (level >= min_level).to_numpy()
    rows, i, n = [], 0, len(level)
    while i < n:
        if not up[i]:
            i += 1
            continue
        j = i
        while j < n and up[j]:
            j += 1
        p0 = float(proxy.iloc[i])
        end = min(i + HORIZON_DAYS, n - 1)
        low = float(proxy.iloc[i:end + 1].min())
        fall = low / p0 - 1
        back = float(proxy.iloc[min(j, n - 1)] / p0 - 1)
        rows.append({"start": proxy.index[i], "end": proxy.index[min(j, n - 1)], "days": j - i, "max_level": int(level.iloc[i:j].max()),
                     "further_fall": fall, "market_move_while_out": back, "justified": fall <= -FALSE_ALARM_FALL,
                     "ongoing": j >= n})
        i = j
    return rows


def run(years: int = 10, lump: float = 1_000_000, refresh: bool = False, data=None) -> dict:
    from .validate import load_long, run_window
    s, px, vix, closes = data or load_long(years, refresh)
    return analyse(s, px, vix, years, lump)


def analyse(s: Settings, px: pd.DataFrame, vix, years: int, lump: float, fx=None) -> dict:
    end = px.index[-1]
    start = max(px.index[0] + pd.DateOffset(months=14), end - pd.DateOffset(years=years))
    idx = px.index[px.index >= start]
    p0 = float(px.loc[idx[0], "NIFTYBEES"])
    lots = [Lot("NIFTYBEES", lump / p0, idx[0].date(), p0)]
    variants = [v for v in VARIANTS if v[0] in PICK]
    curves, table, logs = run_all(lots, px, vix, s, idx[0], fx, variants)
    yrs = (end - idx[0]).days / 365.25
    lv = crash.level_series(px, vix, s)
    proxy = crash._proxy(px, crash.cfg(s)["proxy"]).reindex(idx)
    level = lv["level"].reindex(idx)
    base = PICK[0]
    rows = {}
    for n, r in table.iterrows():
        rows[n] = {"cagr": (1 + r["after_tax_return_liquidated"]) ** (1 / yrs) - 1, "max_drawdown": r["max_drawdown"], "volatility": r["volatility"],
                   "taxes_paid": r["taxes_paid"], "costs": r["costs"], "turnover_x": r["turnover_x"]}
    eps = []
    for e in drawdown_episodes(curves[base]):
        win = slice(e["peak"], e["recovered"] or end)
        mk = proxy.loc[win]
        entry = {"peak": e["peak"], "trough": e["trough"], "recovered": e["recovered"], "depth_nav": e["depth"], "depth_market": float(mk.min() / mk.iloc[0] - 1)}
        up = level.loc[e["peak"]:e["trough"]]
        first = up[up >= 2]
        if len(first):
            d = first.index[0]
            entry["guard_flag"] = {"date": d, "days_after_peak": int((d - e["peak"]).days), "market_down_at_flag": float(proxy.loc[d] / mk.iloc[0] - 1)}
        else:
            entry["guard_flag"] = None
        entry["by_strategy"] = {}
        for n in curves.columns:
            seg = curves[n].loc[win]
            entry["by_strategy"][n] = float((seg / seg.cummax() - 1).min())
        eps.append(entry)
    ledger = alarm_ledger(proxy, level)
    guard_names = [n for n in curves.columns if "crash guard" in n]
    flips = {n: sum(1 for d, k, m in logs[n] if k == "PLAN") for n in guard_names}
    return {"start": str(idx[0].date()), "end": str(end.date()), "years": round(yrs, 2), "lump": lump, "base": base, "full": rows,
            "episodes": eps, "ledger": ledger, "plans_by_variant": flips,
            "level_days": {crash.LEVELS[k]: int((level == k).sum()) for k in range(4)}, "credit_available": "HYG" in px and "IEF" in px,
            "curves": {"dates": [str(d.date()) for d in curves.index[::5]], "series": {c: [round(float(v)) for v in curves[c].iloc[::5]] for c in curves.columns},
                       "level": [int(x) for x in level.iloc[::5]]}}


def report(res: dict) -> str:
    f = lambda x: "-" if x is None else f"{x:+.1%}"
    d = lambda x: "-" if x is None else str(pd.Timestamp(x).date())
    L = [f"# Crash guard test: {res['start']} to {res['end']} ({res['years']} years)", "",
         f"Rs {res['lump']:,.0f} lump sum in a Nifty 50 ETF, then each strategy runs the live planner every day with lots, costs and Indian capital-gains tax "
         "(today's rules applied to all years). The guard's parameters are fixed in settings.yaml and were not tuned on this data.", ""]
    if not res["credit_available"]:
        L += ["_No HYG/IEF history, so the credit signal was not scored and the guard was slightly less sensitive._", ""]
    L += ["## Whole period", "", "| strategy | CAGR after tax | max drawdown | tax paid | costs | turnover |", "|---|---|---|---|---|---|"]
    for n, r in res["full"].items():
        L.append(f"| {n} | {r['cagr']:.1%} | {r['max_drawdown']:.1%} | {r['taxes_paid']:,.0f} | {r['costs']:,.0f} | {r['turnover_x']:.1f}x |")
    L += ["", f"Days spent at each guard level: " + ", ".join(f"{k} {v}" for k, v in res["level_days"].items()) + ".", "",
          "## Every fall of 10% or more in the buy & hold portfolio", "",
          "Max drawdown from the peak to the peak being regained, per strategy. 'Guard flagged' is the first day the level reached elevated.", ""]
    names = list(res["full"])
    L += ["| peak | trough | recovered | market fall | guard flagged | market down by then | " + " | ".join(names) + " |", "|---|---|---|---|---|---|" + "---|" * len(names)]
    for e in res["episodes"]:
        g = e["guard_flag"]
        L.append(f"| {d(e['peak'])} | {d(e['trough'])} | {d(e['recovered'])} | {e['depth_market']:.1%} | {d(g['date']) + f' (+{g['days_after_peak']}d)' if g else 'never'} | "
                 f"{f(g['market_down_at_flag']) if g else '-'} | " + " | ".join(f"{e['by_strategy'][n]:.1%}" for n in names) + " |")
    if not res["episodes"]:
        L.append("| none in this window | | | | | | " + "| " * len(names))
    led = res["ledger"]
    just = [r for r in led if r["justified"]]
    L += ["", "## Whipsaw ledger", "",
          f"The guard went to elevated or worse {len(led)} times; in {len(just)} the market then fell another {FALSE_ALARM_FALL:.0%}+ within {HORIZON_DAYS} days. "
          "'Market move while out' is what the market did between the alarm and the all-clear (positive = you missed a rise).", "",
          "| from | to | days | worst level | further fall in 120d | market move while out | verdict |", "|---|---|---|---|---|---|---|"]
    for r in led:
        L.append(f"| {d(r['start'])} | {d(r['end'])}{' (ongoing)' if r['ongoing'] else ''} | {r['days']} | {crash.LEVELS[r['max_level']]} | {r['further_fall']:.1%} | "
                 f"{f(r['market_move_while_out'])} | {'justified' if r['justified'] else 'false alarm'} |")
    b, g = res["base"], "Buy & hold + crash guard"
    if g in res["full"]:
        L += ["", "## Verdict", "",
              f"Against buy & hold, the guard changed CAGR by {(res['full'][g]['cagr'] - res['full'][b]['cagr']) * 100:+.1f} points a year and max drawdown from "
              f"{res['full'][b]['max_drawdown']:.1%} to {res['full'][g]['max_drawdown']:.1%}, at an extra Rs "
              f"{res['full'][g]['taxes_paid'] + res['full'][g]['costs'] - res['full'][b]['taxes_paid'] - res['full'][b]['costs']:,.0f} of tax and costs. "
              "Insurance has a premium: judge it by the drawdown it removed against the return it gave up, not by return alone."]
    return "\n".join(L)


def synthetic_panel(settings: Settings, kind: str, seed: int = 3) -> tuple[pd.DataFrame, pd.Series]:
    """Made-up price panels for tests and the demo. kind: steady | bubble_burst | v_crash | chop | grind_bear."""
    from .data import cash_series
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2014-01-01", periods=3300)
    n = len(idx)
    daily = lambda mu, sig, k: rng.normal(mu / 252, sig / np.sqrt(252), k)
    mkt = daily(0.12, 0.14, n)
    t0 = 2400
    if kind == "bubble_burst":
        mkt[t0 - 350:t0] = daily(0.55, 0.14, 350)            # a run-up
        mkt[t0:t0 + 70] = daily(-2.2, 0.30, 70)               # the burst
        mkt[t0 + 70:t0 + 400] = daily(-0.10, 0.22, 330)       # bleed
    elif kind == "v_crash":
        mkt[t0:t0 + 25] = daily(-4.5, 0.55, 25)
        mkt[t0 + 25:t0 + 130] = daily(1.6, 0.30, 105)
    elif kind == "grind_bear":
        mkt[t0:t0 + 400] = daily(-0.25, 0.20, 400)
    elif kind == "chop":
        mkt = daily(0.0, 0.16, n)
        mkt[1200:] += 0.12 * np.sin(np.arange(n - 1200) / 22) / 22
    px = {}
    for sym, a in settings.assets.items():
        if sym == "CASH":
            continue
        if a.sleeve in ("india_equity", "global_equity", "semis", "metals", "commodity"):
            beta = rng.uniform(0.7, 1.3)
            r = beta * mkt + daily(0.0, 0.10, n)
        elif a.sleeve == "gold":
            r = daily(0.06, 0.13, n) + 0.05 * (mkt < -0.02)
        elif sym == "HYG":
            r = 0.15 * mkt + daily(0.05, 0.02, n)
        else:
            r = daily(0.04, 0.03 if sym == "IEF" else 0.07, n)
        px[sym] = 100 * np.exp(np.cumsum(r))
    df = pd.DataFrame(px, index=idx)
    df["CASH"] = cash_series(idx, settings["cash"]["rate"])
    comp = pd.Series(mkt, index=idx).rolling(20).std() * np.sqrt(252)
    vix = (10 + 90 * comp.fillna(0.14).ewm(span=15).mean()).clip(10, 85)
    return df, vix
