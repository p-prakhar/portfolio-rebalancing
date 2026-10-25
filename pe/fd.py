"""Fixed deposits: what each one is worth today, what it pays after tax, and what breaking it early costs.

Bank presets cover SBI and IDFC FIRST Bank; any other bank works with the generic preset. Rules change, so every
preset number is a default you can override per deposit in config/fds.yaml (git-ignored).
Tax: FD interest is taxed every year at your slab rate as it accrues, even on a cumulative FD that pays only at
maturity. Banks deduct TDS of 10% (20% without PAN) when your interest from that bank crosses the yearly threshold
(Rs 50,000; Rs 1 lakh for senior citizens, per the Finance Act 2025). TDS is not an extra tax: it is credited
against what you owe when you file. Form 15G/15H stops TDS only if your total income is below the taxable limit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import yaml
from dateutil.relativedelta import relativedelta

from .config import ROOT

PATH = ROOT / "config" / "fds.yaml"

BANKS = {
    "sbi": {"name": "SBI", "compounding": 4, "penalty": [(500000, 0.005), (float("inf"), 0.01)],
            "where": "YONO app > Deposits > select the FD > Details (rate, start date, maturity, amount). OnlineSBI: Fixed Deposit > "
                     "e-TDR/e-STDR > Enquiry. The FD advice PDF has all of it; TDS certificates are under e-Services > TDS Enquiry.",
            "penalty_note": "SBI: 0.5% below the rate for the period actually held (deposits up to Rs 5 lakh), 1% above that. "
                            "Check the current terms on sbi.co.in before breaking."},
    "idfc_first": {"name": "IDFC FIRST Bank", "compounding": 4, "penalty": [(float("inf"), 0.01)],
                   "where": "IDFC FIRST Bank app > Deposits > select the FD > View details (rate, tenure, maturity value). The FD advice is "
                            "emailed when you book it; TDS certificates are in the app under Services > Tax / TDS certificate.",
                   "penalty_note": "Assumed 1% below the rate for the period held. Terms differ by deposit and booking date, so read your "
                                   "FD advice and set 'penalty' on the deposit if it differs."},
    "other": {"name": "Other bank", "compounding": 4, "penalty": [(float("inf"), 0.01)],
              "where": "Your bank's app or net banking > Deposits, or the FD advice / receipt.",
              "penalty_note": "Assumed 1% below the rate for the period held; set 'penalty' on the deposit to your bank's figure."},
}


@dataclass
class FD:
    bank: str
    principal: float
    rate: float                  # annual, e.g. 0.0725
    start: date
    months: int
    payout: str = "cumulative"   # cumulative | quarterly | monthly
    label: str = ""
    penalty: float | None = None
    senior: bool = False

    @property
    def maturity(self) -> date:
        return self.start + relativedelta(months=self.months)

    def _comp(self) -> int:
        return BANKS.get(self.bank, BANKS["other"])["compounding"]

    def value_on(self, d: date) -> float:
        """Principal plus interest earned to date (cumulative) or principal (payout FDs)."""
        if self.payout != "cumulative":
            return self.principal
        t = max(0.0, (min(d, self.maturity) - self.start).days / 365.0)
        n = self._comp()
        return self.principal * (1 + self.rate / n) ** (n * t)

    def interest_in_fy(self, fy_start: date) -> float:
        a, b = max(self.start, fy_start), min(self.maturity, fy_start + relativedelta(years=1))
        if b <= a:
            return 0.0
        if self.payout == "cumulative":
            return self.value_on(b) - self.value_on(a)
        return self.principal * self.rate * (b - a).days / 365.0

    def penalty_rate(self) -> float:
        if self.penalty is not None:
            return self.penalty
        for limit, p in BANKS.get(self.bank, BANKS["other"])["penalty"]:
            if self.principal <= limit:
                return p
        return 0.01

    def break_value(self, d: date, card_rate_for_period: float | None = None) -> float:
        """What you get if you close it on `d`: interest at (rate for the period actually held - penalty).
        Without the bank's card rate for the shorter period we use the booked rate, which overstates it a little."""
        base = card_rate_for_period if card_rate_for_period is not None else self.rate
        r = max(0.0, base - self.penalty_rate())
        t = max(0.0, (min(d, self.maturity) - self.start).days / 365.0)
        n = self._comp()
        return self.principal * (1 + r / n) ** (n * t)


def load() -> list[FD]:
    if not PATH.exists():
        return []
    raw = yaml.safe_load(PATH.read_text()) or {}
    out = []
    for f in raw.get("fds", []):
        f = dict(f)
        f["start"] = f["start"] if isinstance(f["start"], date) else date.fromisoformat(str(f["start"]))
        out.append(FD(**f))
    return out


def save(fds: list[FD]) -> None:
    rows = []
    for f in fds:
        d = dict(f.__dict__)
        d["start"] = str(d["start"])
        rows.append({k: v for k, v in d.items() if v not in (None, "") or k in ("bank", "principal", "rate", "start", "months")})
    PATH.write_text("# Fixed deposits (git-ignored). Edit here or via the shell's add-fd.\n" + yaml.safe_dump({"fds": rows}, sort_keys=False))


def summary(fds: list[FD], slab: float, cess: float = 0.04, today: date | None = None) -> list[dict]:
    today = today or date.today()
    fy0 = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    eff = slab * (1 + cess)
    out = []
    per_bank: dict[str, float] = {}
    for f in fds:
        per_bank[f.bank] = per_bank.get(f.bank, 0.0) + f.interest_in_fy(fy0)
    for f in fds:
        yearly = (1 + f.rate / f._comp()) ** f._comp() - 1
        threshold = 100000 if f.senior else 50000
        out.append({"label": f.label or f"{BANKS.get(f.bank, BANKS['other'])['name']} FD", "bank": BANKS.get(f.bank, BANKS["other"])["name"],
                    "principal": f.principal, "rate": f.rate, "start": str(f.start), "maturity": str(f.maturity), "days_left": (f.maturity - today).days,
                    "value_today": f.value_on(today), "break_value_today": f.break_value(today), "penalty_rate": f.penalty_rate(),
                    "effective_yield": yearly, "after_tax_yield": yearly * (1 - eff), "interest_this_fy": f.interest_in_fy(fy0),
                    "tax_this_fy": f.interest_in_fy(fy0) * eff, "tds_likely": per_bank[f.bank] > threshold,
                    "bank_interest_this_fy": per_bank[f.bank], "penalty_note": BANKS.get(f.bank, BANKS["other"])["penalty_note"]})
    return out
