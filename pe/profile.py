"""Investor profile (age, risk appetite, employer stock) and investments the engine cannot trade.

Profile and non-tradable assets are stored in config/profile.yaml and config/other_assets.yaml
(both git-ignored). They never change what the planner trades; they set guardrails (equity share,
single-stock concentration, emergency fund) that the report checks the plan against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ROOT

PROFILE_PATH = ROOT / "config" / "profile.yaml"
OTHER_PATH = ROOT / "config" / "other_assets.yaml"
RISK_LEVELS = ("conservative", "moderate", "aggressive")
RISK_TILT = {"conservative": -15, "moderate": 0, "aggressive": 15}

# kind -> (asset class, where to find the number, liquid within a week?)
KINDS: dict[str, tuple[str, str, bool]] = {
    "mutual_fund_equity": ("equity", "CAMS/KFin consolidated statement, mfcentral.com (free CAS by email), or Kite Coin > Holdings", True),
    "mutual_fund_debt": ("debt", "Same consolidated statement (mfcentral.com) or your AMC/Coin app", True),
    "fixed_deposit": ("debt", "Bank app > Deposits (principal, rate, maturity date)", False),
    "ppf": ("debt", "Bank/post office passbook or net banking > PPF account balance", False),
    "epf": ("debt", "EPFO member passport (passbook.epfindia.gov.in) or the UMANG app > EPF passbook", False),
    "nps": ("mixed", "NSDL/KFin CRA portal (enps.nsdl.co.in) > Transaction statement, or the NPS app", False),
    "gold_physical": ("gold", "Your own count of grams x today's rate (run: python main.py gold-prices)", False),
    "sgb": ("gold", "Sovereign Gold Bonds show in your demat holdings (Kite > Holdings) or the RBI e-Kuber/bank statement", True),
    "real_estate": ("real_estate", "Your estimate of resale value today, net of any loan outstanding", False),
    "bonds": ("debt", "Demat holdings (tax-free bonds/G-secs) or RBI Retail Direct portfolio", True),
    "crypto": ("other", "Exchange app > portfolio value in INR", True),
    "cash_savings": ("cash", "Bank app > savings and sweep balances", True),
    "us_stock_other": ("equity", "A broker you did not import (Vested, IBKR, Schwab): Portfolio > Positions in USD x today's USD/INR", True),
    "other": ("other", "Anything else: your best estimate of today's value", False),
}


@dataclass
class Profile:
    age: int = 30
    risk: str = "moderate"
    horizon_years: int = 15
    monthly_expenses_inr: float = 0.0
    emergency_months: int = 6
    employer_ticker: str = ""
    employer_broker: str = ""          # e.g. etrade
    has_rsu: bool = False
    # income, for the tax-aware plan (all yearly, in rupees; leave 0 if unknown)
    tax_regime: str = "new"            # new | old
    gross_salary_inr: float = 0.0      # Form 16 Part B: gross salary, excluding RSU perquisite
    rsu_perquisite_inr: float = 0.0    # RSU/ESPP value taxed as salary this year (payslip / Form 16 "perquisites 17(2)")
    other_income_inr: float = 0.0      # FD/savings interest, dividends, rent (AIS on the income tax portal)
    deductions_inr: float = 0.0        # old regime only: 80C, 80D, HRA, home-loan interest...
    carried_st_loss_inr: float = 0.0   # last ITR, Schedule CFL: short-term capital loss carried forward
    carried_lt_loss_inr: float = 0.0   # last ITR, Schedule CFL: long-term capital loss carried forward

    def equity_cap(self) -> float:
        """Rule of thumb: (110 - age) % in equity, tilted by risk appetite, bounded to 20-90%."""
        base = 110 - self.age + RISK_TILT.get(self.risk, 0)
        return max(20, min(90, base)) / 100


# Slabs per the Finance Act 2025 (FY 2025-26 onward). Verify each Budget.
SLABS = {"new": [(400000, 0.0), (800000, 0.05), (1200000, 0.10), (1600000, 0.15), (2000000, 0.20), (2400000, 0.25), (float("inf"), 0.30)],
         "old": [(250000, 0.0), (500000, 0.05), (1000000, 0.20), (float("inf"), 0.30)]}
STD_DEDUCTION = {"new": 75000, "old": 50000}
REBATE_LIMIT = {"new": 1200000, "old": 500000}
INCOME_WHERE = """Where to find your income figures
  Gross salary          Form 16 Part B (from your employer each June), or 12 x the monthly gross on your payslip.
  RSU/ESPP perquisite   Payslip lines like "RSU perquisite" or "Stock perq"; Form 16 Part B, perquisites under 17(2).
                        E*TRADE Benefit History shows each vest's value in dollars too.
  Other income          incometax.gov.in > AIS (Annual Information Statement): bank interest, dividends, with TDS already cut.
                        Form 26AS on the same portal shows the TDS credits.
  Regime                Form 16 says whether your employer used the new or old regime; new is the default.
  Deductions (old only) Form 16 Part B, Chapter VI-A (80C, 80D...), HRA and home-loan interest.
  Carried-forward loss  Your last ITR, Schedule CFL, columns for short-term and long-term capital loss."""


def taxable_income(p: Profile) -> float:
    gross = p.gross_salary_inr + p.rsu_perquisite_inr
    std = STD_DEDUCTION.get(p.tax_regime, 75000) if gross > 0 else 0
    ded = p.deductions_inr if p.tax_regime == "old" else 0
    return max(0.0, gross - std - ded + p.other_income_inr)


def marginal_slab(p: Profile) -> tuple[float, float, str]:
    """(slab rate on the next rupee of ordinary income, surcharge, explanation)."""
    ti = taxable_income(p)
    slabs = SLABS.get(p.tax_regime, SLABS["new"])
    rate = next(r for limit, r in slabs if ti < limit)
    sur = 0.25 if ti > 2e7 else 0.15 if ti > 1e7 else 0.10 if ti > 5e6 else 0.0
    note = f"Taxable income about Rs {ti:,.0f} under the {p.tax_regime} regime puts your next rupee of interest or slab-taxed gains at {rate:.0%}"
    if sur:
        note += f" plus a {sur:.0%} surcharge"
    if ti <= REBATE_LIMIT.get(p.tax_regime, 0):
        note += f". Your income is under the Rs {REBATE_LIMIT[p.tax_regime]:,.0f} rebate limit, so ordinary income may be tax free, but the rebate does not cover capital gains taxed at special rates"
    return rate, sur, note + "."


def apply_broker_rules(settings, p: Profile | None) -> None:
    """Employer shares held in a restricted stock-plan account (E*TRADE at Work) can only be sold there."""
    if p and p.employer_ticker and p.employer_broker == "etrade":
        a = settings.assets.get(p.employer_ticker.upper())
        if a is not None:
            a.sell_only = True
            a.broker = a.broker or "E*TRADE stock plan (sell only)"


def apply_tax_profile(settings, p: Profile | None) -> str | None:
    """Set the slab rate and surcharge from the profile's income. Returns the explanation, or None if no income is given."""
    if p is None or (p.gross_salary_inr + p.rsu_perquisite_inr + p.other_income_inr) <= 0:
        return None
    rate, sur, note = marginal_slab(p)
    settings.raw["tax"]["slab_rate"] = rate
    settings.raw["tax"]["surcharge"] = min(sur, 0.15)   # capital gains under 111A/112A are capped at 15%
    return note


