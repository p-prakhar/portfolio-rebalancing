"""Compare a wide universe (metals, semiconductors, India and abroad) the way an Indian resident would actually own it.

Everything is in rupees. For each instrument: trailing returns, volatility, worst fall, correlation with the Nifty 50,
momentum, and what a Rs 1 lakh, 5-year holding would be worth after round-trip costs and capital-gains tax. Past returns say
nothing certain about the future; metals and semiconductors had very different decades, and the 10-year window includes the
2020-2026 chip and gold booms.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Settings
from .costs import leg_cost
from .tax import effective_rate

# symbol -> (theme, where it trades, how an Indian resident buys it)
INFO: dict[str, tuple[str, str, str]] = {
    "NIFTYBEES": ("Benchmark", "India", "Kite, NSE ETF"),
    "GOLDBEES": ("Precious metals", "India", "Kite, NSE gold ETF (taxed as other asset, 12.5% LT after 12 months)"),
    "GLD": ("Precious metals", "US", "IBKR via LRS (foreign asset, 24 months to LT)"),
    "SILVERBEES": ("Precious metals", "India", "Kite, NSE silver ETF"),
    "SILVERIETF": ("Precious metals", "India", "Kite, NSE silver ETF (ICICI)"),
    "SLV": ("Precious metals", "US", "IBKR via LRS"),
    "PPLT": ("Precious metals", "US", "IBKR via LRS; no India-listed platinum ETF"),
    "GDX": ("Precious metals", "US", "IBKR via LRS; gold miners add equity risk to the gold price"),
    "CPER": ("Industrial metals", "US", "IBKR via LRS; copper futures ETF"),
    "COPX": ("Industrial metals", "US", "IBKR via LRS; copper miners"),
    "DBB": ("Industrial metals", "US", "IBKR via LRS; aluminium, zinc, copper futures"),
    "LIT": ("Industrial metals", "US", "IBKR via LRS; lithium and battery chain"),
    "REMX": ("Industrial metals", "US", "IBKR via LRS; rare earths, strategic metals miners"),
    "URA": ("Industrial metals", "US", "IBKR via LRS; uranium miners and trusts"),
    "DBC": ("Broad commodities", "US", "IBKR via LRS"),
    "METALIETF": ("India metals", "India", "Kite; Nifty Metal ETF (short history)"),
    "HINDALCO": ("India metals", "India", "Kite; single stock (aluminium, copper)"),
    "HINDCOPPER": ("India metals", "India", "Kite; single stock, very volatile"),
    "VEDL": ("India metals", "India", "Kite; single stock (zinc, aluminium, silver)"),
    "SMH": ("Semiconductors", "US", "IBKR via LRS; cap-weighted, heavy in NVIDIA and TSMC"),
    "SOXX": ("Semiconductors", "US", "IBKR via LRS; ICE semiconductor index"),
    "XSD": ("Semiconductors", "US", "IBKR via LRS; equal-weight, less top-heavy"),
    "NVDA": ("Semiconductors", "US", "IBKR via LRS; single stock"),
    "TSM": ("Semiconductors", "US", "IBKR via LRS; Taiwan-based, geopolitical risk"),
    "ASML": ("Semiconductors", "US", "IBKR via LRS; chip equipment, Dutch company"),
    "AVGO": ("Semiconductors", "US", "IBKR via LRS; single stock"),
    "MAFANG": ("Global tech", "India", "Kite; FANG+ index ETF (can trade at a premium to NAV)"),
    "MON100": ("Global tech", "India", "Kite; Nasdaq 100 ETF (can trade at a premium)"),
    "QQQ": ("Global tech", "US", "IBKR via LRS"),
    "ITBEES": ("India tech and electronics", "India", "Kite; Nifty IT ETF (software services, not chips)"),
    "DIXON": ("India tech and electronics", "India", "Kite; single stock, electronics manufacturing"),
    "KAYNES": ("India tech and electronics", "India", "Kite; single stock, electronics and chip packaging push"),
    "HNGSNGBEES": ("Other markets", "India", "Kite; Hang Seng ETF"),
    "SPY": ("Benchmark", "US", "IBKR via LRS"),
    "EEM": ("Other markets", "US", "IBKR via LRS"),
}
NOTES = {
    "semiconductors": "India has no pure semiconductor ETF. The India-listed ways in are electronics makers (Dixon, Kaynes) or a global tech ETF; "
                      "real chip exposure means US-listed ETFs through LRS (TCS applies above the yearly threshold and is a credit against tax).",
    "metals": "No India-listed platinum, copper or rare-earth ETFs exist, so those come via US ETFs. Physical gold and silver carry making charges, GST and "
              "a buyback haircut that dwarf any city price gap; ETFs avoid them.",
}


def _cagr(s: pd.Series, years: float) -> float | None:
    s = s.dropna()
    if len(s) < 2 or (s.index[-1] - s.index[0]).days < years * 365 * 0.95:
        return None
    base = s[s.index <= s.index[-1] - pd.DateOffset(years=years)]
    if base.empty:
        return None
    return float((s.iloc[-1] / base.iloc[-1]) ** (1 / years) - 1)


def compare(px: pd.DataFrame, settings: Settings, usd_inr: float | None = None, amount: float = 100_000, years: float = 5) -> list[dict]:
    rows = []
    nifty = px["NIFTYBEES"].pct_change()
    for sym, (theme, where, how) in INFO.items():
        if sym not in px or px[sym].dropna().empty or sym not in settings.assets:
            continue
        s = px[sym].dropna()
        a = settings.assets[sym]
        r = s.pct_change().dropna()
        dd5 = (s.iloc[-1260:] / s.iloc[-1260:].cummax() - 1).min()
        corr = r.iloc[-756:].corr(nifty.reindex(r.index).iloc[-756:]) if len(r) > 100 else None
        mom = float(s.iloc[-22] / s.iloc[-253] - 1) if len(s) > 253 else None
        c5 = _cagr(s, years)
        net5 = None
        if c5 is not None:
            end = amount * (1 + c5) ** years
            gain = max(0.0, end - amount)
            bucket = "eq_lt" if a.tax_class == "in_equity" else "oth_lt"
            tax = gain * effective_rate(bucket, settings)
            costs = leg_cost(settings, a, "buy", amount, float(s.iloc[-1]), usd_inr) + leg_cost(settings, a, "sell", end, float(s.iloc[-1]), usd_inr)
            fx = amount * settings["costs"]["ibkr_us"]["fx_one_way"] * 2 if a.currency == "USD" else 0.0
            net5 = (end - tax - costs - fx) / amount
            net5 = float(net5 ** (1 / years) - 1) if net5 > 0 else None
        rows.append({"symbol": sym, "name": a.name, "theme": theme, "where": where, "how": how,
                     "since": str(s.index[0].date()), "r1": _cagr(s, 1), "r3": _cagr(s, 3), "r5": c5, "r10": _cagr(s, 10),
                     "vol": float(r.iloc[-252:].std() * np.sqrt(252)), "max_dd_5y": float(dd5), "corr_nifty": None if corr is None or pd.isna(corr) else float(corr),
                     "mom_12_1": mom, "after_tax_5y": net5, "tax_class": a.tax_class, "single_stock": a.venue == "nse_stock" or sym in ("NVDA", "TSM", "ASML", "AVGO")})
    return rows


def report(rows: list[dict]) -> str:
    f = lambda x, d=1: "-" if x is None else f"{x * 100:+.{d}f}%"
    out = ["# Wider universe: metals, semiconductors, India and abroad", "",
           "_Rupee returns (US assets include dollar moves), annualised. 'After tax 5y' is Rs 1 lakh held 5 years then sold, after round-trip costs, "
           "currency conversion and long-term capital-gains tax at today's rates. Past returns do not predict future ones._", ""]
    for theme in list(dict.fromkeys(v[0] for v in INFO.values())) + sorted({r["theme"] for r in rows if r["theme"].startswith("Mutual funds")}):
        grp = [r for r in rows if r["theme"] == theme]
        if not grp:
            continue
        out += [f"## {theme}", "", "| instrument | where | 1y | 3y | 5y | 10y | 5y after tax | vol | worst fall (5y) | vs Nifty | how to buy |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(grp, key=lambda x: -(x["after_tax_5y"] if x["after_tax_5y"] is not None else -9)):
            out.append(f"| {r['symbol']} | {r['where']} | {f(r['r1'])} | {f(r['r3'])} | {f(r['r5'])} | {f(r['r10'])} | {f(r['after_tax_5y'])} | {r['vol']:.0%} | "
                       f"{r['max_dd_5y']:.0%} | {'-' if r['corr_nifty'] is None else format(r['corr_nifty'], '.2f')} | {r['how']} |")
        out.append("")
    out += ["## Things to know", "", "- " + NOTES["semiconductors"], "- " + NOTES["metals"],
            "- Correlation to the Nifty near zero or negative means the asset diversifies; single stocks are far more volatile than the ETFs next to them.",
            "- Short-history funds (SILVERIETF, METALIETF, Kaynes) have too little data for a meaningful 3y/5y figure."]
    return "\n".join(out)
