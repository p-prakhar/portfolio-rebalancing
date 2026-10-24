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
    years, label, policy, freq = job
    s, px, vix, closes = load_long(10)
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
    return {"years": years, "label": label, "policy": policy, "check": freq, "start": str(start.date()), "end": str(end.date()),
            "final_value_after_tax": float(nav.iloc[-1] - liq), "cagr_after_tax": (1 + after) ** (1 / yrs) - 1 if after > -1 else None,
            "return_after_tax": after, "max_drawdown": m["max_drawdown"], "volatility": m["volatility"],
            "taxes_paid": m["taxes_paid"] + liq, "costs": m["costs"], "fills": len(trades), "decisions": len(decisions),
            "trade_days": len({str(e[0]) for e in trades}),
            "curve": {"dates": [str(d.date()) for d in nav.index[::3]], "values": [round(float(v)) for v in nav.iloc[::3]]}}


def simulate(horizons=(10, 5, 2), policy: str | None = None, workers: int = 6) -> dict:
    from .config import load_settings
    pol = policy or load_settings().strategy["policy"]
    jobs = []
    for y in horizons:
        jobs += [(y, "Just hold the Nifty ETFs", "buy_hold", "monthly"),
                 (y, f"Follow the engine daily ({pol})", pol, "daily"),
                 (y, f"Follow the engine monthly ({pol})", pol, "monthly")]
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
         "on the last day. Today's tax rules apply throughout.", ""]
    for y in sorted({r["years"] for r in out["results"]}, reverse=True):
        rows = [r for r in out["results"] if r["years"] == y]
        base = next(r for r in rows if r["policy"] == "buy_hold")
        L += [f"## Last {y} years ({base['start']} to {base['end']})", "",
              "| approach | value after tax | per year after tax | worst fall | tax paid | fees | days with trades |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['label']} | Rs {r['final_value_after_tax']:,.0f} | {r['cagr_after_tax']:.1%} | {r['max_drawdown']:.1%} | Rs {r['taxes_paid']:,.0f} | Rs {r['costs']:,.0f} | {r['trade_days']} |")
        d = next(r for r in rows if r["check"] == "daily")
        gap = d["cagr_after_tax"] - base["cagr_after_tax"]
        L += ["", f"Following it daily {'beat' if gap > 0 else 'trailed'} just holding by {abs(gap) * 100:.1f} points a year after tax, "
                  f"ending Rs {d['final_value_after_tax'] - base['final_value_after_tax']:+,.0f} {'ahead' if gap > 0 else 'behind'}.", ""]
    return "\n".join(L)
