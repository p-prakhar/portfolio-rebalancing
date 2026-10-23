"""Indian capital-gains tax engine for listed equity, gold/intl ETFs, debt funds and foreign shares.

Rules modelled (resident individual, post 23-Jul-2024 regime; verify with a CA):
  in_equity  : LT if held > 12m. STCG 20% (111A). LTCG 12.5% above Rs 1.25L/FY (112A).
  in_other   : gold/silver/international ETFs. LT if held > 12m, LTCG 12.5%, STCG at slab.
  foreign    : shares/ETFs listed abroad. LT if held > 24m, LTCG 12.5%, STCG at slab.
  in_debt    : specified mutual funds (liquid/debt). Always slab.
Set-off: short-term losses offset any gain, long-term losses offset only long-term gains.
Gains are measured in INR (buy and sell converted at the respective dates' rates).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from .config import Lot, Settings

BUCKETS = ("eq_st", "eq_lt", "oth_st", "oth_lt", "debt")


def fy_start_year(d: date, fy_start_month: int = 4) -> int:
    return d.year if d.month >= fy_start_month else d.year - 1


def fy_end(d: date, fy_start_month: int = 4) -> date:
    y = fy_start_year(d, fy_start_month) + 1
    return date(y, fy_start_month, 1) - relativedelta(days=1)


def lt_date(lot: Lot, tax_class: str, settings: Settings) -> date | None:
    """First date on which a sale of this lot is long term (None = never)."""
    months = settings.tax["holding_months"].get(tax_class)
    if months is None:
        return None
    return lot.buy_date + relativedelta(months=months) + relativedelta(days=1)


def is_long_term(lot: Lot, tax_class: str, sell_date: date, settings: Settings) -> bool:
    d = lt_date(lot, tax_class, settings)
    return d is not None and sell_date >= d


def bucket_for(tax_class: str, long_term: bool) -> str:
    if tax_class == "in_debt":
        return "debt"
    if tax_class == "in_equity":
        return "eq_lt" if long_term else "eq_st"
    return "oth_lt" if long_term else "oth_st"


def empty_buckets() -> dict[str, float]:
    return {b: 0.0 for b in BUCKETS}


@dataclass
class TaxResult:
    tax: float
    taxable: dict
    exemption_used: float
    carry_forward_st_loss: float
    carry_forward_lt_loss: float


def compute_tax(gains: dict[str, float], settings: Settings) -> TaxResult:
    """Tax on one FY's net realised gains by bucket, applying set-off and the 112A exemption."""
    t = settings.tax
    slab = t["slab_rate"]
    g = {b: float(gains.get(b, 0.0)) for b in BUCKETS}
    st_loss = -sum(min(0.0, g[b]) for b in ("eq_st", "oth_st", "debt"))
    lt_loss = -sum(min(0.0, g[b]) for b in ("eq_lt", "oth_lt"))
    pos = {b: max(0.0, v) for b, v in g.items()}
    slab_gain = pos["oth_st"] + pos["debt"]

    def absorb(amount, loss):
        used = min(amount, loss)
        return amount - used, loss - used

    # LT losses: oth_lt first (no exemption there), then eq_lt.
    pos["oth_lt"], lt_loss = absorb(pos["oth_lt"], lt_loss)
    pos["eq_lt"], lt_loss = absorb(pos["eq_lt"], lt_loss)
    # ST losses: highest-taxed gains first.
    order = sorted([("slab", slab), ("eq_st", t["equity_stcg_rate"])], key=lambda x: -x[1])
    for name, _ in order:
        if name == "slab":
            slab_gain, st_loss = absorb(slab_gain, st_loss)
        else:
            pos["eq_st"], st_loss = absorb(pos["eq_st"], st_loss)
    pos["oth_lt"], st_loss = absorb(pos["oth_lt"], st_loss)
    # Use ST loss on eq_lt only for the part above the exemption.
    above = max(0.0, pos["eq_lt"] - t["ltcg_exemption"])
    used = min(above, st_loss)
    pos["eq_lt"] -= used
    st_loss -= used

    exemption_used = min(pos["eq_lt"], t["ltcg_exemption"])
    eq_lt_taxable = pos["eq_lt"] - exemption_used
    base = (pos["eq_st"] * t["equity_stcg_rate"] + eq_lt_taxable * t["equity_ltcg_rate"]
            + pos["oth_lt"] * t["other_ltcg_rate"] + slab_gain * slab)
    tax = base * (1 + t.get("surcharge", 0.0)) * (1 + t["cess"])
    taxable = {"eq_st": pos["eq_st"], "eq_lt": eq_lt_taxable, "oth_lt": pos["oth_lt"], "slab": slab_gain}
    return TaxResult(tax, taxable, exemption_used, st_loss, lt_loss)


def marginal_tax(base_gains: dict[str, float], extra: dict[str, float], settings: Settings) -> float:
    """Extra tax caused by adding `extra` realised gains to the FY's existing `base_gains`."""
    combined = {b: base_gains.get(b, 0.0) + extra.get(b, 0.0) for b in BUCKETS}
    return compute_tax(combined, settings).tax - compute_tax(base_gains, settings).tax


def effective_rate(bucket: str, settings: Settings) -> float:
    t = settings.tax
    mult = (1 + t.get("surcharge", 0.0)) * (1 + t["cess"])
    return mult * {"eq_st": t["equity_stcg_rate"], "eq_lt": t["equity_ltcg_rate"],
                   "oth_lt": t["other_ltcg_rate"], "oth_st": t["slab_rate"], "debt": t["slab_rate"]}[bucket]


def economic_tax_cost(gain: float, bucket: str, now_tax: float, settings: Settings) -> float:
    """What realising a gain now really costs versus deferring it.

    Paying tax now is partly just paying a bill early: if you would otherwise sell in
    ~N years at the long-term rate, the true cost is now_tax - PV(future LT tax).
    A negative gain (loss) yields a negative cost, i.e. a benefit.
    """
    t = settings.tax
    n, r = t["default_deferral_years"], t["discount_rate"]
    if gain <= 0:
        return now_tax  # usually <= 0: harvested loss lowers this year's tax
    future_bucket = "debt" if bucket == "debt" else ("eq_lt" if bucket.startswith("eq") else "oth_lt")
    future = gain * effective_rate(future_bucket, settings) / (1 + r) ** n
    return now_tax - future
