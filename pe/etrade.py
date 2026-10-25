"""E*TRADE (Morgan Stanley at Work) RSU/ESPP import into tax lots.

Where to get the file (E*TRADE changes menus now and then):
  - Stock plan: At Work > My Account > Benefit History > Download > Download Expanded. The expanded
    view has one row per vest with the vest date, vested quantity and taxable gain.
  - Already sold some shares? At Work > My Account > Gains & Losses > Download > Download Expanded.
    Sold lots are then removed (first-in-first-out, same as Indian tax law for demat shares).
Accepted formats: .csv or .xlsx (every sheet is read; ESPP purchases and RSU vests can live on
separate tabs). Column names are matched loosely, see ALIASES.

India tax: the vest value is taxed as salary (perquisite) at the SBI TT buying rate of the month
end before vest. For capital gains your cost per share is that same FMV, converted to INR.
Shares held over 24 months are long term. This module uses the market USD/INR on the vest date,
a close proxy; replace the price with the rate on your payslip/Form 16 if you want it exact.
"""
from __future__ import annotations

import re
from collections import deque
from datetime import date
from typing import Callable

import pandas as pd

ALIASES = {
    "date": ["purchase date", "vest date", "vest_date", "date acquired", "acquired date", "acquisition date", "date"],
    "qty": ["purchased qty.", "purchased qty", "net shares", "sellable qty.", "sellable qty",
            "vested qty.", "vested qty", "vested quantity", "qty.", "qty", "quantity", "shares"],
    "vested_qty": ["vested qty.", "vested qty", "vested quantity"],
    "fmv": ["purchase date fmv", "vest date fmv", "vest fmv", "fmv", "fair market value",
            "acquisition cost per share", "cost basis per share", "adjusted cost basis per share", "price"],
    "gain": ["taxable gain", "taxable income"],
    "type": ["record type", "type"],
}


def _collapse(df: pd.DataFrame) -> pd.DataFrame:
    """Expanded E*TRADE sheets repeat headers (Vested Qty. appears twice); pandas suffixes the copies."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    out: dict[str, pd.Series] = {}
    for c in df.columns:
        base = re.sub(r"\.\d+$", "", c)
        out[base] = out[base].combine_first(df[c]) if base in out else df[c]
    return pd.DataFrame(out)


def _read(path: str) -> pd.DataFrame:
    if path.lower().endswith((".xlsx", ".xls")):
        xl = pd.ExcelFile(path)
        return pd.concat([_collapse(pd.read_excel(xl, sheet_name=s)) for s in xl.sheet_names], ignore_index=True)
    return _collapse(pd.read_csv(path))


def _find(cols: dict, key: str):
    for a in ALIASES[key]:
        if a in cols:
            return cols[a]
    return None


def _candidates(cols: dict, key: str) -> list[str]:
    return [cols[a] for a in ALIASES[key] if a in cols]


def _cell(row: pd.Series, names: list[str]):
    for n in names:
        if n not in row.index:
            continue
        v = row[n]
        if pd.notna(v) and str(v).strip() not in ("", "NA"):
            return v
    return None


def _num(x) -> float:
    return float(str(x).replace("$", "").replace(",", "").strip())


def _attach_gain(df: pd.DataFrame, cols: dict, ctype: str | None) -> pd.DataFrame:
    """Taxable Gain sits on Tax Withholding rows; copy it onto the matching Vest Schedule period."""
    cg, gkey, pkey = _find(cols, "gain"), cols.get("grant number"), cols.get("vest period")
    if ctype is None or cg is None or gkey is None or pkey is None:
        return df
    lookup = {}
    for _, r in df.iterrows():
        if "tax" in str(r[ctype]).lower() and pd.notna(r[cg]):
            lookup[(r[gkey], r[pkey])] = r[cg]
    if not lookup:
        return df
    df = df.copy()
    filled = []
    for _, r in df.iterrows():
        v = r[cg]
        if pd.isna(v):
            v = lookup.get((r[gkey], r[pkey]), v)
        filled.append(v)
    df[cg] = filled
    return df


def lots_from_etrade(path: str, ticker: str, usd_inr: Callable[[date], float], sold_qty: float = 0.0
                     ) -> tuple[list[dict], dict, list[str]]:
    """Return (lots, meta, warnings). sold_qty: shares already sold (removed oldest first)."""
    df = _read(path)
    df.columns = [str(c).strip() for c in df.columns]
    cols = {c.lower(): c for c in df.columns}
    ctype = _find(cols, "type")
    df = _attach_gain(df, cols, ctype)
    if ctype is not None:
        rt = df[ctype].astype(str).str.lower()
        keep = rt.str.contains("purchase") | (rt.str.contains("vest") & ~rt.str.contains("withhold"))
        if keep.any():
            df = df[keep]
    dates, qtys, fmvs, gains = (_candidates(cols, "date"), _candidates(cols, "qty"),
                                _candidates(cols, "fmv"), _candidates(cols, "gain"))
    vested = _candidates(cols, "vested_qty")
    if not dates or not qtys:
        raise ValueError(f"Need a vest/acquired date and a quantity column; found {list(df.columns)}. "
                         "Use the shell's manual entry instead.")
    warns, rows = [], []
    for _, r in df.iterrows():
        raw_d, raw_q = _cell(r, dates), _cell(r, qtys)
        try:
            d = pd.to_datetime(raw_d, errors="coerce")
            q = _num(raw_q) if raw_q is not None else 0.0
        except (ValueError, TypeError):
            continue
        if pd.isna(d) or q <= 0:
            continue
        fmv = None
        raw_f = _cell(r, fmvs)
        if raw_f is not None:
            try:
                fmv = _num(raw_f)
            except ValueError:
                fmv = None
        raw_g = _cell(r, gains)
        if fmv is None and raw_g is not None:
            try:
                denom = q
                raw_v = _cell(r, vested)
                if raw_v is not None:
                    vq = _num(raw_v)
                    if vq > 0:
                        denom = vq
                fmv = _num(raw_g) / denom
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
                             "sleeve": "global_equity", "name": f"{ticker.upper()} (employer RSUs, E*TRADE)",
                             "sell_only": True, "broker": "E*TRADE stock plan (sell only)"}}
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