@dataclass
class OtherAsset:
    kind: str
    name: str
    value_inr: float
    note: str = ""

    @property
    def asset_class(self) -> str:
        return KINDS.get(self.kind, KINDS["other"])[0]

    @property
    def liquid(self) -> bool:
        return KINDS.get(self.kind, KINDS["other"])[2]


def load_profile(path: Path = PROFILE_PATH) -> Profile | None:
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text()) or {}
    return Profile(**{k: v for k, v in raw.items() if k in Profile.__dataclass_fields__})


def save_profile(p: Profile, path: Path = PROFILE_PATH) -> None:
    path.write_text("# Investor profile (git-ignored). Edit by hand or via `python main.py shell`.\n"
                    + yaml.safe_dump(p.__dict__, sort_keys=False))


def load_other(path: Path = OTHER_PATH) -> list[OtherAsset]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    return [OtherAsset(**a) for a in raw.get("assets", [])]


def save_other(items: list[OtherAsset], path: Path = OTHER_PATH) -> None:
    path.write_text("# Investments the engine cannot trade but counts in your allocation (git-ignored).\n"
                    + yaml.safe_dump({"assets": [a.__dict__ for a in items]}, sort_keys=False))


def merge_lots(new_lots: list[dict], meta: dict | None = None, replace_symbols: set[str] | None = None,
               path: Path | None = None) -> Path:
    """Add lots (and per-symbol asset overrides) to config/holdings.yaml, keeping everything else.

    replace_symbols: drop existing lots for these symbols first, so re-importing a tradebook
    does not double-count.
    """
    path = path or ROOT / "config" / "holdings.yaml"
    if path.exists():
        doc = yaml.safe_load(path.read_text()) or {}
    else:
        doc = {"cash_inr": 0, "realised_this_fy": {"equity_stcg": 0, "equity_ltcg": 0, "other_stcg": 0, "other_ltcg": 0},
               "lrs_remitted_this_fy_inr": 0}
    drop = replace_symbols if replace_symbols is not None else {l["symbol"] for l in new_lots}
    doc["lots"] = [l for l in doc.get("lots", []) if l["symbol"] not in drop] + new_lots
    if meta:
        doc.setdefault("assets", {}).update(meta)
    if path.exists():
        path.with_suffix(".yaml.bak").write_text(path.read_text())
    path.write_text("# Tax lots (git-ignored). One entry per purchase.\n" + yaml.safe_dump(doc, sort_keys=False, default_flow_style=None))
    return path


