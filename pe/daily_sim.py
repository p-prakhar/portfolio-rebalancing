"""What if you had run this engine every day and followed every decision?

Start: a lump sum split equally between the two Nifty 50 ETFs (NIFTYBEES and SETFNIF50). Each trading day the live
planner runs on prices up to that day only, and its orders are filled exactly as the live run would place them
(execution rule, costs, Indian tax paid each April). Compared with simply holding the two ETFs. Runs the last 10, 5
and 2 years, in parallel.
"""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from .config import ROOT, Lot

LUMP = 1_000_000


def _one(job: tuple) -> dict:
    import warnings
    warnings.filterwarnings("ignore")
    from .backtest import metrics, run_variant
    from .validate import load_long
    years, label, policy, freq, universe = job
    s, px, vix, closes = load_long(10)
    first = px.apply(lambda c: c.first_valid_index())
    px = px.ffill()          # holidays and dropped bad prints leave gaps; carry the last price, never back-fill before listing
    for c, d0 in first.items():
        if d0 is not None:
            px.loc[:d0 - pd.Timedelta(days=1), c] = np.nan
    if universe == "full":       # every instrument with prices may be picked, including single stocks
        for a in s.assets.values():
            if a.symbol != "CASH":
                a.rotate = True
    fx = closes[s["data"]["fx_ticker"]].reindex(px.index).ffill() if s["data"]["fx_ticker"] in closes else None
    end = px.index[-1]
    start = px.index[px.index >= end - pd.DateOffset(years=years)][0]
    s.raw["timing"]["check_frequency"] = freq
    lots = []
    for sym in ("NIFTYBEES", "SETFNIF50"):
        p0 = float(px.loc[start, sym])
        lots.append(Lot(sym, LUMP / 2 / p0, start.date(), p0))
    execution = s.timing["execution"] if policy != "buy_hold" else "immediate"
    nav, book, accrued, liq = run_variant(label, policy, execution, policy != "buy_hold", lots, px, vix, s, start, fx)
    m = metrics(nav, book, accrued, liq, s["cash"]["rate"])
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    after = m["after_tax_return_liquidated"]
    trades = [e for e in book.log if e[1] in ("BUY", "SELL")]
    decisions = [e for e in book.log if e[1] == "PLAN"]
    fills = [{"date": str(d), "side": k.lower(), "text": msg} for d, k, msg in book.log if k in ("BUY", "SELL", "TAX")]
    return {"years": years, "label": label, "policy": policy, "check": freq, "universe": universe, "journal": book.journal if freq == "daily" else [],
            "fills": fills if freq == "daily" else [], "start": str(start.date()), "end": str(end.date()),
            "final_value_after_tax": float(nav.iloc[-1] - liq), "cagr_after_tax": (1 + after) ** (1 / yrs) - 1 if after > -1 else None,
            "return_after_tax": after, "max_drawdown": m["max_drawdown"], "volatility": m["volatility"],
            "taxes_paid": m["taxes_paid"] + liq, "costs": m["costs"], "fills": len(trades), "decisions": len(decisions),
            "trade_days": len({str(e[0]) for e in trades}),
            "curve": {"dates": [str(d.date()) for d in nav.index[::3]], "values": [round(float(v)) for v in nav.iloc[::3]]}}


ALL_POLICIES = {"core_xs": "Core-satellite without core overlay", "core_satellite": "Core-satellite with trend overlay",
                "xs_momentum": "Cross-sectional momentum, top 3", "dual_momentum": "Dual momentum (Nifty/gold/cash)",
                "trend_vol": "Trend filter + volatility targeting", "risk_parity": "Risk parity", "daa": "Defensive asset allocation",
                "custom": "Keep holdings, exit on technicals", "static_mix": "Static mix 55/20/10/15", "rp_blend": "Half Nifty + half risk parity"}


