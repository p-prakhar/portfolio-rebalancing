"""Corporate actions: demergers, spin-offs, stock splits, and mergers.

Applies events to tax lots in holdings and broker tradebook imports so that
historical cost basis, acquisition dates (Sec 2(42A)(g)), and share quantities
remain exact and tax-compliant.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .config import ROOT, Holdings, Lot

log = logging.getLogger(__name__)

ACTIONS_PATH = ROOT / "config" / "corporate_actions.yaml"


@dataclass
class ResultingEntity:
    symbol: str
    name: str = ""
    ratio: float = 1.0
    cost_share: float = 1.0
    ticker: str | None = None
    tax_class: str = "in_equity"
    venue: str = "nse_stock"
    sleeve: str = "india_equity"


@dataclass
class Demerger:
    parent: str
    date: date
    name: str
    keep_parent: bool = False
    parent_cost_share: float = 0.0
    resulting: list[ResultingEntity] = field(default_factory=list)


@dataclass
class Split:
    symbol: str
    date: date
    ratio: float
    name: str = ""


@dataclass
class Merger:
    old_symbol: str
    new_symbol: str
    date: date
    ratio: float = 1.0
    name: str = ""


@dataclass
class CorporateActions:
    demergers: list[Demerger] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)
    mergers: list[Merger] = field(default_factory=list)

    def all_events_sorted(self) -> list[Demerger | Split | Merger]:
        events = list(self.demergers) + list(self.splits) + list(self.mergers)
        return sorted(events, key=lambda e: e.date)


def _to_date(val: Any) -> date:
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    return date.fromisoformat(str(val).strip()[:10])


def load_corporate_actions(path: str | Path | None = None) -> CorporateActions:
    p = Path(path or ACTIONS_PATH)
    if not p.exists():
        return CorporateActions()
    doc = yaml.safe_load(p.read_text()) or {}
    demergers = []
    for d in doc.get("demergers", []):
        res = [
            ResultingEntity(
                symbol=r["symbol"],
                name=r.get("name", r["symbol"]),
                ratio=float(r.get("ratio", 1.0)),
                cost_share=float(r.get("cost_share", 1.0)),
                ticker=r.get("ticker", f"{r['symbol']}.NS"),
                tax_class=r.get("tax_class", "in_equity"),
                venue=r.get("venue", "nse_stock"),
                sleeve=r.get("sleeve", "india_equity"),
            )
            for r in d.get("resulting", [])
        ]
        demergers.append(
            Demerger(
                parent=d["parent"].upper(),
                date=_to_date(d["date"]),
                name=d.get("name", f"{d['parent']} demerger"),
                keep_parent=bool(d.get("keep_parent", False)),
                parent_cost_share=float(d.get("parent_cost_share", 0.0)),
                resulting=res,
            )
        )

    splits = [
        Split(
            symbol=s["symbol"].upper(),
            date=_to_date(s["date"]),
            ratio=float(s["ratio"]),
            name=s.get("name", f"{s['symbol']} split {s['ratio']}:1"),
        )
        for s in doc.get("splits", [])
    ]

    mergers = [
        Merger(
            old_symbol=m["old_symbol"].upper(),
            new_symbol=m["new_symbol"].upper(),
            date=_to_date(m["date"]),
            ratio=float(m.get("ratio", 1.0)),
            name=m.get("name", f"{m['old_symbol']} -> {m['new_symbol']}"),
        )
        for m in doc.get("mergers", [])
    ]

    return CorporateActions(demergers=demergers, splits=splits, mergers=mergers)


def apply_corporate_actions(
    lots: list[Lot | dict],
    actions: CorporateActions | None = None,
    as_of: date | None = None,
) -> tuple[list[Lot | dict], list[str]]:
    """Apply corporate actions chronologically to a list of lots.

    Works on either Lot dataclass instances or dict representations.
    Lots purchased on or before an event's record date are transformed.
    """
    if actions is None:
        actions = load_corporate_actions()
    events = actions.all_events_sorted()
    if not events:
        return lots, []

    current_lots: list[Lot | dict] = list(lots)
    notices: list[str] = []

    for event in events:
        if as_of is not None and event.date > as_of:
            continue

        next_lots: list[Lot | dict] = []
        action_applied = False

        for item in current_lots:
            is_obj = isinstance(item, Lot)
            sym = item.symbol if is_obj else item["symbol"]
            buy_dt = _to_date(item.buy_date if is_obj else item["buy_date"])
            qty = float(item.qty if is_obj else item["qty"])
            price = float(item.price if is_obj else item["price"])
            extra = {} if is_obj else {k: v for k, v in item.items() if k not in ("symbol", "qty", "buy_date", "price")}

            if buy_dt > event.date:
                # Lot was bought after the event record date; unaffected
                next_lots.append(item)
                continue

            if isinstance(event, Demerger) and sym == event.parent:
                action_applied = True
                if event.keep_parent:
                    adj_price = round(price * event.parent_cost_share, 4)
                    if is_obj:
                        next_lots.append(Lot(sym, qty, buy_dt, adj_price))
                    else:
                        next_lots.append({"symbol": sym, "qty": qty, "buy_date": str(buy_dt), "price": adj_price, **extra})

                for entity in event.resulting:
                    new_q = round(qty * entity.ratio, 6)
                    new_p = round((price * entity.cost_share) / entity.ratio, 4)
                    if is_obj:
                        next_lots.append(Lot(entity.symbol, new_q, buy_dt, new_p))
                    else:
                        next_lots.append({"symbol": entity.symbol, "qty": new_q, "buy_date": str(buy_dt), "price": new_p, **extra})

            elif isinstance(event, Split) and sym == event.symbol:
                action_applied = True
                new_q = round(qty * event.ratio, 6)
                new_p = round(price / event.ratio, 4)
                if is_obj:
                    next_lots.append(Lot(sym, new_q, buy_dt, new_p))
                else:
                    next_lots.append({"symbol": sym, "qty": new_q, "buy_date": str(buy_dt), "price": new_p, **extra})

            elif isinstance(event, Merger) and sym == event.old_symbol:
                action_applied = True
                new_q = round(qty * event.ratio, 6)
                new_p = round(price / event.ratio, 4)
                if is_obj:
                    next_lots.append(Lot(event.new_symbol, new_q, buy_dt, new_p))
                else:
                    next_lots.append({"symbol": event.new_symbol, "qty": new_q, "buy_date": str(buy_dt), "price": new_p, **extra})

            else:
                next_lots.append(item)

        if action_applied:
            notices.append(f"Applied {event.name} (effective {event.date})")
        current_lots = next_lots

    return current_lots, notices


def resulting_asset_metadata(actions: CorporateActions | None = None) -> dict[str, dict]:
    """Asset metadata for newly created symbols resulting from corporate actions."""
    if actions is None:
        actions = load_corporate_actions()
    meta = {}
    for d in actions.demergers:
        for r in d.resulting:
            meta[r.symbol] = {
                "name": r.name,
                "ticker": r.ticker or f"{r.symbol}.NS",
                "tax_class": r.tax_class,
                "venue": r.venue,
                "sleeve": r.sleeve,
                "currency": "INR",
                "rotate": False,
            }
    return meta


def apply_to_holdings(
    holdings: Holdings,
    actions: CorporateActions | None = None,
    as_of: date | None = None,
) -> tuple[Holdings, list[str]]:
    """Transform holdings lots and populate resulting asset metadata."""
    if actions is None:
        actions = load_corporate_actions()

    new_lots, notices = apply_corporate_actions(holdings.lots, actions, as_of)
    holdings.lots = [l if isinstance(l, Lot) else Lot(l["symbol"], float(l["qty"]), _to_date(l["buy_date"]), float(l["price"])) for l in new_lots]

    # Pending amounts: if symbol underwent corporate action, split amounts accordingly
    if holdings.pending_amounts:
        events = actions.all_events_sorted()
        new_pending = []
        for p in holdings.pending_amounts:
            p_dt = _to_date(p["buy_date"])
            handled = False
            for ev in events:
                if isinstance(ev, Demerger) and p["symbol"] == ev.parent and p_dt <= ev.date:
                    handled = True
                    if ev.keep_parent:
                        new_pending.append({"symbol": ev.parent, "buy_date": p_dt, "amount_inr": p["amount_inr"] * ev.parent_cost_share})
                    for ent in ev.resulting:
                        new_pending.append({"symbol": ent.symbol, "buy_date": p_dt, "amount_inr": p["amount_inr"] * ent.cost_share})
                    break
            if not handled:
                new_pending.append(p)
        holdings.pending_amounts = new_pending

    # Ensure resulting assets have metadata
    meta = resulting_asset_metadata(actions)
    for sym in {l.symbol for l in holdings.lots}:
        if sym in meta and sym not in holdings.meta:
            holdings.meta[sym] = dict(meta[sym])

    # Clean up parent metadata if parent was fully replaced
    for d in actions.demergers:
        if not d.keep_parent and d.parent in holdings.meta:
            if not any(l.symbol == d.parent for l in holdings.lots):
                del holdings.meta[d.parent]

    return holdings, notices


def sync_holdings_file(
    path: str | Path | None = None,
    actions: CorporateActions | None = None,
) -> tuple[bool, list[str]]:
    """If holdings.yaml contains lots affected by corporate actions, update it on disk."""
    p = Path(path or ROOT / "config" / "holdings.yaml")
    if not p.exists():
        return False, []

    doc = yaml.safe_load(p.read_text()) or {}
    raw_lots = doc.get("lots", [])
    if not raw_lots:
        return False, []

    transformed_lots, notices = apply_corporate_actions(raw_lots, actions)
    if not notices:
        return False, []

    doc["lots"] = transformed_lots
    meta = resulting_asset_metadata(actions)
    doc_assets = doc.setdefault("assets", {})
    for sym in {l["symbol"] for l in transformed_lots}:
        if sym in meta and sym not in doc_assets:
            doc_assets[sym] = dict(meta[sym])

    # Remove delisted parent if no longer held
    if actions is None:
        actions = load_corporate_actions()
    for d in actions.demergers:
        if not d.keep_parent and d.parent in doc_assets:
            if not any(l["symbol"] == d.parent for l in transformed_lots):
                del doc_assets[d.parent]

    p.with_suffix(".yaml.bak").write_text(p.read_text())
    p.write_text(
        "# Tax lots (git-ignored). One entry per purchase.\n"
        + yaml.safe_dump(doc, sort_keys=False, default_flow_style=None)
    )
    return True, notices
