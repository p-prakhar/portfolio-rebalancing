"""Generic after-tax cash-flow framework for any asset class, plus the merged universe report.

One function, `evaluate`, handles every class in config/asset_classes.yaml: entry/exit costs,
running costs, income (paid out or accruing, taxed at slab / exempt / partly exempt), credit
losses, currency drift for USD assets, LRS TCS lock-up, annual caps, and the class's
capital-gains rule. Specialised frameworks (Dubai flat, farmland, physical gold) live in
realassets.py and are merged in so the whole universe sits in one ranked table.
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from . import realassets
from .config import ROOT
from .realassets import Result, irr


def load(path=None) -> dict:
    return yaml.safe_load(open(path or ROOT / "config" / "asset_classes.yaml"))


def _val(x, scen: dict, name: str):
    if isinstance(x, dict):
        return x[name]
    if isinstance(x, str):
        return scen[x]
    return x or 0.0


def _gains_rate(rule: str, years: int, slab: float) -> float:
    return {"equity": 0.125 if years > 1 else 0.20,
            "listed_12m": 0.125 if years > 1 else slab,
            "unlisted_24m": 0.125 if years > 2 else slab,
            "slab": slab, "crypto": 0.30, "exempt": 0.0}[rule]


def evaluate(spec: dict, scen: dict, scen_name: str, years: int, amount: float, slab: float, cess: float = 0.04,
             disc: float = 0.07) -> Result:
    notes, warns = [], []
    a = amount
    cap = spec.get("cap_inr_per_year")
    if cap and a > cap:
        notes.append(f"Capped at Rs {cap:,.0f} a year; modelled as a single Rs {cap:,.0f} contribution.")
        a = cap
    slab_eff = spec.get("slab_override", slab)
    g = _val(spec.get("growth", 0.0), scen, scen_name)
    if spec.get("currency") == "USD":
        g = (1 + g) * (1 + scen["inr_vs_usd"]) - 1
    y = spec.get("income_yield", 0.0)
    itax = spec.get("income_tax", "none")
    share = float(itax.split(":")[1]) if isinstance(itax, str) and itax.startswith("mixed") else (1.0 if itax == "slab" else 0.0)
    v = a * (1 - spec.get("entry_cost_pct", 0.0))
    basis = a
    flows = [-a]
    tcs = 0.0
    if spec.get("currency") == "USD" and not spec.get("no_tcs"):
        tcs = max(0.0, a - 1_000_000) * 0.20
        flows[0] -= tcs
    for t in range(1, years + 1):
        v0 = v
        inc = y * (a if spec.get("income_basis") == "principal" else v0)
        v = v0 * (1 + g - spec.get("annual_cost_pct", 0.0) - spec.get("credit_loss", 0.0))
        tax = inc * share * slab_eff * (1 + cess)
        cf = -spec.get("annual_cost_inr", 0.0)
        if spec.get("income_paid", True):
            cf += inc - tax
        else:
            v += inc
            basis += inc if share > 0 else 0.0     # interest already taxed on accrual isn't taxed again at exit
            cf -= tax
        if t == 1:
            cf += tcs
        flows.append(cf)
    sale = v * (1 - spec.get("exit_cost_pct", 0.0))
    gain = sale - basis
    rate = _gains_rate(spec.get("gains_tax", "exempt"), years, slab)
    gtax = max(0.0, gain) * rate * (1 + cess)
    flows[-1] += sale - gtax
    if spec.get("gains_tax") == "crypto":
        notes.append("Crypto: 30% + cess on gains, losses can't offset anything, 1% TDS on each sale (refundable as credit).")
    y1 = flows[1] / a if years else 0.0
    return Result(spec["name"], a, flows, spec.get("entry_cost_pct", 0.0), y1, notes, warns,
                  {"exit_tax": gtax, "group": spec["group"], "key": spec["key"], "eligible": spec.get("eligible", ""),
                   "min_ticket": spec.get("min_ticket", 0), "turbulence": spec.get("turbulence", ""),
                   "round_trip": spec.get("entry_cost_pct", 0.0) + spec.get("exit_cost_pct", 0.0)},
                  spec.get("liquidity", ""))


@dataclass
class Row:
    group: str
    name: str
    irr: dict
    round_trip: float
    liquidity: str
    min_ticket: float
    eligible: str
    turbulence: str
    result: Result


def universe(ac: dict | None = None, ra: dict | None = None, city_premium: float = 0.0) -> dict:
    ac = ac or load()
    ra = ra or realassets.load()
    years = ra["common"]["horizon_years"]
    slab = ra["common"]["slab_rate"]
    rows: list[Row] = []
    for spec in ac["classes"]:
        res = {s: evaluate(spec, sc, s, years, ac["amount_inr"], slab) for s, sc in ac["scenarios"].items()}
        b = res["base"]
        rows.append(Row(spec["group"], spec["name"], {s: r.irr for s, r in res.items()}, b.breakdown["round_trip"],
                        b.liquidity, spec.get("min_ticket", 0), spec.get("eligible", ""), spec.get("turbulence", ""), b))
    # specialised frameworks, run under the matching scenario numbers
    sp = realassets.compare(ra, city_premium)
    for i, r in enumerate(sp["scenarios"]["base"]):
        if r.name.startswith("Nifty"):
            continue
        irrs = {s: sp["scenarios"][s][i].irr for s in sp["scenarios"]}
        grp = "Real estate" if ("apartment" in r.name or "farmland" in r.name) else "Commodities"
        elig = "; ".join(r.warnings) or "yes"
        min_t = r.invested if grp == "Real estate" else 1000
        rows.append(Row(grp, r.name, irrs, r.upfront_friction, r.liquidity, min_t, elig[:160], "", r))
    eq = next(r for r in rows if r.result.breakdown.get("key") == "nifty_etf")
    return {"rows": rows, "equity": eq, "specialised": sp, "years": years, "amount": ac["amount_inr"]}


def universe_report(u: dict, budget: float = 1_700_000) -> str:
    from .report import DISCLAIMER
    rows, years = u["rows"], u["years"]
    eq = u["equity"].irr["base"]
    out = [f"# Every asset class, after tax and costs ({years}-year view)", "",
           f"Each line is a Rs {u['amount'] / 1e5:.0f} lakh ticket (or the asset's real size when it can't be bought smaller), "
           "held for the full period. It includes entry and exit costs, running costs, credit losses, currency, TCS lock-up, and "
           "Indian tax on income and gains (30% slab). Scenarios and every assumption are in `config/asset_classes.yaml` "
           "and `config/real_assets.yaml`. Ranked by base-case after-tax IRR within each group.", "",
           "**Bear** = a turbulent decade: weak equities, the rupee sliding 5%/yr, gold up, property flat, crypto down.", ""]
    groups = list(dict.fromkeys(r.group for r in rows))
    for gname in groups:
        out += [f"## {gname}", "", "| asset | base | bear | bull | vs Nifty (base) | round-trip cost | liquidity | min ticket | can you use it? | in turbulence |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted([r for r in rows if r.group == gname], key=lambda r: -(r.irr["base"] if r.irr["base"] == r.irr["base"] else -9)):
            mt = f"Rs {r.min_ticket:,.0f}" if r.min_ticket else "-"
            out.append(f"| {r.name} | {r.irr['base']:+.1%} | {r.irr['bear']:+.1%} | {r.irr['bull']:+.1%} | {r.irr['base'] - eq:+.1%} | "
                       f"{r.round_trip:.1%} | {r.liquidity} | {mt} | {r.eligible} | {r.turbulence} |")
        out.append("")
    usable = [r for r in rows if r.min_ticket <= budget and "not recommended" not in r.eligible and "needs" not in r.eligible.lower()
              and "Warning" not in r.eligible and r.irr["base"] == r.irr["base"]]
    best_base = sorted(usable, key=lambda r: -r.irr["base"])[:6]
    best_bear = sorted(usable, key=lambda r: -r.irr["bear"])[:6]
    out += ["## Shortlist at your size", "",
            "**Highest expected after-tax return (base):** " + ", ".join(f"{r.name} ({r.irr['base']:+.1%})" for r in best_base) + ".", "",
            "**Most resilient in a turbulent decade (bear):** " + ", ".join(f"{r.name} ({r.irr['bear']:+.1%})" for r in best_bear) + ".", "",
            "The two lists barely overlap, which is the case for a mix: equity for growth, plus a defensive block (gold, "
            "sovereign/tax-free debt, PPF/VPF) that does well when equity doesn't. The main engine's overlays decide how much "
            "sits in each at any time.", ""]
    out += ["## How to read the IRRs", "",
            "- They are forecasts under stated assumptions, not predictions. Change a scenario number and re-run "
            "(`python main.py real-assets`) to see sensitivity.",
            "- Debt and deposit IRRs are close to certain; equity, property, gold and crypto IRRs are not. Compare the *bear* "
            "column when deciding how much risk to take.",
            "- Caps matter: PPF (Rs 1.5 lakh/yr), VPF (Rs 2.5 lakh/yr tax-free), SFB FDs (Rs 5 lakh insured per bank), P2P (Rs 50 lakh).", ""]
    out += ["## Detailed frameworks", ""]
    for r in u["specialised"]["scenarios"]["base"]:
        if r.name.startswith("Nifty"):
            continue
        out.append(f"### {r.name}\n")
        out += [f"- **Warning:** {w}" for w in r.warnings]
        out += [f"- {n}" for n in r.notes]
        out.append("")
    out.append("Breakeven growth each needs to match Nifty: " + "; ".join(
        f"{k} {v:+.1%}/yr" for k, v in u["specialised"]["breakeven"].items() if v == v) + ".\n")
    out.append(f"---\n_{DISCLAIMER}_\n")
    return "\n".join(out)
