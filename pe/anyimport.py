"""Import "whatever the user has": work out what a file is, then turn it into tax lots.

Kinds recognised (see `detect`):
  tradebook      broker trade history with buys and sells (Zerodha Console, Groww order history, IBKR, plain CSV/Excel)
  snapshot       a holdings list without purchase dates (Kite/Groww holdings export, a spreadsheet you keep)
  etrade         E*TRADE Benefit History / vest list (handled by pe/etrade.py)
  cas            mutual fund Consolidated Account Statement PDF (handled by pe/mf.py)
  holdings_yaml  a holdings.yaml written by this engine
  backup         a backup zip made by the app
Plus `parse_text` for lots typed or pasted as lines of text.

A snapshot has no dates, so the caller supplies one approximate purchase date; that only decides long term versus
short term, and the user can correct single lots afterwards.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from .importer import ALIASES as TRADE_ALIASES

TRADE_EXTRA = {
    "symbol": ["instrument", "stock symbol", "security", "scrip name", "stock name", "name"],
    "date": ["execution date and time", "execution date", "trade date", "order date", "time", "tradedate"],
    "side": ["transaction type", "buy/sell", "b/s", "order type", "transaction"],
    "qty": ["qty.", "filled qty", "traded qty", "trade qty", "units"],
    "price": ["avg price", "avg. price", "average price", "trade price", "executed price", "nav"],
    "value": ["value", "amount", "trade value", "order value", "net amount"],
}
SNAP = {
    "symbol": ["symbol", "tradingsymbol", "instrument", "scrip", "ticker", "stock symbol", "security", "stock name",
               "scheme name", "scrip name", "name", "stock"],
    "qty": ["quantity", "qty", "qty.", "quantity available", "shares", "units", "net qty", "position", "holding qty",
            "total quantity", "balance units"],
    "avg": ["average price", "avg. cost", "avg cost", "avg price", "avg. price", "average buy price", "buy price",
            "average cost price", "average cost", "cost price", "cost basis price", "buy avg", "avg buy price", "price"],
    "invested": ["invested", "buy value", "cost value", "invested value", "cost basis", "invested amount", "total cost",
                 "amount invested", "cost"],
    "currency": ["currency"],
    "date": ["buy date", "buy_date", "purchase date", "date"],
}
ETRADE_HINTS = ("vest date", "vest_date", "date acquired", "acquired date", "acquisition date", "vested qty", "vested qty.")
_SUFFIX = re.compile(r"-(EQ|BE|BZ|SM|ST)$")


def _norm(c) -> str:
    return re.sub(r"\s+", " ", str(c).strip().lower())


def clean_symbol(x) -> str:
    return _SUFFIX.sub("", str(x).strip().upper())


def _num(x) -> float | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = re.sub(r"[^\d.\-eE]", "", str(x).replace(",", ""))
    try:
        return float(s)
    except ValueError:
        return None


def _known_tokens() -> set[str]:
    out = set()
    for d in (TRADE_ALIASES, TRADE_EXTRA, SNAP):
        for v in d.values():
            out.update(v)
    out.update(ETRADE_HINTS)
    return out


def read_table(path: str) -> pd.DataFrame:
    """Read a CSV or Excel sheet whose header row may sit below a few title lines (broker exports often do that)."""
    p = str(path).lower()
    if p.endswith((".xlsx", ".xls", ".xlsm")):
        raw = pd.read_excel(path, header=None, dtype=object)
    else:
        import csv
        data = Path(path).read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        head = "\n".join(text.splitlines()[:30])
        delim = max(",;\t|", key=head.count)
        rows = [r for r in csv.reader(text.splitlines(), delimiter=delim)]
        width = max((len(r) for r in rows), default=0)
        raw = pd.DataFrame([[(v if v != "" else None) for v in r] + [None] * (width - len(r)) for r in rows], dtype=object)
    known = _known_tokens()
    best, best_hits = 0, 0
    for i in range(min(len(raw), 40)):
        hits = sum(_norm(v) in known for v in raw.iloc[i].tolist() if v is not None and not (isinstance(v, float) and pd.isna(v)))
        if hits > best_hits:
            best, best_hits = i, hits
    df = raw.iloc[best + 1:].copy()
    df.columns = [str(c).strip() if c is not None and not (isinstance(c, float) and pd.isna(c)) else f"col{j}"
                  for j, c in enumerate(raw.iloc[best].tolist())]
    return df.dropna(how="all").reset_index(drop=True)


def _pick(cols: dict, names: list[str]):
    for n in names:
        if n in cols:
            return cols[n]
    return None


def classify(df: pd.DataFrame) -> str:
    cols = {_norm(c): c for c in df.columns}
    if any(h in cols for h in ETRADE_HINTS):
        return "etrade"
    has = lambda k, extra=None: _pick(cols, TRADE_ALIASES.get(k, []) + (extra or TRADE_EXTRA).get(k, [])) is not None
    if has("side") and has("date") and has("qty") and has("symbol"):
        side = _pick(cols, TRADE_ALIASES["side"] + TRADE_EXTRA["side"])
        vals = df[side].dropna().astype(str).str.strip().str.lower().str[:1]
        if len(vals) and vals.isin(["b", "s"]).mean() > 0.6:
            return "tradebook"
    if _pick(cols, SNAP["symbol"]) is not None and _pick(cols, SNAP["qty"]) is not None:
        return "snapshot"
    return "unknown"


def detect(path: str) -> str:
    p = str(path).lower()
    if p.endswith(".pdf"):
        return "cas"
    if p.endswith((".yaml", ".yml")):
        return "holdings_yaml"
    if p.endswith(".zip"):
        return "backup"
    if p.endswith((".xlsx", ".xls", ".xlsm")):
        try:
            names = [n.lower() for n in pd.ExcelFile(path).sheet_names]
            if any("restricted" in n or "espp" in n for n in names):
                return "etrade"
        except Exception:
            return "unknown"
    try:
        return classify(read_table(path))
    except Exception:
        return "unknown"


def parse_dates(s: pd.Series) -> tuple[pd.Series, bool]:
    """Dates from mixed broker formats. Returns (dates, ambiguous): Indian exports write day first, US ones month first;
    when every value could be read both ways we assume day first and say so."""
    txt = s.astype(str).str.strip()
    iso = txt.str.match(r"^\d{4}[-/.]?\d{2}[-/.]?\d{2}")
    if iso.all():
        return pd.to_datetime(txt.str.slice(0, 10).str.replace(r"[/.]", "-", regex=True), errors="coerce", format="mixed").dt.date, False
    parts = txt.str.extract(r"^(\d{1,2})[-/.\s](\d{1,2}|[A-Za-z]{3,9})[-/.\s,]")
    first = pd.to_numeric(parts[0], errors="coerce")
    second = pd.to_numeric(parts[1], errors="coerce")
    if second.isna().all() or (first > 12).any():
        return pd.to_datetime(txt, errors="coerce", dayfirst=True, format="mixed").dt.date, False
    if (second > 12).any():
        return pd.to_datetime(txt, errors="coerce", dayfirst=False, format="mixed").dt.date, False
    return pd.to_datetime(txt, errors="coerce", dayfirst=True, format="mixed").dt.date, True


def normalise_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Any trade-history layout -> the canonical columns pe/importer.py reads (symbol, trade_date, trade_type, quantity, price)."""
    cols = {_norm(c): c for c in df.columns}
    warns: list[str] = []
    get = lambda k: _pick(cols, TRADE_ALIASES.get(k, []) + TRADE_EXTRA.get(k, []))
    c = {k: get(k) for k in ("symbol", "date", "side", "qty", "price")}
    cval = _pick(cols, TRADE_EXTRA["value"])
    missing = [k for k in ("symbol", "date", "side", "qty") if c[k] is None]
    if missing or (c["price"] is None and cval is None):
        raise ValueError(f"This looks like a trade history but has no {', '.join(missing) or 'price'} column. Columns found: {list(df.columns)}")
    out = pd.DataFrame()
    out["symbol"] = df[c["symbol"]].map(clean_symbol)
    dates, ambiguous = parse_dates(df[c["date"]])
    out["trade_date"] = dates.astype(str)
    if ambiguous:
        warns.append("Dates like 03-04-2024 were read as day-month-year (3 April). If your file is month first, fix the dates of the lots after importing.")
    out["trade_type"] = df[c["side"]].astype(str).str.strip().str.lower()
    out["quantity"] = df[c["qty"]].map(_num).abs()
    if c["price"] is not None:
        out["price"] = df[c["price"]].map(_num)
    else:
        out["price"] = df[cval].map(_num).abs() / out["quantity"]
    for extra, name in ((_pick(cols, ["currency"]), "currency"), (_pick(cols, ["usd_inr", "fx"]), "usd_inr"),
                        (_pick(cols, ["trade_id", "trade id", "trade no", "trade no."]), "trade_id")):
        if extra is not None:
            out[name] = df[extra].values
    status = _pick(cols, ["order status", "status"])
    if status is not None:
        ok = df[status].astype(str).str.lower().str.contains("exec|complete|filled|success|traded", regex=True)
        if ok.any():
            out = out[ok.values]
    bad = out["quantity"].isna() | out["price"].isna() | (out["trade_date"] == "NaT") | ~out["trade_type"].str[:1].isin(["b", "s"])
    if bad.any():
        warns.append(f"{int(bad.sum())} row(s) without a readable date, side, quantity or price were skipped.")
    return out[~bad].reset_index(drop=True), warns


