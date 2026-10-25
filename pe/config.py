"""Settings and holdings loading."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Asset:
    symbol: str
    ticker: str | None
    name: str
    tax_class: str          # in_equity | in_other | in_debt | foreign
    venue: str              # key into settings.costs
    sleeve: str
    currency: str = "INR"
    rotate: bool = True
    equivalent_of: str | None = None
    sell_only: bool = False      # e.g. employer shares in a restricted E*TRADE stock-plan account: can be sold, never bought
    broker: str = ""             # where this holding sits, used in the order steps


@dataclass
class Settings:
    raw: dict
    assets: dict[str, Asset]

    def __getitem__(self, key):
        return self.raw[key]

    @property
    def tax(self) -> dict:
        return self.raw["tax"]

    @property
    def strategy(self) -> dict:
        return self.raw["strategy"]

    @property
    def timing(self) -> dict:
        return self.raw["timing"]

    def rotatable(self) -> list[str]:
        return [s for s, a in self.assets.items() if a.rotate and s != "CASH"]


@dataclass
class Lot:
    symbol: str
    qty: float
    buy_date: date
    price: float            # INR cost per unit

    @property
    def cost(self) -> float:
        return self.qty * self.price


@dataclass
class Holdings:
    lots: list[Lot]
    cash_inr: float = 0.0
    realised_this_fy: dict = field(default_factory=dict)
    lrs_remitted_this_fy_inr: float = 0.0
    pending_amounts: list[dict] = field(default_factory=list)  # lots given as amount_inr
    meta: dict[str, dict] = field(default_factory=dict)         # per-symbol overrides for assets not in the universe


def _to_date(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x))


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or ROOT / "config" / "settings.yaml")
    raw = yaml.safe_load(path.read_text())
    assets = {}
    for a in raw["universe"]:
        assets[a["symbol"]] = Asset(
            symbol=a["symbol"], ticker=a.get("ticker"), name=a.get("name", a["symbol"]),
            tax_class=a["tax_class"], venue=a["venue"], sleeve=a.get("sleeve", "other"),
            currency=a.get("currency", "INR"), rotate=a.get("rotate", True),
            equivalent_of=a.get("equivalent_of"),
        )
    return Settings(raw=raw, assets=assets)


def load_holdings(path: str | Path | None = None) -> Holdings:
    path = Path(path or ROOT / "config" / "holdings.yaml")
    if not path.exists():   # public repo ships only the example; real holdings stay local
        path = ROOT / "config" / "holdings.example.yaml"
    raw = yaml.safe_load(path.read_text())
    lots, pending, meta = [], [], {}
    for sym, m in (raw.get("assets") or {}).items():
        meta[sym] = dict(m or {})
    for l in raw.get("lots", []):
        extra = {k: l[k] for k in ("ticker", "name", "tax_class", "venue", "currency", "sleeve") if k in l}
        if extra:
            meta.setdefault(l["symbol"], {}).update(extra)
        if "qty" in l:
            lots.append(Lot(l["symbol"], float(l["qty"]), _to_date(l["buy_date"]), float(l["price"])))
        else:
            pending.append({"symbol": l["symbol"], "buy_date": _to_date(l["buy_date"]),
                            "amount_inr": float(l["amount_inr"])})
    return Holdings(
        lots=lots, cash_inr=float(raw.get("cash_inr", 0)),
        realised_this_fy=raw.get("realised_this_fy", {}) or {},
        lrs_remitted_this_fy_inr=float(raw.get("lrs_remitted_this_fy_inr", 0)),
        pending_amounts=pending, meta=meta,
    )


ETF_HINTS = ("BEES", "ETF", "IETF", "NIF", "SETF", "GOLD", "SILVER", "LIQUID")


def register_assets(settings: Settings, holdings: Holdings) -> list[str]:
    """Make every held symbol known to the engine, guessing sensible defaults for new ones.

    Defaults: NSE-listed (ticker SYMBOL.NS), listed equity tax rules, stock cost model,
    never bought by the rotation. Override per symbol in holdings.yaml (`assets:` block or on
    the lot itself): ticker (e.g. 500325.BO, AAPL), currency USD, tax_class, venue, sleeve.
    """
    added = []
    for sym in {l.symbol for l in holdings.lots} | {p["symbol"] for p in holdings.pending_amounts} | set(holdings.meta):
        m = holdings.meta.get(sym, {})
        if sym in settings.assets:
            a = settings.assets[sym]
            for k, v in m.items():
                setattr(a, k, v)
            continue
        usd = m.get("currency") == "USD"
        etf = any(h in sym.upper() for h in ETF_HINTS)
        settings.assets[sym] = Asset(
            symbol=sym, ticker=m.get("ticker", sym if usd else f"{sym}.NS"), name=m.get("name", sym),
            tax_class=m.get("tax_class", "foreign" if usd else "in_equity"),
            venue=m.get("venue", "ibkr_us" if usd else ("nse_etf" if etf else "nse_stock")),
            sleeve=m.get("sleeve", "global_equity" if usd else "india_equity"),
            currency="USD" if usd else "INR", rotate=False, sell_only=bool(m.get("sell_only", False)), broker=m.get("broker", ""))
        added.append(sym)
    return added


def resolve_amount_lots(holdings: Holdings, prices) -> Holdings:
    """Turn `amount_inr` lots into qty/price using the close on (or just after) buy_date."""
    for p in holdings.pending_amounts:
        series = prices[p["symbol"]].dropna()
        after = series[series.index >= str(p["buy_date"])]
        if after.empty:
            raise ValueError(f"No price for {p['symbol']} on/after {p['buy_date']}")
        px = float(after.iloc[0])
        holdings.lots.append(Lot(p["symbol"], p["amount_inr"] / px, p["buy_date"], px))
    holdings.pending_amounts = []
    return holdings
