"""Tax-aware rebalance planner. Produces trade recommendations, each with a written 'why'."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .config import Lot, Settings
from .costs import fx_cost, leg_cost
from .stopping import ltcg_wait
from .strategy import Target, build_target
from .technical import analyse_all
from .tax import (BUCKETS, bucket_for, compute_tax, effective_rate, fy_end, is_long_term,
                  lt_date, marginal_tax)

RISK_SLEEVES = {"india_equity", "global_equity"}
SAFE_SLEEVES = {"gold", "bonds", "cash"}


@dataclass
class Trade:
    symbol: str
    side: str                      # buy | sell
    value: float
    price: float
    qty: float
    kind: str                      # rebalance | risk_exit | harvest_gain | harvest_loss
    lots: list[tuple[Lot, float]] = field(default_factory=list)   # sells: (lot, qty)
    gains: dict = field(default_factory=dict)                      # bucket -> realised gain
    tax_now: float = 0.0
    econ_tax: float = 0.0
    cost: float = 0.0
    why: list[str] = field(default_factory=list)


@dataclass
class Plan:
    as_of: date
    nav: float
    positions: pd.DataFrame
    target: Target
    trades: list[Trade]
    deferred: list[str]
    blocked: list[str]
    notes: list[str]
    fy_realised: dict
    tax_before: float
    tax_after: float
    usd_inr: float | None = None
    ta: dict = field(default_factory=dict)


def _d(ts) -> date:
    return ts.date() if hasattr(ts, "date") else ts


def positions_table(lots: list[Lot], px_now: pd.Series, today: date, settings: Settings) -> pd.DataFrame:
    rows = []
    for lot in lots:
        a = settings.assets[lot.symbol]
        p_val = px_now.get(lot.symbol) if hasattr(px_now, "get") else None
        p = float(lot.price) if (p_val is None or pd.isna(p_val)) else float(p_val)
        lt = is_long_term(lot, a.tax_class, today, settings)
        ltd = lt_date(lot, a.tax_class, settings)
        gain = lot.qty * (p - lot.price)
        b = bucket_for(a.tax_class, lt)
        rows.append({"symbol": lot.symbol, "qty": lot.qty, "buy_date": lot.buy_date, "cost": lot.cost,
                     "price": p, "value": lot.qty * p, "gain": gain, "long_term": lt,
                     "lt_date": ltd, "days_to_lt": (ltd - today).days if ltd and not lt else 0,
                     "bucket": b, "tax_class": a.tax_class})
    return pd.DataFrame(rows)


def _alpha(px: pd.DataFrame, settings: Settings) -> dict[str, float]:
    """Shrunk trailing-momentum estimate of each asset's excess return (annual)."""
    st = settings.strategy
    r12 = {}
    for s in px.columns:
        ser = px[s].dropna()
        if len(ser) > 252:
            r12[s] = ser.iloc[-1] / ser.iloc[-253] - 1
    med = float(np.median([v for k, v in r12.items() if k in settings.rotatable()] or [0.0]))
    return {s: float(np.clip(st["expected_alpha_shrink"] * (v - med), -st["alpha_cap"], st["alpha_cap"]))
            for s, v in r12.items()}


def _partner(symbol: str, settings: Settings) -> str | None:
    """Another fund tracking the same index, for same-day harvest swaps."""
    a = settings.assets[symbol]
    prim = a.equivalent_of or symbol
    for s, b in settings.assets.items():
        if s != symbol and (s == prim or b.equivalent_of == prim):
            return s
    return None


def _fifo(settings: Settings) -> bool:
    return settings.tax.get("lot_method", "fifo") == "fifo"


def _oldest_rows(pos: pd.DataFrame) -> pd.Index:
    """Index of the oldest lot of each symbol in the positions table (the only one a FIFO sale can reach on its own)."""
    return pos.groupby("symbol").buy_date.idxmin().values


def _pick_lots(lots: list[Lot], qty: float, price: float, tax_class: str, today: date, settings: Settings):
    """Which lots a sale consumes. Default FIFO: depositories and the tax filing treat a sale of a demat security (or fund
    units) as the oldest units first, per account and ISIN, so the investor cannot choose. `lot_method: specific` is only
    right if each lot sits in its own demat account/folio; it then sells losses first, then long-term gains, then
    short-term gains (least gain first)."""
    def key(l):
        if _fifo(settings):
            return (l.buy_date,)
        g = price - l.price
        lt = is_long_term(l, tax_class, today, settings)
        return (0 if g < 0 else 1 if lt else 2, g)
    picked, left = [], qty
    for l in sorted(lots, key=key):
        if left <= 1e-9:
            break
        q = min(l.qty, left)
        picked.append((l, q))
        left -= q
    return picked


