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

    def equity_cap(self) -> float:
        """Rule of thumb: (110 - age) % in equity, tilted by risk appetite, bounded to 20-90%."""
        base = 110 - self.age + RISK_TILT.get(self.risk, 0)
        return max(20, min(90, base)) / 100


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
