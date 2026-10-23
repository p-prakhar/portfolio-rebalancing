"""Frameworks for non-market assets: Dubai property, Indian farmland, physical gold.

Each framework turns its own economics (fees, carrying costs, tax rules, currency, liquidity)
into one yearly after-tax INR cash-flow stream, so everything is comparable with a Nifty ETF
on the same footing: IRR, terminal wealth, upfront and round-trip friction, and the growth
rate the asset needs just to match equity ("breakeven").
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import yaml

from .config import ROOT

USD_PER_AED = 1 / 3.6725


@dataclass
class Result:
    name: str
    invested: float
    flows: list[float]                    # t = 0..N, INR, after tax; flows[0] is negative
    upfront_friction: float               # % of the money put in that is lost on day one
    year1_cash_yield: float
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)
    liquidity: str = ""

    @property
    def irr(self) -> float:
        return irr(self.flows)

    @property
    def multiple(self) -> float:
        return sum(self.flows[1:]) / -self.flows[0]


def irr(flows: list[float]) -> float:
    def npv(r):
        return sum(f / (1 + r) ** t for t, f in enumerate(flows))
    lo, hi = -0.99, 1.0
    if npv(lo) * npv(hi) > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def load(path=None) -> dict:
    return yaml.safe_load(open(path or ROOT / "config" / "real_assets.yaml"))


def _tax_mult(c):
    return 1 + c["cess"]


# ---------------------------------------------------------------- equity yardstick
def equity(cfg: dict, growth: float) -> Result:
    c, e = cfg["common"], cfg["equity_benchmark"]
    n, a = c["horizon_years"], e["amount_inr"]
    v, basis = a * (1 - e["cost_pct"] / 2), a
    harvested = 0.0
    for _ in range(n):
        v *= 1 + growth
        if e.get("harvest_exemption_yearly"):
            step = min(e["exemption"], max(0.0, v - basis))
            basis += step
            harvested += step
    sale = v * (1 - e["cost_pct"] / 2)
    tax = max(0.0, sale - basis - e["exemption"]) * c["ltcg_rate"] * _tax_mult(c)
    flows = [-a] + [0.0] * (n - 1) + [sale - tax]
    return Result("Nifty 50 ETF (buy & hold)", a, flows, e["cost_pct"] / 2, 0.0,
                  notes=[f"Exit tax Rs {tax:,.0f} after harvesting Rs {harvested:,.0f} of gains tax-free over the years."],
                  breakdown={"exit_tax": tax}, liquidity="T+1, any amount")


# ---------------------------------------------------------------- Dubai flat
def dubai_flat(cfg: dict, price_growth: float, inr_dep: float) -> Result:
    c, d = cfg["common"], cfg["dubai_flat"]
    n, p0, fx0 = c["horizon_years"], d["price_aed"], d["aed_inr"]
    pu = d["purchase"]
    capitalised = (p0 * pu["dld_pct"] + pu["dld_admin_aed"] + pu["trustee_aed"] + pu["title_deed_aed"]
                   + p0 * pu["agent_pct"] * 1.05 + pu["conveyancing_aed"])
    entry_aed = capitalised + pu["furnishing_aed"]
    outlay_inr = (p0 + entry_aed) * fx0 * (1 + d["remittance_fx_pct"])
    per_buyer = outlay_inr / d["buyers"]
    tcs = max(0.0, per_buyer - 1_000_000) * 0.20 * d["buyers"]
    warnings, notes = [], []
    usd_needed = (p0 + entry_aed) * USD_PER_AED
    if usd_needed > d["lrs_limit_usd_per_person"] * d["buyers"]:
        warnings.append(f"Needs about USD {usd_needed:,.0f}, more than the LRS limit of USD {d['lrs_limit_usd_per_person']:,} per person per "
                        f"year x {d['buyers']} buyer(s). You would need co-buyers in the family or to spread payments across financial "
                        "years. Resident Indians generally can't take a foreign mortgage for this, so plan for cash or a developer payment plan; "
                        "confirm with your bank's LRS desk.")
    flows = [-(outlay_inr + tcs)]
    y1 = None
    tax_total = 0.0
    for t in range(1, n + 1):
        price_prev = p0 * (1 + price_growth) ** (t - 1)
        rent = d["gross_yield"] * price_prev * (12 - d["vacancy_months"]) / 12
        costs = (d["service_charge_aed_sqft"] * d["size_sqft"] * 1.02 ** (t - 1) + rent * d["management_pct_of_rent"] * 1.05
                 + d["maintenance_aed"] * 1.03 ** (t - 1) + d["insurance_aed"])
        fx = fx0 * (1 + inr_dep) ** t
        net_inr = (rent - costs) * fx * (1 - (d["remittance_fx_pct"] if d["rent_repatriated"] else 0))
        tax = 0.7 * rent * fx * c["slab_rate"] * _tax_mult(c)   # house property: 30% standard deduction; service charges not deductible
        tax_total += tax
        cf = net_inr - tax
        if t == 1:
            cf += tcs                                              # TCS comes back as a credit when you file
            y1 = (net_inr - tax) / outlay_inr
        flows.append(cf)
    pn = p0 * (1 + price_growth) ** n
    fxn = fx0 * (1 + inr_dep) ** n
    sale_aed = pn * (1 - d["selling"]["agent_pct"] * 1.05) - d["selling"]["noc_aed"]
    sale_inr = sale_aed * fxn
    gain = sale_inr - (p0 + capitalised) * fx0
    rate = c["ltcg_rate"] if n >= 2 else c["slab_rate"]
    cg_tax = max(0.0, gain) * rate * _tax_mult(c)
    flows[-1] += sale_inr * (1 - d["remittance_fx_pct"]) - cg_tax
    gross = d["gross_yield"]
    net_y = (gross * p0 * (12 - d["vacancy_months"]) / 12 - d["service_charge_aed_sqft"] * d["size_sqft"]
             - gross * p0 * d["management_pct_of_rent"] * 1.05 - d["maintenance_aed"] - d["insurance_aed"]) / (p0 + entry_aed)
    notes += [f"Gross yield {gross:.2%} becomes {net_y:.2%} net of vacancy, service charges, management and upkeep on the all-in cost, "
              f"and about {y1:.2%} after Indian tax on the rent.",
              "The UAE doesn't tax rent, so as an Indian resident you pay Indian slab tax on 70% of it (30% standard deduction); "
              "service charges are not deductible.",
              f"Sale after {n} years: Indian LTCG at 12.5% + cess on the INR gain, including the currency gain (Rs {cg_tax:,.0f} in this scenario). "
              "Report the flat in Schedule FA every year."]
    if tcs:
        notes.append(f"TCS of Rs {tcs:,.0f} is collected on the remittance and refunded as a tax credit about a year later.")
    return Result(d["name"], outlay_inr, flows, entry_aed / (p0 + entry_aed), y1, notes, warnings,
                  {"entry_costs_aed": entry_aed, "rent_tax_total": tax_total, "cg_tax": cg_tax, "tcs": tcs},
                  "2-6 months to sell; AED-denominated (USD-pegged), so it partly hedges the rupee")


# ---------------------------------------------------------------- Indian farmland
def farmland(cfg: dict, state: str, growth: float) -> Result:
    c, f = cfg["common"], cfg["agricultural_land"][state]
    n = c["horizon_years"]
    land = f["price_per_acre_inr"] * f["acres"]
    entry = land * (f["stamp_duty_pct"] + f["registration_pct"]) + f["legal_survey_inr"]
    capex = f["fencing_borewell_inr"]
    outlay = land + entry + capex
    flows = [-outlay]
    for t in range(1, n + 1):
        flows.append(f["lease_income_per_acre_inr"] * f["acres"] * 1.04 ** (t - 1) - f["annual_costs_inr"] * 1.05 ** (t - 1))
    sale = land * (1 + growth) ** n * (1 - f["selling_cost_pct"])
    tax = 0.0
    if not f["rural"]:
        gain = sale - outlay
        tax = max(0.0, gain) * (c["ltcg_rate"] if n >= 2 else c["slab_rate"]) * _tax_mult(c)
    delay = (1 + c["discount_rate"]) ** (f["months_to_sell"] / 12)
    flows[-1] += (sale - tax) / delay
    notes = [f"Upfront: stamp duty + registration {f['stamp_duty_pct'] + f['registration_pct']:.1%} (Rs {land * (f['stamp_duty_pct'] + f['registration_pct']):,.0f}), "
             f"title search/survey Rs {f['legal_survey_inr']:,.0f}, fencing/borewell Rs {capex:,.0f}.",
             "Lease income from farming is agricultural income, which is exempt (it can still push up the rate on your other income above Rs 5,000).",
             ("Rural agricultural land (beyond 2/6/8 km of a municipality, depending on its population) is not a capital asset, so the sale is tax-free."
              if f["rural"] else f"Urban agricultural land is a capital asset: LTCG 12.5% + cess after 24 months (Rs {tax:,.0f} here)."),
             f"Selling typically takes ~{f['months_to_sell']} months; the model discounts proceeds for that wait.",
             f"Can you buy it? {f['can_buy']}"]
    warnings = []
    if f["can_buy"].lower().startswith(("uncertain", "no")):
        warnings.append(f"{state.title()}: ownership by a non-agriculturist may not be permitted. Check this before anything else.")
    y1 = flows[1] / outlay
    return Result(f["name"], outlay, flows, (entry + capex) / outlay, y1, notes, warnings,
                  {"entry_costs": entry, "capex": capex, "exit_tax": tax},
                  f"illiquid: ~{f['months_to_sell']} months to sell; title and encroachment risk")


# ---------------------------------------------------------------- physical gold
def physical_gold(cfg: dict, form: str, growth: float, price_premium: float = 0.0) -> Result:
    """price_premium: how much dearer the chosen city's rate is than the reference (e.g. +0.01)."""
    c, g = cfg["common"], cfg["physical_gold"]
    n, a = c["horizon_years"], g["amount_inr"]
    fm = g["forms"][form]
    m = fm["making_pct"]
    per_rupee_gold = 1 / ((1 + price_premium) * (1 + m + g["gst_gold_pct"] + g["gst_making_pct"] * m))
    gold_value = a * per_rupee_gold
    flows = [-a]
    for t in range(1, n + 1):
        v = gold_value * (1 + growth) ** t
        flows.append(-(g["locker_rent_inr"] * (1 + g["locker_gst_pct"]) * 1.05 ** (t - 1) + v * g["insurance_pct"]))
    sale = gold_value * (1 + growth) ** n * (1 - fm["buyback_haircut_pct"])
    gain = sale - a
    tax = max(0.0, gain) * (c["ltcg_rate"] if n > 2 else c["slab_rate"]) * _tax_mult(c)
    flows[-1] += sale - tax
    locker = g["locker_rent_inr"] * (1 + g["locker_gst_pct"])
    notes = [f"Of every Rs 100 spent, about Rs {100 * per_rupee_gold:.1f} is metal: making charges {m:.0%}, GST 3% on gold and 5% on making"
             + (f", city premium {price_premium:+.1%}" if price_premium else "") + ".",
             f"Locker Rs {locker:,.0f}/yr incl. 18% GST is {locker / a:.2%} of a Rs {a / 1e5:.0f} lakh holding a year; "
             "the bank doesn't insure locker contents, so add insurance if you want cover.",
             f"On resale a jeweller deducts about {fm['buyback_haircut_pct']:.0%}"
             + (" and the making charge is lost." if form == "jewellery" else "."),
             "Tax: physical gold is long term after 24 months (12.5% + cess); before that, your slab rate."]
    return Result(f"Physical gold ({form})", a, flows, 1 - per_rupee_gold, flows[1] / a, notes, [],
                  {"metal_value": gold_value, "exit_tax": tax}, "same day at a jeweller, but at a haircut")


