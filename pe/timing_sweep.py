"""Compare ways of deciding WHEN to rebalance, on the same strategy, in the walk-forward simulation.

One strategy (the configured policy) is held fixed; only the timing rule changes, one thing at a time from a control
(monthly check, immediate fills, no band). Every variant runs through `validate.validate`, so costs, Indian tax, rolling
windows, the block bootstrap and the deflated Sharpe (which counts every variant here as a trial) all apply.
The base for "excess" is buy and hold, as in the main validation; the control row shows what the strategy itself adds,
so read each timing rule against the control, not against buy and hold.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import ROOT, load_settings
from .timing import dca_study, exec_study, kelly_fraction
from . import validate as V

POLICY = "core_xs"


def variants(policy: str = POLICY):
    H = ("Buy & hold (baseline)", "buy_hold", "immediate", False)
    mk = lambda name, ex="immediate", **o: (name, policy, ex, True, o)
    return [H,
            mk("CONTROL: monthly check, immediate fills", check="monthly"),
            mk("Calendar: daily check", check="daily"),
            mk("Calendar: weekly check", check="weekly"),
            mk("Calendar: quarterly", check="quarterly"),
            mk("Calendar: once a year in March", check="annual_mar"),
            mk("Band 5%: monthly check, act if plan moves 5%+", check="monthly", gate="band", gate_args={"width": 0.05}),
            mk("Band 10%", check="monthly", gate="band", gate_args={"width": 0.10}),
            mk("Cost-aware band (Rogers-Mayer), monthly", check="monthly", gate="cost_band"),
            mk("Cost-aware band, daily check", check="daily", gate="cost_band"),
            mk("Fill: secretary rule, 10 days", "secretary", check="monthly"),
            mk("Fill: threshold rule, 10 days", "threshold", check="monthly"),
            mk("Fill: TWAP, 10 days", "twap", check="monthly"),
            mk("Fill: TWAP, 21 days", "twap", check="monthly", window_days=21),
            mk("No wait for long-term status", check="monthly", ltcg_wait_max_days=0)]


def synthetic_long(settings, years: int = 12):
    from .data import synthetic_prices
    end = pd.Timestamp.today().normalize()
    return synthetic_prices(settings, start=str((end - pd.DateOffset(years=years)).date()), end=str(end.date()))


def price_studies(close: pd.Series) -> dict:
    p = close.dropna().to_numpy()
    r = np.diff(np.log(p))
    out = {"n_days": len(p), "exec": {s: exec_study(p, side=s) for s in ("buy", "sell")},
           "dca": {k: dca_study(p, tranches=k) for k in (3, 6, 12)}}
    mu, vol = float(r.mean() * 252), float(r.std() * 252 ** 0.5)
    out["kelly"] = {"mu": mu, "vol": vol, "half_kelly_on_mu": kelly_fraction(mu - 0.065, vol),
                    "half_kelly_mu_minus_2se": kelly_fraction(mu - 0.065 - 2 * vol / (len(r) / 252) ** 0.5, vol)}
    return out


def run(years: int = 10, demo: bool = False, refresh: bool = False) -> dict:
    s = load_settings()
    if demo:
        px, vix = synthetic_long(s, years + 2)
        closes = None
        data = (s, px, vix, pd.DataFrame())
    else:
        data = None
    res = V.validate(years=years, variants=variants(), data=data, refresh=refresh)
    res["price_studies"] = price_studies((data[1] if data else V.load_long(years)[1])["NIFTYBEES"])
    res["demo"] = demo
    return res


def report(res: dict) -> str:
    base = res_base = "Buy & hold (baseline)"
    L = ["# When to rebalance: timing rules compared", ""]
    if res.get("demo"):
        L += ["> **Synthetic random-walk prices.** Code check only; these numbers say nothing about real markets.", ""]
    L += [V.report(res, base), ""]
    ps = res["price_studies"]
    L += ["## Fill rules on Nifty prices, order by order", "",
          f"{ps['n_days']} trading days; 10-day windows, a new order every 5 days. Basis points better than filling at once "
          "(positive is better), with a 90% bootstrap range. Before cost and tax.", ""]
    for side, e in ps["exec"].items():
        L += [f"**{side}s** ({e['orders']} orders)", "", "| rule | mean | 90% range | worst order | spread (sd) |", "|---|---|---|---|---|"]
        for r, v in e["rules"].items():
            L.append(f"| {r} | {v['mean_bp']:+.1f} | {v['lo']:+.1f} to {v['hi']:+.1f} | {v['worst_bp']:+.0f} | {v['sd_bp']:.0f} |")
        L += ["", "Bandit picks: " + ", ".join(f"{k} {v:.0%}" for k, v in e["bandit_picks"].items()), ""]
    L += ["## Lump sum or staged entry (before cost and tax)", "", "| tranches | months | lump sum ahead | average edge of lump | 90% range | samples |", "|---|---|---|---|---|---|"]
    for k, d in ps["dca"].items():
        L.append(f"| {k} | {d['months']:.0f} | {d['lump_wins']:.0%} of starts | {d['mean_edge']:+.2%} | {d['lo']:+.2%} to {d['hi']:+.2%} | {d['samples']} |")
    k = ps["kelly"]
    L += ["", "## Sizing, not timing: half Kelly", "",
          f"Nifty over this history: {k['mu']:.1%} a year at {k['vol']:.1%} volatility. Half Kelly against a 6.5% cash rate says "
          f"{k['half_kelly_on_mu']:.0%} in equity; after subtracting two standard errors from the mean return, {k['half_kelly_mu_minus_2se']:.0%}. "
          "The answer swings with an estimate that ten years cannot pin down, which is why it is context and not a rule here."]
    return "\n".join(L)


def save(res: dict) -> None:
    d = ROOT / "reports"
    d.mkdir(exist_ok=True)
    (d / "timing.json").write_text(json.dumps(res, default=str))
    (d / "timing.md").write_text(report(res) + "\n")
