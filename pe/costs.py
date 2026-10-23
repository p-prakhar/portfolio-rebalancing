"""Transaction cost models (INR). Statutory levies per the blueprint; spreads are estimates."""
from __future__ import annotations

from .config import Asset, Settings


def cost_breakdown(settings: Settings, asset: Asset, side: str, value: float, price_inr: float,
                   usd_inr: float | None = None) -> dict[str, float]:
    """Itemised INR cost of buying or selling `value` INR of `asset`. Excludes FX conversion."""
    if value <= 0:
        return {}
    c = settings["costs"][asset.venue]
    if asset.venue == "ibkr_us":
        fx = usd_inr or 85.0
        shares = value / price_inr
        comm_usd = max(c["min_commission_usd"], shares * c["commission_per_share_usd"])
        return {"commission": min(comm_usd * fx, value * c["max_commission_pct"]),
                "SEC fee": value * c["sec_fee_sell"] if side == "sell" else 0.0,
                "spread": value * c["half_spread"]}
    if asset.venue == "cash_fund":
        return {"spread/exit load": value * (c.get("half_spread", 0) + (c.get("exit_load", 0) if side == "sell" else 0))}
    exch = value * c["exch"]
    sebi = value * c["sebi"]
    return {"brokerage": c["brokerage"],
            "STT": value * (c["stt_buy"] if side == "buy" else c["stt_sell"]),
            "exchange": exch, "SEBI": sebi,
            "GST": c["gst"] * (c["brokerage"] + exch + sebi),
            "stamp duty": value * c["stamp_buy"] if side == "buy" else 0.0,
            "DP charge": c["dp_per_sell"] if side == "sell" else 0.0,
            "spread": value * c["half_spread"]}


def leg_cost(settings: Settings, asset: Asset, side: str, value: float, price_inr: float,
             usd_inr: float | None = None) -> float:
    return sum(cost_breakdown(settings, asset, side, value, price_inr, usd_inr).values())


def describe(settings: Settings, asset: Asset, side: str, value: float, price_inr: float,
             usd_inr: float | None = None) -> str:
    b = cost_breakdown(settings, asset, side, value, price_inr, usd_inr)
    tot = sum(b.values())
    items = ", ".join(f"{k} Rs {v:,.0f}" for k, v in b.items() if v >= 0.5)
    return f"Transaction cost about Rs {tot:,.0f} ({tot / value:.2%} of the trade): {items or 'nil'}."


def fx_cost(settings: Settings, net_usd_flow_inr: float) -> float:
    """Cost of converting the net INR<->USD flow of a rebalance (bank/remittance spread)."""
    return abs(net_usd_flow_inr) * settings["costs"]["ibkr_us"]["fx_one_way"]