def gold_etf(cfg: dict, growth: float) -> Result:
    c, g = cfg["common"], cfg["physical_gold"]
    n, a = c["horizon_years"], g["amount_inr"]
    e = g["gold_etf"]
    v = a * (1 - e["spread_pct"]) * ((1 + growth) * (1 - e["expense_pct"])) ** n * (1 - e["spread_pct"])
    tax = max(0.0, v - a) * c["ltcg_rate"] * _tax_mult(c)
    flows = [-a] + [0.0] * (n - 1) + [v - tax]
    return Result("Gold ETF (e.g. GOLDBEES)", a, flows, e["spread_pct"], 0.0,
                  [f"No making charges, GST or locker; expense ratio about {e['expense_pct']:.2%}/yr. Long term after 12 months at 12.5%."],
                  [], {"exit_tax": tax}, "T+1, any amount")


# ---------------------------------------------------------------- comparison
def _with(cfg, **over):
    c = copy.deepcopy(cfg)
    for k, v in over.items():
        c["common"][k] = v
    return c


def _breakeven(fn, target: float, lo=-0.2, hi=0.4) -> float:
    f = lambda g: fn(g).irr - target
    if f(lo) * f(hi) > 0:
        return float("nan")
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def compare(cfg: dict, city_premium: float = 0.0) -> dict:
    out = {}
    for sc, s in cfg["common"]["scenarios"].items():
        res = [equity(cfg, s["equity"]),
               dubai_flat(cfg, s["dubai_price"], s["inr_vs_aed"]),
               *[farmland(cfg, st, s["farmland"]) for st in cfg["agricultural_land"]],
               *[physical_gold(cfg, f, s["gold_inr"], city_premium) for f in cfg["physical_gold"]["forms"]],
               gold_etf(cfg, s["gold_inr"])]
        out[sc] = res
    base = cfg["common"]["scenarios"]["base"]
    eq = equity(cfg, base["equity"]).irr
    be = {"Dubai flat (AED price growth)": _breakeven(lambda g: dubai_flat(cfg, g, base["inr_vs_aed"]), eq)}
    for st in cfg["agricultural_land"]:
        be[f"Farmland {st} (land price growth)"] = _breakeven(lambda g, st=st: farmland(cfg, st, g), eq)
    be["Physical gold coin (INR gold growth)"] = _breakeven(lambda g: physical_gold(cfg, "coin", g, city_premium), eq)
    be["Gold ETF (INR gold growth)"] = _breakeven(lambda g: gold_etf(cfg, g), eq)
    return {"scenarios": out, "breakeven": be, "equity_irr": eq}
