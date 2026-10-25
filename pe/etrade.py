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


def _date(x):
    d = pd.to_datetime(x, errors="coerce", format="mixed", dayfirst=False)
    return None if pd.isna(d) else d.date()


def _rsu_vests(df: pd.DataFrame) -> tuple[list, float]:
    """Benefit History 'Restricted Stock' layout: one 'Vest Schedule' row per vest (Vest Date, vested quantity) and a
    matching 'Tax Withholding' row with the Taxable Gain (vested qty x FMV) and the tax withheld. Shares withheld for tax
    (sell-to-cover) never reach you, so the lot is vested minus withheld. Returns
    ([(date, net shares, fmv usd, source)], sellable qty from the grant rows)."""
    cols = list(df.columns)
    rt = df[cols[0]].astype(str).str.strip().str.lower()
    find = lambda name, nth=0: [c for c in cols if str(c).strip().lower().startswith(name)][nth]
    c_grant, c_period, c_vdate = find("grant number"), find("vest period"), find("vest date")
    c_vested = [c for c in cols if str(c).strip().lower().startswith("vested qty")][-1]   # the vest-section column, not the grant total
    c_gain, c_wh = find("taxable gain"), find("withholding amount")
    sellable_cols = [c for c in cols if str(c).strip().lower().startswith("sellable qty")]
    sellable = float(pd.to_numeric(df.loc[rt == "grant", sellable_cols[0]], errors="coerce").fillna(0).sum()) if sellable_cols else 0.0
    num = lambda v: pd.to_numeric(str(v).replace("$", "").replace(",", ""), errors="coerce")
    gains, withheld = {}, {}
    for _, r in df[rt == "tax withholding"].iterrows():
        k = (str(r[c_grant]), str(r[c_period]))
        g, w = num(r[c_gain]), num(r[c_wh])
        if pd.notna(g):
            gains[k] = gains.get(k, 0.0) + float(g)
        if pd.notna(w):
            withheld[k] = withheld.get(k, 0.0) + float(w)
    out = []
    for _, r in df[rt == "vest schedule"].iterrows():
        d = _date(r[c_vdate])
        vested = pd.to_numeric(r[c_vested], errors="coerce")
        if d is None or pd.isna(vested) or vested <= 0 or d > date.today():
            continue            # future vest, nothing delivered yet
        k = (str(r[c_grant]), str(r[c_period]))
        g = gains.get(k)
        fmv = g / vested if g else None
        net = float(vested) - (round(withheld.get(k, 0.0) / fmv) if fmv else 0)
        out.append((d, net, fmv, f"RSU vest {d} (grant {r[c_grant]})"))
    return out, sellable


def _espp_purchases(df: pd.DataFrame) -> tuple[list, float]:
    """Benefit History 'ESPP' layout: one 'Purchase' row per purchase. Indian cost basis is the FMV on the purchase
    date (the discount is taxed as salary), not the discounted purchase price."""
    cols = list(df.columns)
    rt = df[cols[0]].astype(str).str.strip().str.lower()
    find = lambda name: [c for c in cols if str(c).strip().lower().startswith(name)][0]
    c_date, c_fmv = find("purchase date"), find("purchase date fmv")
    c_qty = [c for c in cols if str(c).strip().lower().startswith("net shares")] or [c for c in cols if str(c).strip().lower().startswith("purchased qty")]
    c_qty = c_qty[0]
    sell = [c for c in cols if str(c).strip().lower().startswith("sellable qty")]
    out, sellable = [], 0.0
    for _, r in df[rt == "purchase"].iterrows():
        d = _date(r[c_date])
        q = pd.to_numeric(r[c_qty], errors="coerce")
        fmv = pd.to_numeric(str(r[c_fmv]).replace("$", "").replace(",", ""), errors="coerce")
        if d is None or pd.isna(q) or q <= 0:
            continue
        out.append((d, float(q), None if pd.isna(fmv) else float(fmv), f"ESPP purchase {d}"))
        if sell:
            sellable += float(pd.to_numeric(r[sell[0]], errors="coerce") or 0)
    return out, sellable


def lots_from_benefit_history(path: str, ticker: str, usd_inr: Callable[[date], float]) -> tuple[list[dict], dict, list[str]] | None:
    """The E*TRADE 'Download Expanded' workbook (sheets 'Restricted Stock' and 'ESPP'). None if the file is not that layout."""
    if not path.lower().endswith((".xlsx", ".xls")):
        return None
    sheets = pd.read_excel(path, sheet_name=None)
    rsu = next((df for name, df in sheets.items() if "restricted" in name.lower()), None)
    espp = next((df for name, df in sheets.items() if "espp" in name.lower()), None)
    if rsu is None and espp is None:
        return None
    rows, sellable, warns = [], 0.0, []
    for df, fn in ((rsu, _rsu_vests), (espp, _espp_purchases)):
        if df is not None and not df.empty:
            r, s = fn(df)
            rows += r
            sellable += s
    rows.sort(key=lambda x: x[0])
    total = sum(q for _, q, _, _ in rows)
    sold = max(0.0, total - sellable) if sellable else 0.0
    if sold > 1e-6:
        warns.append(f"The statement shows {sellable:g} sellable shares against {total:g} received, so {sold:g} were sold or "
                     "transferred; the oldest are removed first (Indian FIFO).")
    left, out = sold, []
    for d, q, fmv, src in rows:
        take = min(q, left)
        left -= take
        q -= take
        if q <= 1e-9:
            continue
        if fmv is None:
            warns.append(f"{src}: no market value found, skipped; add it with add-lot.")
            continue
        out.append({"symbol": ticker.upper(), "qty": round(q, 6), "buy_date": str(d), "price": round(fmv * usd_inr(d), 4), "currency": "USD"})
    meta = {ticker.upper(): {"currency": "USD", "tax_class": "foreign", "venue": "ibkr_us", "ticker": ticker.upper(),
                             "sleeve": "global_equity", "name": f"{ticker.upper()} (employer RSU/ESPP, E*TRADE)",
                             "sell_only": True, "broker": "E*TRADE stock plan (sell only)"}}
    return out, meta, warns


def lots_from_etrade(path: str, ticker: str, usd_inr: Callable[[date], float], sold_qty: float = 0.0
                     ) -> tuple[list[dict], dict, list[str]]:
    """Return (lots, meta, warnings). sold_qty: shares already sold (removed oldest first)."""
    bh = lots_from_benefit_history(path, ticker, usd_inr)
    if bh is not None:
        return bh
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
