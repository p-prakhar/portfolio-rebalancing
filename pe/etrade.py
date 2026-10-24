"""E*TRADE (Morgan Stanley at Work) RSU/ESPP import into tax lots.

Where to get the file (E*TRADE changes menus now and then):
  - Stock plan: At Work > My Account > Benefit History > Download > Download Expanded. The expanded
    view has one row per vest with the vest date, vested quantity and taxable gain.
  - Already sold some shares? At Work > My Account > Gains & Losses > Download > Download Expanded.
    Sold lots are then removed (first-in-first-out, same as Indian tax law for demat shares).
Accepted formats: .csv or .xlsx. Column names are matched loosely, see ALIASES.

India tax: the vest value is taxed as salary (perquisite) at the SBI TT buying rate of the month
end before vest. For capital gains your cost per share is that same FMV, converted to INR.
Shares held over 24 months are long term. This module uses the market USD/INR on the vest date,
a close proxy; replace the price with the rate on your payslip/Form 16 if you want it exact.
"""
from __future__ import annotations

from collections import deque
from datetime import date
from typing import Callable

import pandas as pd

ALIASES = {
    "date": ["vest date", "vest_date", "date acquired", "acquired date", "acquisition date", "date"],
    "qty": ["vested qty.", "vested qty", "vested quantity", "net shares", "sellable qty.", "qty.", "qty", "quantity", "shares"],
    "fmv": ["vest date fmv", "vest fmv", "fmv", "fair market value", "acquisition cost per share",
            "cost basis per share", "adjusted cost basis per share", "price"],
    "gain": ["taxable gain", "taxable income"],
    "type": ["record type", "type"],
}


def _read(path: str) -> pd.DataFrame:
    if path.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    return pd.read_csv(path)


def _find(cols: dict, key: str):
    for a in ALIASES[key]:
        if a in cols:
            return cols[a]
    return None


def _num(x) -> float:
    return float(str(x).replace("$", "").replace(",", "").strip())


def lots_from_etrade(path: str, ticker: str, usd_inr: Callable[[date], float], sold_qty: float = 0.0
                     ) -> tuple[list[dict], dict, list[str]]:
    """Return (lots, meta, warnings). sold_qty: shares already sold (removed oldest first)."""
    df = _read(path)
    df.columns = [str(c).strip() for c in df.columns]
    cols = {c.lower(): c for c in df.columns}
    ctype = _find(cols, "type")
    if ctype is not None:   # expanded export mixes Grant/Vest Schedule/Tax Withholding rows
        keep = df[ctype].astype(str).str.lower().str.contains("vest")
        if keep.any():
            df = df[keep]
    cd, cq, cf, cg = _find(cols, "date"), _find(cols, "qty"), _find(cols, "fmv"), _find(cols, "gain")
    if cd is None or cq is None:
        raise ValueError(f"Need a vest/acquired date and a quantity column; found {list(df.columns)}. "
                         "Use the shell's manual entry instead.")
    warns, rows = [], []
    for _, r in df.iterrows():
        try:
            d = pd.to_datetime(r[cd], errors="coerce")
            q = _num(r[cq])
        except (ValueError, TypeError):
            continue
        if pd.isna(d) or q <= 0:
            continue
        fmv = None
        if cf is not None and pd.notna(r[cf]):
            try:
                fmv = _num(r[cf])
            except ValueError:
                fmv = None
        if fmv is None and cg is not None and pd.notna(r[cg]):
            try:
                fmv = _num(r[cg]) / q
            except ValueError:
                fmv = None
        if not fmv:
            warns.append(f"{d.date()}: no FMV found, skipped; add this vest by hand.")
            continue
        rows.append([d.date(), q, fmv])
    rows.sort()
    dq = deque(rows)
    left = sold_qty
    while left > 1e-9 and dq:
        take = min(dq[0][1], left)
        dq[0][1] -= take
        left -= take
        if dq[0][1] <= 1e-9:
            dq.popleft()
    lots = [{"symbol": ticker.upper(), "qty": round(q, 6), "buy_date": str(d), "price": round(fmv * usd_inr(d), 4), "currency": "USD"}
            for d, q, fmv in dq]
    meta = {ticker.upper(): {"currency": "USD", "tax_class": "foreign", "venue": "ibkr_us", "ticker": ticker.upper(),
                             "sleeve": "global_equity", "name": f"{ticker.upper()} (employer RSUs, E*TRADE)"}}
    if not lots:
        warns.append("No open lots were produced.")
    return lots, meta, warns


def fx_lookup() -> Callable[[date], float]:
    """USD/INR on or before a date, from Yahoo; falls back to the latest rate if the date is out of range."""
    import yfinance as yf
    from . import quiet
    with quiet():
        s = yf.download("INR=X", period="max", progress=False, auto_adjust=True)["Close"]
    s = s.squeeze().dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None)

    def f(d: date) -> float:
        sub = s.loc[:pd.Timestamp(d)]
        return float(sub.iloc[-1] if len(sub) else s.iloc[0])
    return f