def make_plan(today_ts, lots: list[Lot], cash_inr: float, px_hist: pd.DataFrame, vix: pd.Series | None,
              settings: Settings, fy_realised: dict | None = None, policy: str | None = None,
              harvest: bool = True, lrs_used: float = 0.0, usd_inr: float | None = None, guard_level: int | None = None, guard_mem: dict | None = None) -> Plan:
    """policy=None is the live path: it uses the configured policy and adds the crash guard when strategy.crash.enabled.
    Backtests pass explicit policies, so their results only include the guard where a variant asks for `+guard`."""
    today = _d(today_ts)
    st, tm, tx = settings.strategy, settings.timing, settings.tax
    live = policy is None
    policy = policy or st["policy"]
    if not policy.endswith("+guard") and (guard_level is not None or (live and st.get("crash", {}).get("enabled"))):
        policy += "+guard"
    px_now = px_hist.iloc[-1]
    fy_realised = {b: float((fy_realised or {}).get(b, 0.0)) for b in BUCKETS}
    running = dict(fy_realised)
    tax_before = compute_tax(fy_realised, settings).tax

    pos = positions_table(lots, px_now, today, settings)
    held = pos.groupby("symbol")["value"].sum().to_dict() if not pos.empty else {}
    nav = sum(held.values()) + cash_inr
    held_w = {k: v / nav for k, v in held.items()} if nav > 0 else {}
    if cash_inr > 0 and nav > 0 and policy.endswith("+guard"):
        held_w["CASH"] = held_w.get("CASH", 0.0) + cash_inr / nav
    target = build_target(px_hist, vix, settings, policy, held_w, guard_level, guard_mem)
    ta = analyse_all(px_hist, list(held) + list((target.weights or {}).keys()))
    alpha = _alpha(px_hist, settings)
    vol6 = px_hist.pct_change().iloc[-126:].std() * np.sqrt(252)

    trades: list[Trade] = []
    deferred, blocked, notes = [], [], []
    by_sym: dict[str, list[Lot]] = {}
    for l in lots:
        by_sym.setdefault(l.symbol, []).append(l)

    # ---------- rotation trades ----------
    if target.weights is not None and nav > 0:
        tw = dict(target.weights)
        # Equivalent funds (e.g. SETFNIF50 for NIFTYBEES) share the primary's weight in proportion to
        # what you already hold, so the plan never sells one Nifty ETF just to buy another.
        for prim in list(tw):
            group = [prim] + [s for s, a in settings.assets.items() if a.equivalent_of == prim]
            held_g = {s: held.get(s, 0.0) for s in group}
            if len(group) > 1 and sum(held_g.values()) > 0:
                w = tw.pop(prim)
                for s, v in held_g.items():
                    tw[s] = tw.get(s, 0.0) + w * v / sum(held_g.values())
        band = st["min_trade_weight"] * nav
        diffs = {s: tw.get(s, 0.0) * nav - held.get(s, 0.0) for s in set(tw) | set(held)}
        buys = {s: d for s, d in diffs.items() if d > band and not settings.assets[s].sell_only and pd.notna(px_now.get(s))}
        buy_total = sum(buys.values()) or 1.0
        a_buy = sum(alpha.get(s, 0.0) * v for s, v in buys.items()) / buy_total if buys else alpha.get("CASH", 0.0)
        buy_cost_rate = (sum(leg_cost(settings, settings.assets[s], "buy", v, float(px_now[s]), usd_inr)
                             for s, v in buys.items()) / buy_total) if buys else 0.0
        horizon = st["horizon_months"] / 12

        proceeds = 0.0
        for s, d in sorted(diffs.items(), key=lambda x: x[1]):
            full_exit = tw.get(s, 0.0) == 0 and held.get(s, 0.0) > 0
            if d >= 0 or (-d < band and not full_exit):
                continue
            a = settings.assets[s]
            p_val = px_now.get(s) if hasattr(px_now, "get") else None
            if p_val is None or pd.isna(p_val):
                blocked.append(f"CANNOT SELL {s}: no market price on {today} (not yet trading or delisted)")
                continue
            p = float(p_val)
            value = held[s] if full_exit else -d
            pieces = _pick_lots(by_sym[s], value / p, p, a.tax_class, today, settings)
            risk_exit = target.risk_off and (a.sleeve in RISK_SLEEVES or (target.guard and a.sleeve not in SAFE_SLEEVES)) and tw.get(s, 0.0) < held[s] / nav
            keep, gains, why = [], {b: 0.0 for b in BUCKETS}, []
            for lot, q in pieces:
                lt = is_long_term(lot, a.tax_class, today, settings)
                g = q * (p - lot.price)
                ltd = lt_date(lot, a.tax_class, settings)
                days = (ltd - today).days if ltd and not lt else 0
                if not lt and ltd and 0 < days <= tm["ltcg_wait_max_days"] and g > 0 and not target.urgent:
                    w, *_rest, w_why = ltcg_wait(g, q * p, days, float(vol6.get(s, 0.2)),
                                                 effective_rate(bucket_for(a.tax_class, False), settings),
                                                 effective_rate(bucket_for(a.tax_class, True), settings), risk_exit)
                    if w:
                        deferred.append(f"WAIT on selling {q:,.2f} {s} (bought {lot.buy_date}) until {ltd}: {w_why}")
                        if _fifo(settings):
                            break           # FIFO: newer lots cannot be sold ahead of this one
                        continue
                    why.append(w_why)
                keep.append((lot, q))
                gains[bucket_for(a.tax_class, lt)] += g
            if not keep:
                continue
            q_tot = sum(q for _, q in keep)
            v = q_tot * p
            tax_now = marginal_tax(running, gains, settings)
            future = sum(max(0.0, g) * effective_rate("eq_lt" if b.startswith("eq") else ("debt" if b == "debt" else "oth_lt"), settings)
                         for b, g in gains.items()) / (1 + tx["discount_rate"]) ** tx["default_deferral_years"]
            econ = tax_now - future
            cost = leg_cost(settings, a, "sell", v, p, usd_inr) + v * buy_cost_rate
            benefit = v * (a_buy - alpha.get(s, 0.0)) * horizon
            gain_txt = ", ".join(f"{b} Rs {g:,.0f}" for b, g in gains.items() if abs(g) > 1)
            if s in target.review:
                why.extend(target.review[s]["why"])
            if full_exit and not a.rotate and not a.equivalent_of and settings.strategy.get("policy") != "custom" and policy != "custom":
                why.append(f"{s} is outside the model's rotation universe (single stock), so the plan folds it into the target "
                           f"portfolio. Set `rotate: true` or drop this line from the universe if you want to keep it.")
            if risk_exit:
                why.insert(0, f"Risk-reducing sale ({target.risk_reason or 'policy risk filter'}). "
                              f"This sale is about avoiding a deep drawdown, not about return, so it skips the cost/benefit hurdle.")
            elif benefit < st["switch_safety"] * max(cost + econ, 0.0):
                blocked.append(f"HOLD {s} (model would sell Rs {v:,.0f}): estimated benefit of switching Rs {benefit:,.0f} over "
                               f"{st['horizon_months']} months does not beat {st['switch_safety']}x the total cost Rs {cost + econ:,.0f} "
                               f"(trading incl. reinvestment Rs {cost:,.0f} + economic tax cost Rs {econ:,.0f}). "
                               f"Realised gains would be: {gain_txt or 'none'}.")
                continue
            else:
                why.insert(0, f"Rotation: {s} trails what the model wants to buy (estimated edge {a_buy - alpha.get(s, 0):+.1%}/yr after "
                              f"a {st['expected_alpha_shrink']:.0%} haircut). Expected benefit Rs {benefit:,.0f} beats total cost Rs {cost + econ:,.0f}.")
            why.append(f"Realised gains: {gain_txt or 'none'}. Tax this FY rises by Rs {tax_now:,.0f}; "
                       f"economic cost after valuing deferral Rs {econ:,.0f}.")
            for b, g in gains.items():
                running[b] += g
            trades.append(Trade(s, "sell", v, p, q_tot, "risk_exit" if risk_exit else "rebalance", keep, gains,
                                tax_now, econ, leg_cost(settings, a, "sell", v, p, usd_inr), why))
            proceeds += v - trades[-1].cost

        # buys funded by approved sales + idle cash
        funding = proceeds + cash_inr
        want = sum(buys.values())
        scale = min(1.0, funding / want) if want > 0 else 0.0
        spent = 0.0
        for s, d in sorted(buys.items(), key=lambda x: -x[1]):
            v = d * scale
            if v < band / 2:
                continue
            a = settings.assets[s]
            p = float(px_now[s])
            c = leg_cost(settings, a, "buy", v, p, usd_inr)
            why = [f"Target weight {tw.get(s, 0):.0%} vs current {held.get(s, 0) / nav:.0%}."]
            if target.scores is not None and s in target.scores.index:
                r = target.scores.loc[s]
                why.append(f"{s} ranks #{int(r['rank'])} on momentum (score {r['score']:+.2f}, 12m {r['ret_12m']:+.1%}, "
                           f"{r['excess_vs_cash']:+.1%} vs cash).")
            if s in ta:
                why.append(f"Technical view: {ta[s].verdict}." + (f" {ta[s].why[-1]}" if ta[s].why[-1].startswith("Timing") else ""))
            if s == "CASH":
                why.append("Cash sleeve = arbitrage fund (equity taxation, low risk). Parks money the model cannot put to work.")
            if scale < 0.98:
                why.append(f"Scaled to {scale:.0%} of the ideal size because some sales were held back (tax/cost hurdle or LT wait).")
            trades.append(Trade(s, "buy", v - c, p, (v - c) / p, "rebalance", why=why, cost=c))
            spent += v
        leftover = funding - spent
        if leftover > band / 2 and "CASH" not in buys and proceeds > 0:
            trades.append(Trade("CASH", "buy", leftover, float(px_now["CASH"]), leftover / float(px_now["CASH"]),
                                "rebalance", why=["Unallocated sale proceeds parked in the cash sleeve."]))

        usd_flow = sum((t.value if t.side == "buy" else -t.value) for t in trades if settings.assets[t.symbol].currency == "USD")
        if abs(usd_flow) > 0:
            fxc = fx_cost(settings, usd_flow)
            notes.append(f"Net {'remittance to' if usd_flow > 0 else 'repatriation from'} IBKR of Rs {abs(usd_flow):,.0f}: "
                         f"FX conversion cost about Rs {fxc:,.0f}.")
            if usd_flow > 0 and lrs_used + usd_flow > tx["lrs_tcs_threshold"]:
                tcs = (lrs_used + usd_flow - max(lrs_used, tx["lrs_tcs_threshold"])) * tx["lrs_tcs_rate"]
                notes.append(f"LRS: this takes your FY remittances past Rs {tx['lrs_tcs_threshold']:,.0f}, so the bank collects "
                             f"TCS of about Rs {tcs:,.0f}. You get it back against your tax, but it is cash locked until then.")

    # ---------- tax harvesting ----------
    if harvest and not pos.empty:
        sold = {t.symbol for t in trades if t.side == "sell"}
        remaining = tx["ltcg_exemption"] - min(tx["ltcg_exemption"], max(0.0, running["eq_lt"]))
        no_rebuy = [sym for sym, a in settings.assets.items() if a.sell_only]   # harvesting needs a re-buy leg
        cands = pos[(pos.tax_class == "in_equity") & pos.long_term & (pos.gain > 0) & ~pos.symbol.isin(sold) & (pos.symbol != "CASH") & ~pos.symbol.isin(no_rebuy)]
        if _fifo(settings):
            cands = cands[cands.index.isin(_oldest_rows(pos))]       # a sale takes the oldest units, so only those can be harvested
        if remaining >= 5000 and not cands.empty:
            r = cands.assign(gpu=cands.gain / cands.qty).sort_values("gpu", ascending=False).iloc[0]
            g = min(remaining, r.gain)
            q = g / r.gpu
            lot = next(l for l in by_sym[r.symbol] if l.buy_date == r.buy_date and abs(l.qty - r.qty) < 1e-6)
            a = settings.assets[r.symbol]
            v = q * r.price
            c = leg_cost(settings, a, "sell", v, r.price) + leg_cost(settings, a, "buy", v, r.price)
            benefit = g * effective_rate("eq_lt", settings) / (1 + tx["discount_rate"]) ** tx["default_deferral_years"]
            if benefit > c:
                why = [f"Tax-gain harvesting: Rs {remaining:,.0f} of this FY's Rs {tx['ltcg_exemption']:,.0f} LTCG exemption is unused and expires on {fy_end(today)}.",
                       f"Selling {q:,.2f} units of {r.symbol} (lot of {r.buy_date}) books Rs {g:,.0f} of long-term gain at zero tax and resets the cost basis higher, "
                       f"cutting future tax by about Rs {g * effective_rate('eq_lt', settings):,.0f} (worth Rs {benefit:,.0f} today) for about Rs {c:,.0f} in costs.",
                       "Do not buy back the same ETF on the same day (the broker nets same-day buy and sell as intraday, so no gain is booked). "
                       + (f"Simplest: buy the same amount of {_partner(r.symbol, settings)} (same index, other AMC) the same day. "
                          if _partner(r.symbol, settings) else "Buy back the next trading day, or buy an equivalent ETF from another AMC the same day."),
                       "The re-bought units start a new 12-month holding period."]
                running["eq_lt"] += g
                trades.append(Trade(r.symbol, "sell", v, r.price, q, "harvest_gain", [(lot, q)], {"eq_lt": g}, 0.0, -benefit,
                                    leg_cost(settings, a, "sell", v, r.price), why))
                trades.append(Trade(r.symbol, "buy", v, r.price, q, "harvest_gain", why=["Re-buy leg of the gain harvest."],
                                    cost=leg_cost(settings, a, "buy", v, r.price)))
        # loss harvesting
        losers = pos[(pos.gain < -np.maximum(5000, 0.03 * pos.value)) & ~pos.symbol.isin(sold) & (pos.symbol != "CASH") & ~pos.symbol.isin(no_rebuy)]
        if _fifo(settings):
            losers = losers[losers.index.isin(_oldest_rows(pos))]
        for _, r in losers.iterrows():
            a = settings.assets[r.symbol]
            lot = next(l for l in by_sym[r.symbol] if l.buy_date == r.buy_date and abs(l.qty - r.qty) < 1e-6)
            saving = -marginal_tax(running, {r.bucket: r.gain}, settings)
            c = leg_cost(settings, a, "sell", r.value, r.price, usd_inr) + leg_cost(settings, a, "buy", r.value, r.price, usd_inr)
            if saving <= c:
                # A loss with nothing to offset is only worth booking if short term (it can offset anything later).
                # Booking a long-term loss is a trap: it can only offset long-term gains, while the re-bought
                # units start a fresh short-term clock and their rebound would be taxed at the higher STCG rate.
                continue
            why = [f"Tax-loss harvesting: lot of {r.buy_date} is down Rs {-r.gain:,.0f}.",
                   f"Booking it offsets gains already realised this FY and cuts tax by about Rs {saving:,.0f} versus Rs {c:,.0f} in costs. "
                   "Re-buy the next trading day or switch to an equivalent fund. India has no wash-sale rule, but keep it to genuine "
                   "portfolio moves; tax officers can question purely circular trades.",
                   "The re-bought units start a new holding period."]
            running[r.bucket] += r.gain
            trades.append(Trade(r.symbol, "sell", r.value, r.price, r.qty, "harvest_loss", [(lot, r.qty)], {r.bucket: r.gain},
                                -saving, -saving, c / 2, why))
            trades.append(Trade(r.symbol, "buy", r.value, r.price, r.qty, "harvest_loss", why=["Re-buy leg of the loss harvest."], cost=c / 2))

    # ---------- notes ----------
    stocks = [s for s in held if settings.assets[s].venue == "nse_stock"]
    if stocks:
        notes.append(f"Buybacks ({', '.join(stocks)}): from 1 Apr 2026 buyback proceeds are taxed as capital gains again (only the profit, "
                     "at 12.5%/20%), not as dividend. If one of these announces a tender buyback and your holding is worth up to Rs 2 lakh on "
                     "the record date, tendering in the small-shareholder quota is usually worth it. See docs/EDGES.md.")
    soon = pos[(~pos.long_term) & (pos.days_to_lt > 0) & (pos.days_to_lt <= 90)] if not pos.empty else pos
    for _, r in soon.iterrows():
        notes.append(f"{r.symbol} lot of {r.buy_date} turns long term on {r.lt_date} ({r.days_to_lt} days).")
    if fy_end(today) and (fy_end(today) - today).days <= 45:
        notes.append(f"Financial year ends {fy_end(today)}: last chance to use this FY's LTCG exemption and harvest losses.")

    tax_after = compute_tax(running, settings).tax
    return Plan(today, nav, pos, target, trades, deferred, blocked, notes, running, tax_before, tax_after, usd_inr, ta)