def lots_from_snapshot(df: pd.DataFrame, approx_date: date, usd_inr: float | None = None) -> tuple[list[dict], list[str]]:
    """Holdings list (symbol, quantity, average cost) -> one lot per symbol dated `approx_date` (or the file's own date column)."""
    cols = {_norm(c): c for c in df.columns}
    csym, cq = _pick(cols, SNAP["symbol"]), _pick(cols, SNAP["qty"])
    cavg, cinv, ccur, cdate = (_pick(cols, SNAP[k]) for k in ("avg", "invested", "currency", "date"))
    if csym is None or cq is None:
        raise ValueError(f"Need a symbol and a quantity column. Columns found: {list(df.columns)}")
    if cavg is None and cinv is None:
        raise ValueError(f"Need an average price or an invested amount column. Columns found: {list(df.columns)}")
    lots, warns = [], []
    if _norm(csym) in ("stock name", "scheme name", "name", "scrip name") and _pick(cols, ["symbol", "tradingsymbol", "instrument", "ticker"]) is None:
        warns.append("This file lists names, not exchange symbols. Check each symbol after importing (for example TCS, not 'Tata Consultancy').")
    dates = parse_dates(df[cdate])[0] if cdate is not None else None
    for i, r in df.iterrows():
        sym, q = clean_symbol(r[csym]), _num(r[cq])
        if not sym or sym in ("NAN", "TOTAL") or not q or q <= 0:
            continue
        px = _num(r[cavg]) if cavg is not None else None
        if not px and cinv is not None and _num(r[cinv]):
            px = _num(r[cinv]) / q
        if not px or px <= 0:
            warns.append(f"{sym}: no cost found, skipped.")
            continue
        lot = {"symbol": sym, "qty": round(q, 6), "buy_date": str(approx_date), "price": round(px, 4)}
        if dates is not None and isinstance(dates.iloc[i], date) and not pd.isna(dates.iloc[i]):
            lot["buy_date"] = str(dates.iloc[i])
        if ccur is not None and str(r[ccur]).strip().upper() == "USD":
            if not usd_inr:
                raise ValueError("need_usd_inr")
            lot["price"] = round(px * usd_inr, 4)
            lot["currency"] = "USD"
        lots.append(lot)
    if lots and dates is None:
        warns.append(f"The file has no purchase dates, so every lot is dated {approx_date}. That only affects long-term versus short-term tax; edit a lot to correct it.")
    return lots, warns


