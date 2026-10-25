"""Mutual funds: where to find yours, importing them from a CAS statement, NAV history, and regular vs direct plans.

NAVs come from mfapi.in, a free mirror of AMFI's daily NAV data. Holdings come from the Consolidated Account Statement
(CAS) PDF, parsed with casparser. Advisor-placed funds are usually REGULAR plans, which pay the distributor a
commission inside the expense ratio; the same fund's DIRECT plan holds the same portfolio for less. The yearly cost
gap is measured here straight from the two plans' NAV histories, which already include every fee.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

import pandas as pd

from .config import ROOT

API = "https://api.mfapi.in/mf"
CACHE = ROOT / "data" / "cache_mf"

WHERE = """Where to find your mutual funds
  Best: a Consolidated Account Statement (CAS). It lists every fund in your PAN across all AMCs, with every purchase date and price.
    - CAMS: camsonline.com > Investors > Statements > CAS - CAMS+KFintech. Choose "Detailed", period "Specific period" from your
      first investment to today, set a password, submit. The PDF arrives by email in a few minutes.
    - MF Central: mfcentral.com (log in with PAN and OTP) > Reports > Consolidated Account Statement. Same data, also as PDF.
    - KFintech: mfs.kfintech.com > Investor services > CAS. Same data.
  Funds bought through a demat account (Zerodha Coin, Groww) also appear in the NSDL/CDSL CAS that the depository emails monthly.
  Then run `import-mf` in the shell and give it the PDF and the password you chose.
  No PDF? `add-mf` takes the fund name, purchase date and amount by hand; the fund house app or the advisor's statement has them."""


def _get(url: str):
    import requests
    r = requests.get(url, timeout=25, headers={"User-Agent": "portfolio-engine"})
    r.raise_for_status()
    return r.json()


def search(q: str) -> list[dict]:
    return _get(f"{API}/search?q={q}")


def _cached(code: str, refresh: bool = False) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{code}.json"
    if p.exists() and not refresh and time.time() - p.stat().st_mtime < 20 * 3600:
        return json.loads(p.read_text())
    d = _get(f"{API}/{code}")
    p.write_text(json.dumps(d))
    return d


def scheme_meta(code: str) -> dict:
    return _cached(str(code))["meta"]


def nav_series(code: str, refresh: bool = False) -> pd.Series:
    d = _cached(str(code), refresh)
    s = pd.Series({pd.to_datetime(x["date"], format="%d-%m-%Y"): float(x["nav"]) for x in d["data"]}).sort_index()
    return s[s > 0]


def tax_class(category: str, buy_date: date) -> str:
    """Indian tax treatment of a mutual fund unit, from its AMFI category and purchase date."""
    c = (category or "").lower()
    if c.startswith("equity") or "arbitrage" in c or "aggressive hybrid" in c or "elss" in c or "index fund" in c and "debt" not in c:
        return "in_equity"         # equity-oriented: 20% STCG, 12.5% LTCG after 12 months
    if "debt" in c or "liquid" in c or "money market" in c or "overnight" in c or "gilt" in c:
        return "in_debt" if buy_date >= date(2023, 4, 1) else "mf_other"   # specified MF: slab rate regardless of holding
    return "mf_other"              # gold/international FoFs, other hybrids: 12.5% LTCG after 24 months, STCG at slab


def sleeve_for(category: str) -> str:
    c = (category or "").lower()
    if "gold" in c or "silver" in c:
        return "gold"
    if "fund of funds" in c and ("overseas" in c or "international" in c):
        return "global_equity"
    if c.startswith("equity") or "index" in c or "aggressive" in c:
        return "india_equity"
    if "arbitrage" in c or "liquid" in c or "overnight" in c or "money market" in c:
        return "cash"
    return "bonds"


def symbol_for(code: str | int) -> str:
    return f"MF{code}"


def asset_meta(code: str | int, name: str, category: str, buy_date: date) -> dict:
    return {"ticker": f"MFAPI:{code}", "name": name, "tax_class": tax_class(category, buy_date), "venue": "mutual_fund",
            "sleeve": sleeve_for(category), "currency": "INR"}


def is_regular(name: str) -> bool:
    n = name.lower()
    return "direct" not in n and ("regular" in n or "reg " in n or "plan" in n)


def direct_twin(name: str) -> dict | None:
    """Find the DIRECT growth plan of the same scheme."""
    base = re.split(r"\s+-\s+(regular|direct)", name, flags=re.I)[0]
    base = re.sub(r"\(.*?\)", "", base).strip()
    try:
        hits = search(base)
    except Exception:
        return None
    for h in hits:
        n = h["schemeName"].lower()
        if "direct" in n and "growth" in n and "idcw" not in n and "dividend" not in n:
            return h
    return None