def simulate_all(horizons=(10, 5, 2), workers: int = 10) -> dict:
    """Every strategy followed daily on the core universe, against just holding."""
    jobs = [(y, "Just hold the Nifty ETFs", "buy_hold", "monthly", "core") for y in horizons]
    jobs += [(y, name, pol, "daily", "core") for y in horizons for pol, name in ALL_POLICIES.items()]
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_one, jobs))
    for r in res:
        r["journal"], r["fills"] = [], []
    out = {"lump": LUMP, "run_on": str(date.today()), "results": res}
    (ROOT / "reports" / "daily_sim_all.json").write_text(json.dumps(out, default=str))
    L = ["# Every strategy, followed daily", "", "Same start and rules as the daily simulation: Rs 10 lakh in the two Nifty 50 ETFs, the engine run each day "
         "on data up to that day, every order followed, fees and tax included. Core universe. Gap = yearly return after tax minus just holding.", ""]
    for y in sorted(horizons, reverse=True):
        rows = [r for r in res if r["years"] == y]
        base = next(r for r in rows if r["policy"] == "buy_hold")
        L += [f"## Last {y} years", "", "| strategy | per year after tax | gap vs holding | worst fall | days with trades | beat holding? |", "|---|---|---|---|---|---|"]
        for r in sorted(rows, key=lambda r: -(r["cagr_after_tax"] or -9)):
            gap = (r["cagr_after_tax"] or 0) - base["cagr_after_tax"]
            L.append(f"| {r['label']} | {r['cagr_after_tax']:.1%} | {'-' if r is base else f'{gap * 100:+.1f}'} | {r['max_drawdown']:.1%} | {r['trade_days']} | "
                     f"{'-' if r is base else ('yes' if gap > 0 else 'no')} |")
        L.append("")
    (ROOT / "reports" / "daily_sim_all.md").write_text("\n".join(L))
    return out


def simulate(horizons=(10, 5, 2), policy: str | None = None, workers: int = 6) -> dict:
    from .config import load_settings
    pol = policy or load_settings().strategy["policy"]
    jobs = []
    for y in horizons:
        jobs += [(y, "Just hold the Nifty ETFs", "buy_hold", "monthly", "core"),
                 (y, "Follow daily, core universe", pol, "daily", "core"),
                 (y, "Follow monthly, core universe", pol, "monthly", "core"),
                 (y, "Follow daily, full universe", pol, "daily", "full"),
                 (y, "Follow monthly, full universe", pol, "monthly", "full")]
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_one, jobs))
    out = {"policy": pol, "lump": LUMP, "run_on": str(date.today()), "results": res}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "daily_sim.json").write_text(json.dumps(out, default=str))
    (ROOT / "reports" / "daily_sim.md").write_text(report(out))
    return out


def report(out: dict) -> str:
    L = ["# If you had followed the engine every day", "",
         f"Start: Rs {out['lump']:,.0f} split between NIFTYBEES and SETFNIF50. The engine ({out['policy']}) runs each day on data up to that day, "
         "and every order it gives is followed, with costs, Indian capital-gains tax paid each April, and tax on everything still held as if sold "
         "on the last day. Today's tax rules apply throughout.",
         "", "Core universe: the hand-picked ETF list the rotation normally uses. Full universe: every instrument with price data "
         "(metals, semiconductors, single stocks included); an instrument becomes eligible once it has about 13 months of history.", ""]
    for y in sorted({r["years"] for r in out["results"]}, reverse=True):
        rows = [r for r in out["results"] if r["years"] == y]
        base = next(r for r in rows if r["policy"] == "buy_hold")
        L += [f"## Last {y} years ({base['start']} to {base['end']})", "",
              "| approach | value after tax | per year after tax | worst fall | tax paid | fees | days with trades |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['label']} | Rs {r['final_value_after_tax']:,.0f} | {r['cagr_after_tax']:.1%} | {r['max_drawdown']:.1%} | Rs {r['taxes_paid']:,.0f} | Rs {r['costs']:,.0f} | {r['trade_days']} |")
        d = next(r for r in rows if r["check"] == "daily" and r["universe"] == "core")
        gap = d["cagr_after_tax"] - base["cagr_after_tax"]
        L += ["", f"Following it daily {'beat' if gap > 0 else 'trailed'} just holding by {abs(gap) * 100:.1f} points a year after tax, "
                  f"ending Rs {d['final_value_after_tax'] - base['final_value_after_tax']:+,.0f} {'ahead' if gap > 0 else 'behind'}.", ""]
    for r in out["results"]:
        if r["check"] != "daily" or not r["journal"] or r["years"] != min(x["years"] for x in out["results"]):
            continue
        L += [f"## Decision timeline: {r['label']}, last {r['years']} years", ""]
        for e in r["journal"]:
            acts = ", ".join(f"{t['side']} {t['symbol']} Rs {t['value']:,.0f}" for t in e["trades"])
            L.append(f"- **{e['date']}** ({e['regime'].replace('_', '-')}): {acts}. {e['trades'][0]['why'][0] if e['trades'][0]['why'] else ''}")
        L.append("")
    return "\n".join(L)
