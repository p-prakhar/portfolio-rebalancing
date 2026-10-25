"""Walk-forward backtest that runs the exact live planner day by day, with lots, Indian tax and costs.

Signals use data up to the close of the check day; orders fill at later closes per the
execution mode. Tax for each FY is paid out of the portfolio on the last trading day of
March. At the end we report NAV, tax accrued on gains realised in the current FY, and the
value if everything were sold on the last day ("liquidation value").
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import crash
from .config import Lot, Settings
from .costs import fx_cost, leg_cost
from .engine import Trade, make_plan
from .stopping import secretary_decision, threshold_decision
from .timing import apply_gate
from .tax import BUCKETS, bucket_for, compute_tax, fy_start_year, is_long_term

VARIANTS = [
    # name, policy, execution, harvest
    ("Buy & hold (your current portfolio)", "buy_hold", "immediate", False),
    ("Buy & hold + tax harvesting", "buy_hold", "immediate", True),
    ("Custom: keep holdings, exit on TA+momentum", "custom", "immediate", True),
    ("Dual momentum (Nifty/Gold/Cash)", "dual_momentum", "immediate", True),
    ("Cross-sectional momentum, top 3", "xs_momentum", "immediate", True),
    ("Trend filter + vol targeting", "trend_vol", "immediate", True),
    ("Risk parity (inverse vol)", "risk_parity", "immediate", True),
    ("Defensive asset allocation (canary)", "daa", "immediate", True),
    ("Core-satellite, immediate fills", "core_satellite", "immediate", True),
    ("Core-satellite, secretary-rule fills", "core_satellite", "secretary", True),
    ("Core-satellite, TWAP fills", "core_satellite", "twap", True),
    ("Core-satellite without core overlay", "core_xs", "immediate", True),
    ("Static mix (55 Nifty/20 gold/10 S&P/15 cash)", "static_mix", "immediate", True),
    ("Half Nifty + half risk parity", "rp_blend", "immediate", True),
    # crash guard variants (pe/crash.py): the guard is checked every day, the underlying policy on its usual schedule
    ("Buy & hold + crash guard", "buy_hold+guard", "immediate", True),
    ("Core + momentum + crash guard", "core_xs+guard", "immediate", True),
]


@dataclass
class Leg:
    trade: Trade
    mode: str
    n: int
    observed: list = field(default_factory=list)
    done_frac: float = 0.0
    sigma: float = 0.01


@dataclass
class Book:
    lots: list[Lot]
    cash: float
    fy_realised: dict
    fy: int
    taxes_paid: float = 0.0
    costs_paid: float = 0.0
    turnover: float = 0.0
    log: list = field(default_factory=list)
    guard_mem: dict = field(default_factory=dict)   # crash guard: pre-exit weights of a buy & hold book
    journal: list = field(default_factory=list)    # one entry per day the planner ordered trades: what, and why


def _sell(book: Book, settings: Settings, t: Trade, frac: float, price: float, day: date, usd_inr):
    convert = not t.kind.startswith("harvest")  # harvest sell+rebuy stays in USD at the broker
    a = settings.assets[t.symbol]
    value = 0.0
    for lot, q in t.lots:
        q = min(q * frac, lot.qty)
        if q <= 0:
            continue
        lt = is_long_term(lot, a.tax_class, day, settings)
        book.fy_realised[bucket_for(a.tax_class, lt)] += q * (price - lot.price)
        lot.qty -= q
        value += q * price
    book.lots = [l for l in book.lots if l.qty > 1e-9]
    c = leg_cost(settings, a, "sell", value, price, usd_inr) + (fx_cost(settings, value) if a.currency == "USD" and convert else 0)
    book.cash += value - c
    book.costs_paid += c
    book.turnover += value
    return value


def _buy(book: Book, settings: Settings, symbol: str, value: float, price: float, day: date, usd_inr, convert=True):
    value = min(value, max(book.cash, 0.0))
    if value <= 1:
        return 0.0
    a = settings.assets[symbol]
    c = leg_cost(settings, a, "buy", value, price, usd_inr) + (fx_cost(settings, value) if a.currency == "USD" and convert else 0)
    book.lots.append(Lot(symbol, (value - c) / price, day, price))
    book.cash -= value
    book.costs_paid += c
    book.turnover += value
    return value


def _nav(book: Book, px_row: pd.Series) -> float:
    return sum(l.qty * float(px_row[l.symbol]) for l in book.lots) + book.cash


def _check_days(idx: pd.DatetimeIndex, freq: str) -> set:
    if freq == "daily":
        return set(idx)
    s = pd.Series(idx, index=idx)
    if freq == "annual_mar":        # once a year in March, before the Indian tax year closes
        s = s[s.dt.month == 3]
        return set(s.groupby(s.dt.year).first().values)
    key = {"monthly": s.dt.to_period("M"), "weekly": s.dt.to_period("W"), "quarterly": s.dt.to_period("Q")}[freq]
    return set(s.groupby(key).first().values)


def run_variant(name, policy, execution, harvest, init_lots, px, vix, settings: Settings, start, fx=None, opts: dict | None = None):
    """`opts` (optional) changes the timing rules for this variant: check (frequency), gate (name), gate_args, window_days, ltcg_wait_max_days."""
    opts = opts or {}
    if any(k in opts for k in ("check", "window_days", "ltcg_wait_max_days")):
        settings = copy.deepcopy(settings)
        settings.raw["timing"].update({"check_frequency": opts.get("check", settings.timing["check_frequency"]),
                                       "window_days": opts.get("window_days", settings.timing["window_days"]),
                                       "ltcg_wait_max_days": opts.get("ltcg_wait_max_days", settings.timing["ltcg_wait_max_days"])})
    idx = px.index[px.index >= start]
    tm = settings.timing
    checks = _check_days(idx, tm["check_frequency"])
    guarded = policy.endswith("+guard")
    glevel = crash.level_series(px, vix, settings)["level"] if guarded else None     # causal, so reading day t equals running it on data up to t
    acted_level = 0
    book = Book(copy.deepcopy(init_lots), 0.0, {b: 0.0 for b in BUCKETS}, fy_start_year(idx[0].date()))
    pending: list[Leg] = []
    navs = []
    for i, ts in enumerate(idx):
        day = ts.date()
        row = px.loc[ts]
        usd_inr = float(fx.loc[ts]) if fx is not None and ts in fx.index else None
        # FY rollover: pay last FY's tax at the first trading day of the new FY
        fy = fy_start_year(day)
        if fy != book.fy:
            res = compute_tax(book.fy_realised, settings)
            book.cash -= res.tax
            book.taxes_paid += res.tax
            book.log.append((day, "TAX", f"Paid Rs {res.tax:,.0f} for FY{book.fy}-{(book.fy + 1) % 100:02d}"))
            book.fy_realised = {b: 0.0 for b in BUCKETS}
            book.fy_realised["eq_st"] -= res.carry_forward_st_loss
            book.fy_realised["oth_lt"] -= res.carry_forward_lt_loss
            book.fy = fy
        # work pending legs (sells first so buys can be funded)
        for leg in sorted(pending, key=lambda l: l.trade.side != "sell"):
            t = leg.trade
            p = float(row[t.symbol])
            if leg.mode == "secretary":
                leg.observed.append(p)
                funded = t.side == "sell" or not any(l.trade.side == "sell" and l.done_frac < 1 for l in pending)
                dec, _ = secretary_decision(leg.observed, leg.n, t.side)
                if dec == "execute" and funded or len(leg.observed) >= leg.n + 5:
                    frac = 1 - leg.done_frac
                else:
                    continue
            elif leg.mode == "threshold":
                leg.observed.append(p)
                funded = t.side == "sell" or not any(l.trade.side == "sell" and l.done_frac < 1 for l in pending)
                dec, _ = threshold_decision(leg.observed, leg.n, t.side, leg.sigma, opts.get("z", 0.5))
                if dec == "execute" and funded or len(leg.observed) >= leg.n + 5:
                    frac = 1 - leg.done_frac
                else:
                    continue
            elif leg.mode == "twap":
                frac = min(1 / leg.n, 1 - leg.done_frac)
            else:
                frac = 1 - leg.done_frac
            if t.side == "sell":
                if leg.mode == "twap":
                    _sell_twap(book, settings, t, leg, p, day, usd_inr)
                else:
                    _sell(book, settings, t, 1.0, p, day, usd_inr)
            else:
                _buy(book, settings, t.symbol, t.value * frac, p, day, usd_inr, not t.kind.startswith("harvest"))
            leg.done_frac += frac
            book.log.append((day, t.side.upper(), f"{t.symbol} {frac:.0%} of Rs {t.value:,.0f} @ {p:,.2f} [{t.kind}]"))
        pending = [l for l in pending if l.done_frac < 1 - 1e-9]
        # new decisions (only when nothing is still executing)
        # a change in the guard level triggers a check on any day: a crash does not wait for the monthly review
        guard_trigger = guarded and int(glevel.loc[ts]) != acted_level
        if (ts in checks or guard_trigger) and not pending and i < len(idx) - 1:
            if guarded:
                acted_level = int(glevel.loc[ts])
            hist = px.loc[:ts]
            plan = make_plan(ts, book.lots, book.cash, hist, vix.loc[:ts] if vix is not None else None, settings,
                             book.fy_realised, policy, harvest, usd_inr=usd_inr, guard_mem=book.guard_mem)
            if opts.get("gate"):
                kept, gate_why = apply_gate(plan, book, opts["gate"], opts.get("gate_args", {}), settings)
                if gate_why:
                    book.log.append((day, "HOLD", gate_why))
                plan.trades = kept
            for t in plan.trades:
                immediate = execution == "immediate" or t.kind.startswith("harvest") or \
                    (t.kind == "risk_exit" and tm["regime_override_secretary"])
                sig = float(hist[t.symbol].pct_change().iloc[-60:].std()) if t.symbol in hist and t.symbol != "CASH" else 0.01
                pending.append(Leg(t, "immediate" if immediate else execution, 1 if immediate else tm["window_days"], sigma=sig if sig == sig else 0.01))
                book.log.append((day, "PLAN", f"{t.side} {t.symbol} Rs {t.value:,.0f} [{t.kind}] - {t.why[0] if t.why else ''}"))
            if plan.trades:
                reg = plan.target.regime or {}
                tw = plan.target.weights or {}
                book.journal.append({
                    "date": str(day), "nav": round(_nav(book, row)), "regime": reg.get("label", ""),
                    "regime_why": " ".join(reg.get("why", [])), "target": {k: round(v, 4) for k, v in sorted(tw.items(), key=lambda kv: -kv[1]) if v > 0.004},
                    "strategy_why": [w for w in plan.target.why[1:]][:4],
                    "trades": [{"side": t.side, "symbol": t.symbol, "value": round(t.value), "kind": t.kind, "tax": round(t.tax_now), "cost": round(t.cost),
                                "why": t.why[:3]} for t in plan.trades]})
            for b in plan.blocked:
                book.log.append((day, "HOLD", b))
            for d in plan.deferred:
                book.log.append((day, "WAIT", d))
        navs.append(_nav(book, row))
    nav = pd.Series(navs, index=idx, name=name)
    last = px.loc[idx[-1]]
    accrued = compute_tax(book.fy_realised, settings).tax
    unreal = {b: 0.0 for b in BUCKETS}
    for l in book.lots:
        a = settings.assets[l.symbol]
        unreal[bucket_for(a.tax_class, is_long_term(l, a.tax_class, idx[-1].date(), settings))] += l.qty * (float(last[l.symbol]) - l.price)
    liq_tax = compute_tax({b: book.fy_realised[b] + unreal[b] for b in BUCKETS}, settings).tax
    return nav, book, accrued, liq_tax


def _sell_twap(book, settings, t, leg, p, day, usd_inr):
    t2 = copy.copy(t)
    t2.lots = [(l, q * (1 / leg.n)) for l, q in t.lots]
    return _sell(book, settings, t2, 1.0, p, day, usd_inr)


def metrics(nav: pd.Series, book: Book, accrued: float, liq_tax: float, cash_rate: float) -> dict:
    r = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    total = nav.iloc[-1] / nav.iloc[0] - 1
    vol = r.std() * np.sqrt(252)
    dd = (nav / nav.cummax() - 1).min()
    sharpe = ((1 + total) ** (1 / years) - 1 - cash_rate) / vol if vol > 0 else np.nan
    after_keep = nav.iloc[-1] - accrued
    after_liq = nav.iloc[-1] - liq_tax
    return {"start_value": nav.iloc[0], "end_value": nav.iloc[-1], "return": total,
            "after_tax_return_keep": after_keep / nav.iloc[0] - 1,
            "after_tax_return_liquidated": after_liq / nav.iloc[0] - 1,
            "volatility": vol, "max_drawdown": dd, "sharpe": sharpe,
            "taxes_paid": book.taxes_paid, "tax_accrued": accrued, "tax_if_liquidated": liq_tax,
            "costs": book.costs_paid, "turnover_x": book.turnover / nav.iloc[0]}


def run_all(init_lots, px, vix, settings: Settings, start, fx=None, variants=VARIANTS):
    curves, rows, logs = [], [], {}
    for name, policy, ex, hv, *rest in variants:
        nav, book, accrued, liq = run_variant(name, policy, ex, hv, init_lots, px, vix, settings, start, fx, rest[0] if rest else None)
        curves.append(nav)
        m = metrics(nav, book, accrued, liq, settings["cash"]["rate"])
        m["strategy"] = name
        rows.append(m)
        logs[name] = book.log
    return pd.concat(curves, axis=1), pd.DataFrame(rows).set_index("strategy"), logs