def cost_gap(regular_code: str, direct_code: str, years: int = 3) -> float | None:
    """Yearly return the regular plan gave up against the direct plan over the last `years` (positive = regular costs more)."""
    r, d = nav_series(regular_code), nav_series(direct_code)
    end = min(r.index[-1], d.index[-1])
    start = end - pd.DateOffset(years=years)
    r, d = r[:end], d[:end]
    if r.index[0] > start or d.index[0] > start:
        return None
    rr = (r.iloc[-1] / r[:start].iloc[-1]) ** (1 / years)
    dd = (d.iloc[-1] / d[:start].iloc[-1]) ** (1 / years)
    return float(dd - rr)


# ---------------- CAS import ----------------
def lots_from_cas(cas: dict) -> tuple[list[dict], dict, list[str]]:
    """Open lots (first-in-first-out) per scheme from a casparser dict. Returns (lots, asset meta by symbol, warnings)."""
    lots, meta, warns = [], {}, []
    for folio in cas.get("folios", []):
        for sch in folio.get("schemes", []):
            code = sch.get("amfi")
            name = sch.get("scheme", "")
            if not code:
                warns.append(f"{name}: no AMFI code in the statement; add it by hand with add-mf.")
                continue
            try:
                category = scheme_meta(code).get("scheme_category", "")
            except Exception:
                category = sch.get("type") or ""
            q: list[list] = []
            for t in sch.get("transactions", []):
                units = float(t.get("units") or 0)
                if units == 0:
                    continue
                d = t["date"] if isinstance(t["date"], date) else date.fromisoformat(str(t["date"])[:10])
                nav = float(t.get("nav") or 0) or (abs(float(t.get("amount") or 0)) / abs(units) if units else 0)
                if units > 0:
                    q.append([units, d, nav])
                else:
                    left = -units
                    while left > 1e-6 and q:
                        take = min(q[0][0], left)
                        q[0][0] -= take
                        left -= take
                        if q[0][0] <= 1e-6:
                            q.pop(0)
                    if left > 1e-3:
                        warns.append(f"{name}: redeemed {left:.3f} more units than the statement shows bought (start the CAS period earlier).")
            sym = symbol_for(code)
            close = float(sch.get("close") or 0)
            held = sum(x[0] for x in q)
            if close and abs(held - close) > 0.01 * max(close, 1):
                warns.append(f"{name}: lots add up to {held:.3f} units but the statement closes at {close:.3f}; check the CAS period.")
            for units, d, nav in q:
                lots.append({"symbol": sym, "qty": round(units, 4), "buy_date": str(d), "price": round(nav, 4)})
            if q:
                meta[sym] = asset_meta(code, name, category, q[0][1])
    return lots, meta, warns


def read_cas(path: str, password: str) -> dict:
    import casparser
    return casparser.read_cas_pdf(path, password, output="dict")


# ---------------- report ----------------
UNIVERSE = [  # well-known DIRECT growth plans, resolved by name on mfapi.in
    ("Index", "UTI Nifty 50 Index Fund - Direct Plan - Growth"),
    ("Index", "Motilal Oswal Nifty Midcap 150 Index Fund - Direct Plan - Growth"),
    ("Flexi cap", "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"),
    ("Flexi cap", "HDFC Flexi Cap Fund - Direct Plan - Growth"),
    ("Large cap", "ICICI Prudential Bluechip Fund - Direct Plan - Growth"),
    ("Mid cap", "Motilal Oswal Midcap Fund - Direct Plan - Growth"),
    ("Small cap", "Nippon India Small Cap Fund - Direct Plan - Growth"),
    ("Hybrid", "ICICI Prudential Equity & Debt Fund - Direct Plan - Growth"),
    ("Hybrid", "HDFC Balanced Advantage Fund - Direct Plan - Growth"),
    ("Arbitrage", "Kotak Equity Arbitrage Fund - Direct Plan - Growth"),
    ("Debt", "HDFC Liquid Fund - Direct Plan - Growth"),
    ("Debt", "ICICI Prudential Corporate Bond Fund - Direct Plan - Growth"),
    ("International", "Motilal Oswal Nasdaq 100 Fund of Fund - Direct Plan - Growth"),
    ("Gold", "SBI Gold Fund - Direct Plan - Growth"),
]


def resolve(name: str) -> dict | None:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    try:
        hits = search(" ".join(name.split(" - ")[0].split()[:5]))
    except Exception:
        return None
    best, score = None, -1
    for h in hits:
        n = h["schemeName"].lower()
        if "direct" not in n or "growth" not in n or "idcw" in n or "bonus" in n:
            continue
        sc = sum(w in n for w in words)
        if sc > score:
            best, score = h, sc
    return best