def guardrails(p: Profile | None, others: list[OtherAsset], equity_value: float, total_tradable: float,
               employer_value: float, plan_equity_after: float | None = None) -> list[dict]:
    """Checks of the whole picture (tradable + other assets) against the profile. Each: level ok|warn, title, detail."""
    out = []
    other_total = sum(o.value_inr for o in others)
    other_eq = sum(o.value_inr for o in others if o.asset_class == "equity")
    # NPS and EPF are partly equity but we only count what the user labelled as equity
    total = total_tradable + other_total
    if total <= 0:
        return out
    eq = (equity_value + other_eq) / total
    if p is None:
        out.append({"level": "info", "title": "No profile yet",
                    "detail": "Run `python main.py shell` and choose profile to set age and risk appetite; the report then checks your equity share against it."})
    else:
        cap = p.equity_cap()
        lvl = "ok" if eq <= cap + 0.02 else "warn"
        out.append({"level": lvl, "title": f"Equity share {eq:.0%} vs guide {cap:.0%}",
                    "detail": f"Rule of thumb for age {p.age}, {p.risk}: (110 - age) % in equity, tilted by risk appetite. "
                              + ("You are inside it." if lvl == "ok" else "You hold more equity than the guide, so a defensive trade is more defensible.")
                              + (f" After this plan: {plan_equity_after:.0%}." if plan_equity_after is not None else "")})
        if employer_value > 0:
            share = employer_value / total
            out.append({"level": "ok" if share <= 0.10 else "warn", "title": f"Employer stock {share:.0%} of everything",
                        "detail": "Your salary already depends on this company, so more than ~10% in its stock stacks the same risk twice. "
                                  "RSUs are taxed as salary at vest; selling later only adds capital gains on the move since vest."})
        if p.monthly_expenses_inr > 0:
            liquid = sum(o.value_inr for o in others if o.asset_class in ("cash", "debt") and o.liquid)
            need = p.emergency_months * p.monthly_expenses_inr
            out.append({"level": "ok" if liquid >= need else "warn",
                        "title": f"Emergency fund Rs {liquid:,.0f} vs Rs {need:,.0f} target",
                        "detail": f"{p.emergency_months} months of expenses should sit in cash/liquid debt, outside anything this engine rotates."})
    return out
