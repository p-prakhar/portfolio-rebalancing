"""City-wise retail gold rates (metal only, before making charges and GST) and a landed-parity check.

Scrapes a public city-rate page per city (default pricehistoryapp.com, where cards read like
"24K 99.9% pure ... Rs 1,42,128  Rs 14,213/g"). Websites change their layout; if parsing fails,
pass rates by hand with `--manual bangalore=14800,raipur=14213`. Every successful run is
appended to a CSV, so a daily schedule builds your own city-spread history.

City spreads in India are usually small (local jewellers' association rates and quoting
conventions differ), while making charges, GST and buyback haircuts are large. So the report
puts the spread in context: a 1% cheaper city on Rs 5 lakh saves Rs 5,000, about the same as one
year of a metro bank locker.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from .config import ROOT

TROY_OZ_G = 31.1035
UA = {"User-Agent": "Mozilla/5.0 (portfolio-engine gold checker)"}


def parse_rates(html: str) -> dict[str, float]:
    """Pull per-gram 24K and 22K rates out of a rate page."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&#8377;|&#x20b9;|&#X20B9;|&#x20B9;|Rs\.?", "₹", text)
    text = re.sub(r"&nbsp;", " ", text).replace("₹", " ₹ ")
    text = re.sub(r"\s+", " ", text)
    out = {}
    for k in ("24K", "22K", "18K"):
        # stay inside this purity's card: don't run past the next "NNK" label
        m = re.search(rf"{k}\b(?:(?!\b\d{{2}}K\b).){{0,200}}?₹\s*([\d,]+(?:\.\d+)?)\s*/\s*g", text, flags=re.I)
        if not m:   # fallback: "<k> ... per gram ... ₹ x"
            m = re.search(rf"{k}\b(?:(?!\b\d{{2}}K\b).){{0,120}}?(?:per|1)\s*g(?:ram)?\b.{{0,40}}?₹\s*([\d,]+(?:\.\d+)?)", text, flags=re.I)
        if m:
            v = float(m.group(1).replace(",", ""))
            if 1000 < v < 100000:  # sanity: per-gram range
                out[k] = v
    return out


def fetch_city(city: str, source: str) -> dict[str, float]:
    import requests
    r = requests.get(source.format(city=city), headers=UA, timeout=20)
    r.raise_for_status()
    return parse_rates(r.text)


def landed_parity(import_duty: float, gst: float = 0.03) -> dict | None:
    """International spot converted to INR per gram, plus duty: what an importer pays."""
    try:
        import yfinance as yf
        d = yf.download(["GC=F", "INR=X"], period="5d", progress=False, auto_adjust=True)["Close"].ffill().iloc[-1]
        spot = float(d["GC=F"]) * float(d["INR=X"]) / TROY_OZ_G
        return {"spot_inr_g": spot, "landed_ex_gst": spot * (1 + import_duty), "landed_incl_gst": spot * (1 + import_duty) * (1 + gst)}
    except Exception:
        return None


def snapshot(cfg: dict, manual: dict[str, float] | None = None) -> tuple[pd.DataFrame, list[str]]:
    g = cfg["gold_prices"]
    rows, errors = [], []
    for city in g["cities"]:
        if manual and city in manual:
            rows.append({"city": city, "24K": manual[city], "22K": None, "source": "manual"})
            continue
        try:
            r = fetch_city(city, g["source"])
            if "24K" not in r:
                raise ValueError("could not find a 24K per-gram rate on the page")
            rows.append({"city": city, **r, "source": g["source"].format(city=city)})
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            errors.append(f"{city}: {type(exc).__name__}" + (f" {code} (no such city page on the source)" if code == 404 else ""))
    df = pd.DataFrame(rows)
    if not df.empty:
        hist = ROOT / g["history_file"]
        hist.parent.mkdir(parents=True, exist_ok=True)
        df.assign(date=str(date.today())).to_csv(hist, mode="a", header=not hist.exists(), index=False)
    return df, errors


def report(cfg: dict, df: pd.DataFrame, errors: list[str], home: str = "bangalore") -> str:
    lines = [f"# Gold rates by city ({date.today()})", "",
             "_Metal only, per gram, before making charges and 3% GST. Same-day quotes; rates move ~1%/day in volatile markets, "
             "so compare cities only on the same day._", ""]
    if df.empty:
        lines.append("No rates fetched. " + "; ".join(errors))
        return "\n".join(lines)
    ref = df.loc[df.city == home, "24K"]
    ref = float(ref.iloc[0]) if len(ref) else float(df["24K"].median())
    lines += ["| city | 24K Rs/g | 22K Rs/g | vs " + home.title() + " | saving on Rs 5L vs " + home.title() + " |", "|---|---|---|---|---|"]
    for _, r in df.sort_values("24K").iterrows():
        diff = r["24K"] / ref - 1
        k22 = f"{r['22K']:,.0f}" if pd.notna(r.get("22K")) else "-"
        lines.append(f"| {r.city.title()} | {r['24K']:,.0f} | {k22} | {diff:+.2%} | Rs {500000 * -diff:+,.0f} |")
    par = landed_parity(cfg["gold_prices"]["import_duty_pct"])
    if par:
        lines += ["", f"International spot = Rs {par['spot_inr_g']:,.0f}/g; with {cfg['gold_prices']['import_duty_pct']:.0%} import duty "
                      f"Rs {par['landed_ex_gst']:,.0f}/g. Local 24K quotes {ref / par['landed_ex_gst'] - 1:+.1%} vs that landed price "
                      "(a large positive gap means a local premium; negative means a discount, as in heavy selling or smuggling-driven supply)."]
    cheapest = df.sort_values("24K").iloc[0]
    lines += ["", f"**Reading it:** the cheapest city today is {cheapest.city.title()} at {cheapest['24K'] / ref - 1:+.2%} vs {home.title()}. "
              "Buying where you are anyway (Bangalore or Chhattisgarh) is free; a dedicated trip rarely pays. Making charges "
              "(2-6% on coins, 8-20% on jewellery), GST and the buyback haircut dominate, and a gold ETF avoids all three."]
    if errors:
        lines += ["", "Fetch problems: " + "; ".join(errors)]
    return "\n".join(lines)