_DATE = re.compile(r"\b(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b")
_NUMBER = re.compile(r"(?<![A-Za-z\d])(?:rs\.?|inr|₹|\$)?\s*(-?\d[\d,]*\.?\d*)\s*(k|l|lakh|lakhs|lac|cr|crore)?(?![A-Za-z\d])", re.I)
_MULT = {"k": 1e3, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "cr": 1e7, "crore": 1e7}


def parse_text(text: str, default_date: date) -> tuple[list[dict], list[str]]:
    """Lots typed as lines. Two shapes per line, date optional:
        SYMBOL QTY PRICE [DATE]      e.g.  TCS 12 @ 3900 2024-09-16
        SYMBOL AMOUNT [DATE]         e.g.  NIFTYBEES 5 lakh 14/08/2024   (units worked out from that day's close)
    """
    lots, warns = [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip().strip(",;")
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9&.\-]*)\b(.*)$", line)
        if not m:
            warns.append(f"Line {n}: start with the symbol, for example 'TCS 12 3900 2024-09-16'.")
            continue
        sym, rest = clean_symbol(m.group(1)), m.group(2)
        d = default_date
        dm = _DATE.search(rest)
        if dm:
            parsed = parse_dates(pd.Series([dm.group(1)]))[0].iloc[0]
            if isinstance(parsed, date) and not pd.isna(parsed):
                d = parsed
            rest = rest.replace(dm.group(1), " ")
        nums = []
        for v, unit in _NUMBER.findall(rest.replace("@", " ").replace("x", " ")):
            f = _num(v)
            if f is not None:
                nums.append(f * _MULT.get(unit.lower(), 1))
        usd = bool(re.search(r"\$|\busd\b", rest, re.I))
        if len(nums) >= 2:
            lot = {"symbol": sym, "qty": nums[0], "buy_date": str(d), "price": nums[1]}
        elif len(nums) == 1:
            lot = {"symbol": sym, "buy_date": str(d), "amount_inr": nums[0]}
        else:
            warns.append(f"Line {n} ({sym}): add a quantity and price, or an amount.")
            continue
        if usd:
            lot["currency"] = "USD"
        lots.append(lot)
    return lots, warns
