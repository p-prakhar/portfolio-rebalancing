"""Two questions the app answers from price history instead of from waiting:

1. `prepare` / `run_strategy`: how would each strategy have done on the investor's own lots, from the days they bought them?
   The lots held on the start day open the book; every later purchase joins on its own date, the same for every strategy,
   so the strategies differ only in what they did with the money. One path through one stretch of history: it shows what
   happened, it does not rank strategies (python main.py validate does that over rolling 10-year windows).

2. `replay_leg`: where would the waiting window (the secretary rule in pe/stopping.py) be today if the check had been run
   every day? The plan is recomputed on each of the last n trading days with data up to that day; the window for a trade
   starts on the first day of the unbroken run of days that asked for it, and the rule is then stepped through the closes
   already seen. No look-ahead: day k's decision uses closes up to day k only.
"""
from __future__ import annotations

import math

import pandas as pd

from .config import Lot
from .stopping import secretary_cutoff, secretary_decision

# (id, name, policy, harvest). All fill at once so the comparison is about the strategy, not the fill rule.
STRATEGIES = [
    ("yours", "What you did: buy and hold", "buy_hold", False),
    ("hold_harvest", "Hold, with tax harvesting", "buy_hold", True),
    ("core_xs", "Core and momentum satellite", "core_xs", True),
    ("custom", "Keep what I own, exit on warnings", "custom", True),
    ("core_satellite", "Core and trend satellite", "core_satellite", True),
    ("static_mix", "Fixed mix", "static_mix", True),
    ("dual_momentum", "Dual momentum", "dual_momentum", True),
    ("xs_momentum", "Momentum rotation", "xs_momentum", True),
    ("risk_parity", "Risk parity", "risk_parity", True),
    ("trend_vol", "Trend with volatility target", "trend_vol", True),
    ("daa", "Defensive asset allocation", "daa", True),
]
RANGES = {"purchase": None, "1y": 365, "6m": 182}
SLEEVE_ORDER = ["india_equity", "global_equity", "gold", "bonds", "debt", "commodity", "metals", "semis", "cash"]
MAX_POINTS = 120
WARMUP = 260        # trading days of history the signals need before the first decision


def _ffill_listed(px: pd.DataFrame) -> pd.DataFrame:
    """Carry the last price over holidays and dropped prints, never back-fill before an instrument's first price."""
    first = px.apply(lambda c: c.first_valid_index())
    out = px.ffill()
    for c, d0 in first.items():
        if d0 is not None:
            out.loc[out.index < d0, c] = float("nan")
    return out


def prepare(lots: list[Lot], px: pd.DataFrame, range_key: str = "purchase") -> dict:
    """Pick the start day and split the lots into those held at the start and those that join later."""
    if not lots:
        raise ValueError("no lots")
    px = _ffill_listed(px)
    idx = px.index
    if len(idx) < 60:
        raise ValueError("not enough price history")
    first_buy = pd.Timestamp(min(l.buy_date for l in lots))
    days = RANGES.get(range_key)
    want = first_buy if days is None else max(first_buy, idx[-1] - pd.Timedelta(days=days))
    earliest = idx[min(WARMUP, len(idx) - 40)]
    after = idx[idx >= max(want, earliest)]
    start = after[0] if len(after) else idx[-40]
    init = [l for l in lots if pd.Timestamp(l.buy_date) <= start]
    inflows: dict = {}
    for l in lots:
        if pd.Timestamp(l.buy_date) > start:
            on = idx[idx >= pd.Timestamp(l.buy_date)]
            inflows.setdefault(on[0] if len(on) else idx[-1], []).append(l)
    if not init:        # nothing was owned yet on the start day: begin on the first purchase inside the range
        start = min(inflows)
        init = inflows.pop(start)
    span = idx[idx >= start]
    step = max(1, math.ceil(len(span) / MAX_POINTS))
    keep = sorted(set(range(0, len(span), step)) | {len(span) - 1})
    row0 = px.loc[start]
    nav0 = sum(l.qty * (float(row0[l.symbol]) if l.symbol in row0 and row0[l.symbol] == row0[l.symbol] else l.price) for l in init)
    dep = pd.Series(0.0, index=span)
    for ts, ls in inflows.items():
        row = px.loc[ts]
        dep.loc[ts] += sum(l.qty * (float(row[l.symbol]) if l.symbol in row and row[l.symbol] == row[l.symbol] else l.price) for l in ls)
    invested = nav0 + dep.cumsum()
    return {"px": px, "start": start, "init": init, "inflows": inflows, "span": span, "step": step, "keep": keep, "dep": dep,
            "invested": invested, "clamped": bool(want < earliest), "first_buy": first_buy, "range": range_key if range_key in RANGES else "purchase"}


def setup_view(ctx: dict) -> dict:
    span, keep = ctx["span"], ctx["keep"]
    return {"range": ctx["range"], "start": str(ctx["start"].date()), "end": str(span[-1].date()), "days": len(span),
            "first_buy": str(ctx["first_buy"].date()), "clamped": ctx["clamped"],
            "dates": [str(span[i].date()) for i in keep], "invested": [round(float(ctx["invested"].iloc[i])) for i in keep],
            "invested_total": round(float(ctx["invested"].iloc[-1])), "deposits": int(len(ctx["inflows"])),
            "lots": len(ctx["init"]) + sum(len(v) for v in ctx["inflows"].values()),
            "strategies": [{"id": s[0], "name": s[1]} for s in STRATEGIES]}


