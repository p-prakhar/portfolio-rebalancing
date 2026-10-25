"""Build tax lots from a broker tradebook (Zerodha Console, Groww, IBKR flex CSV, or a plain CSV).

Accepted columns (case-insensitive, first match wins):
  symbol : symbol, tradingsymbol, scrip, ticker
  date   : trade_date, date, order_execution_time, datetime
  side   : trade_type, side, type, buy/sell, action      values like buy/sell/b/s
  qty    : quantity, qty, shares
  price  : price, trade_price, tradeprice, rate
optional:
  currency : USD rows get their price converted to INR with `usd_inr` (or `fx`) if present,
             otherwise with the --usd-inr value you pass.
Sells are matched against buys first-in-first-out, which is how Indian tax law treats
demat holdings.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date

import pandas as pd
import yaml

ALIASES = {
    "symbol": ["symbol", "tradingsymbol", "scrip", "ticker"],
    "date": ["trade_date", "date", "order_execution_time", "datetime", "date/time"],
    "side": ["trade_type", "side", "type", "buy/sell", "action"],
    "qty": ["quantity", "qty", "shares"],
    "price": ["price", "trade_price", "tradeprice", "rate", "t. price"],
    "currency": ["currency"],
    "fx": ["usd_inr", "fx"],
}


def _col(df: pd.DataFrame, key: str, required=True):
    cols = {c.lower().strip(): c for c in df.columns}
    for a in ALIASES[key]:
        if a in cols:
            return cols[a]
    if required:
        raise ValueError(f"Tradebook needs a '{key}' column (any of {ALIASES[key]}); found {list(df.columns)}")
    return None


def lots_from_tradebook(path: str, usd_inr: float | None = None) -> tuple[list[dict], list[str]]:
    df = pd.read_csv(path)
    c = {k: _col(df, k, k not in ("currency", "fx")) for k in ALIASES}
    df["_date"] = pd.to_datetime(df[c["date"]], dayfirst=False, errors="coerce").dt.date
    df = df.sort_values("_date", kind="stable")
    book: dict[str, deque] = defaultdict(deque)
    warnings, usd_syms = [], set()
    for _, r in df.iterrows():
        sym = str(r[c["symbol"]]).strip().upper().replace("-EQ", "")
        side = str(r[c["side"]]).strip().lower()[:1]
        q = abs(float(r[c["qty"]]))
        px = float(r[c["price"]])
        if c["currency"] and str(r[c["currency"]]).upper() == "USD":
            usd_syms.add(sym)
            fx = float(r[c["fx"]]) if c["fx"] and pd.notna(r[c["fx"]]) else usd_inr
            if not fx:
                raise ValueError(f"{sym}: USD trade but no usd_inr column or --usd-inr value")
            px *= fx
        if side == "b":
            book[sym].append([q, r["_date"], px])
        elif side == "s":
            left = q
            while left > 1e-9 and book[sym]:
                lot = book[sym][0]
                take = min(lot[0], left)
                lot[0] -= take
                left -= take
                if lot[0] <= 1e-9:
                    book[sym].popleft()
            if left > 1e-9:
                warnings.append(f"{sym}: sold {left:g} more than bought in this file (earlier buys missing?)")
    lots = [{"symbol": s, "qty": round(q, 6), "buy_date": str(d), "price": round(p, 4),
             **({"currency": "USD"} if s in usd_syms else {})}
            for s, dq in book.items() for q, d, p in dq if q > 1e-9]
    from .corporate_actions import apply_corporate_actions, resulting_asset_metadata
    lots, ca_notices = apply_corporate_actions(lots)
    warnings.extend(ca_notices)
    return lots, warnings


def write_holdings(lots: list[dict], out_path: str, cash_inr: float = 0.0) -> None:
    from .corporate_actions import resulting_asset_metadata
    meta = resulting_asset_metadata()
    held_syms = {l["symbol"] for l in lots}
    assets = {sym: meta[sym] for sym in held_syms if sym in meta}
    doc = {"lots": lots, "cash_inr": cash_inr,
           "realised_this_fy": {"equity_stcg": 0, "equity_ltcg": 0, "other_stcg": 0, "other_ltcg": 0},
           "lrs_remitted_this_fy_inr": 0}
    if assets:
        doc["assets"] = assets
    header = (f"# Generated from a tradebook on {date.today()}. Check it, then add an `assets:` block for any\n"
              "# symbol whose ticker/tax treatment the defaults get wrong (see README).\n")
    with open(out_path, "w") as f:
        f.write(header + yaml.safe_dump(doc, sort_keys=False, default_flow_style=None))