def _cagr(s: pd.Series, years: float):
    s = s.dropna()
    if len(s) < 2 or (s.index[-1] - s.index[0]).days < years * 365 * 0.95:
        return None
    base = s[s.index <= s.index[-1] - pd.DateOffset(years=years)]
    return None if base.empty else float((s.iloc[-1] / base.iloc[-1]) ** (1 / years) - 1)


def compare_rows(nifty: pd.Series | None, settings) -> list[dict]:
    """The mutual fund universe in the same shape as universe_compare rows (direct plans; tax by category)."""
    import numpy as np
    from .tax import effective_rate
    rows = []
    for theme, name in UNIVERSE:
        h = resolve(name)
        if not h:
            continue
        code = h["schemeCode"]
        try:
            s = nav_series(code)
            cat = scheme_meta(code).get("scheme_category", "")
        except Exception:
            continue
        r = s.pct_change().dropna()
        c5 = _cagr(s, 5)
        net5 = None
        tc = tax_class(cat, date.today())
        if c5 is not None:
            end = (1 + c5) ** 5
            rate = effective_rate("eq_lt", settings) if tc == "in_equity" else effective_rate("debt" if tc == "in_debt" else "oth_lt", settings)
            net5 = (end - (end - 1) * rate - 0.00005) ** (1 / 5) - 1
        corr = None
        if nifty is not None:
            nr = nifty.pct_change().reindex(r.index).iloc[-756:]
            cc = r.iloc[-756:].corr(nr)
            corr = None if pd.isna(cc) else float(cc)
        rows.append({"symbol": h["schemeName"].split(" - ")[0][:40], "name": h["schemeName"], "theme": f"Mutual funds: {theme}", "where": "India",
                     "how": f"Direct plan through Coin, Kuvera, MF Central or the fund house; {'taxed like shares' if tc == 'in_equity' else 'taxed at your slab' if tc == 'in_debt' else '12.5% after 24 months'}",
                     "since": str(s.index[0].date()), "r1": _cagr(s, 1), "r3": _cagr(s, 3), "r5": c5, "r10": _cagr(s, 10),
                     "vol": float(r.iloc[-252:].std() * np.sqrt(252)), "max_dd_5y": float((s.iloc[-1260:] / s.iloc[-1260:].cummax() - 1).min()),
                     "corr_nifty": corr, "mom_12_1": None, "after_tax_5y": net5, "tax_class": tc, "single_stock": False})
    return rows


def holdings_report(lots, settings, today: date | None = None) -> list[dict]:
    """For each mutual fund you hold: regular or direct, what the regular plan costs a year, and whether switching pays."""
    from .tax import effective_rate
    today = today or date.today()
    by: dict[str, list] = {}
    for l in lots:
        if l.symbol.startswith("MF"):
            by.setdefault(l.symbol, []).append(l)
    out = []
    for sym, ls in by.items():
        code = sym[2:]
        try:
            meta = scheme_meta(code)
            nav = float(nav_series(code).iloc[-1])
        except Exception:
            continue
        name, cat = meta.get("scheme_name", sym), meta.get("scheme_category", "")
        units = sum(l.qty for l in ls)
        value = units * nav
        cost = sum(l.qty * l.price for l in ls)
        row = {"symbol": sym, "name": name, "category": cat, "units": units, "value": value, "cost": cost, "gain": value - cost,
               "regular": is_regular(name), "young_lots": sum(l.qty * nav for l in ls if (today - l.buy_date).days < 365)}
        if row["regular"]:
            twin = direct_twin(name)
            if twin:
                gap = cost_gap(code, str(twin["schemeCode"]))
                row.update({"direct_name": twin["schemeName"], "direct_code": twin["schemeCode"], "gap": gap})
                if gap is not None:
                    tc = tax_class(cat, min(l.buy_date for l in ls))
                    lt = [l for l in ls if (today - l.buy_date).days > (365 if tc == "in_equity" else 730)]
                    lt_gain = sum(l.qty * (nav - l.price) for l in lt)
                    st_gain = value - cost - lt_gain
                    if tc == "in_equity":
                        tax = max(0.0, lt_gain - settings.tax["ltcg_exemption"]) * effective_rate("eq_lt", settings) + max(0.0, st_gain) * effective_rate("eq_st", settings)
                    else:
                        tax = max(0.0, lt_gain) * effective_rate("oth_lt", settings) + max(0.0, st_gain) * effective_rate("debt", settings)
                    load = row["young_lots"] * 0.01
                    yearly = gap * value
                    row.update({"switch_tax": tax, "exit_load_est": load, "yearly_cost": yearly,
                                "breakeven_years": (tax + load) / yearly if yearly > 0 else None})
        out.append(row)
    return out