def run_strategy(ctx: dict, sid: str, vix, settings, fx=None) -> dict:
    from .backtest import run_variant
    from .tax import compute_tax
    spec = next((s for s in STRATEGIES if s[0] == sid), None)
    if spec is None:
        raise ValueError(f"unknown strategy {sid}")
    _, name, policy, harvest = spec
    span, keep = ctx["span"], ctx["keep"]
    nav, book, accrued, liq = run_variant(name, policy, "immediate", harvest, ctx["init"], ctx["px"], vix, settings, ctx["start"], fx,
                                          {"inflows": ctx["inflows"], "record_every": ctx["step"]})
    # time-weighted return: money added on a day is not counted as that day's gain
    r = ((nav - ctx["dep"]) / nav.shift(1) - 1).iloc[1:].fillna(0.0)
    unit = pd.concat([pd.Series([1.0], index=[span[0]]), (1 + r).cumprod()])
    end, invested = float(nav.iloc[-1]), float(ctx["invested"].iloc[-1])
    sleeve_of = lambda sym: settings.assets[sym].sleeve if sym in settings.assets else "other"
    seen: dict[str, list[float]] = {}
    for j, (_, snap, cash) in enumerate(book.alloc):
        vals: dict[str, float] = {"cash": cash} if cash > 1 else {}
        for sym, v in snap.items():
            k = sleeve_of(sym)
            vals[k] = vals.get(k, 0.0) + v
        for k, v in vals.items():
            seen.setdefault(k, [0.0] * len(book.alloc))[j] = round(v)
    order = [k for k in SLEEVE_ORDER if k in seen] + sorted(k for k in seen if k not in SLEEVE_ORDER)
    months: dict[str, dict] = {}
    for ts in span:
        months.setdefault(f"{ts.year}-{ts.month:02d}", {"bought": 0.0, "sold": 0.0, "harvest": 0.0})
    for day, side, _sym, value, kind in book.fills:
        m = months[f"{day.year}-{day.month:02d}"]
        if kind.startswith("harvest"):
            m["harvest"] += value / 2        # a harvest is a sale and an equal re-buy: count the round trip once
        else:
            m["bought" if side == "buy" else "sold"] += value
    real = [f for f in book.fills if not f[4].startswith("harvest")]
    return {"id": sid, "name": name, "end_value": round(end), "tax_if_sold": round(liq), "after_tax_value": round(end - liq),
            "invested": round(invested), "gain_after_tax": round(end - liq - invested), "twr": float(unit.iloc[-1] - 1),
            "max_drawdown": float((unit / unit.cummax() - 1).min()), "taxes_paid": round(book.taxes_paid), "tax_accrued": round(accrued),
            "costs": round(book.costs_paid), "trades": len(real), "trade_days": len({f[0] for f in real}), "harvests": (len(book.fills) - len(real)) // 2,
            "curve": [round(float(nav.iloc[i])) for i in keep],
            "alloc": [{"sleeve": k, "values": seen[k]} for k in order],
            "flows": [{"month": k, "bought": round(v["bought"]), "sold": round(v["sold"]), "harvest": round(v["harvest"])} for k, v in months.items()],
            "moves": [{"date": str(d), "side": s, "symbol": sym, "value": round(v), "kind": k} for d, s, sym, v, k in real[-40:]]}


# ---------------------------------------------------------------- the waiting window, replayed
def replay_leg(dates: list[str], prices: list[float], signal: list[bool], n: int, side: str) -> dict:
    """`dates`/`prices`: the last n closes (oldest first, today last). `signal[i]`: was this trade on the plan on day i?
    Returns the window as it would stand today, plus the same replay started a full n days ago for comparison."""
    assert len(prices) == len(signal) == len(dates) and prices
    run = 0
    for ok in reversed(signal):
        if not ok:
            break
        run += 1
    run = max(1, min(run, n))

    def step(first: int) -> dict:
        obs, fired, out = [], None, []
        for i in range(first, len(prices)):
            obs.append(prices[i])
            dec, why = secretary_decision(obs, n, side)
            if fired is None and dec == "execute":
                fired = i
            out.append({"i": i, "decision": dec, "why": why})
        day = len(obs)
        today = prices[-1]
        res = {"opened": dates[first], "day": day, "left": max(n - day, 0), "steps": out,
               "fired": None if fired is None else dates[fired], "fired_i": fired, "fill": None if fired is None else prices[fired]}
        if fired is None:
            res.update(decision="observe", reason="watching" if day <= secretary_cutoff(n) else "no_new_best", why=out[-1]["why"])
        elif fired == len(prices) - 1:
            res.update(decision="execute", reason="last_day" if day >= n and "last day" in out[-1]["why"] else "best_today", why=out[-1]["why"])
        else:
            fill = prices[fired]
            edge = (fill - today) / fill if side == "buy" else (today - fill) / fill       # above zero: today is the better price for you
            res.update(decision="execute", reason="fired_earlier", edge=edge,
                       why=f"The rule would have traded on {dates[fired]} at {fill:,.2f}. Today's price is {today:,.2f}, "
                           f"{abs(edge):.1%} {'better' if edge >= 0 else 'worse'} for you than that fill.")
        return res

    return {"side": side, "n": n, "cutoff": secretary_cutoff(n), "run": run, "dates": dates, "prices": prices, "signal": signal,
            "now": step(len(prices) - run), "full": step(0)}
