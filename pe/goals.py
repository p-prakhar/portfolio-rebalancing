"""Goal-based withdrawals: "I need Rs X on date D". The engine adapts in three ways.

1. Glide path. A goal's money moves from growth assets to safe assets as the date nears: nothing is forced while
   the goal is more than `glide_start_years` away, the goal is fully backed by safe assets (cash sleeve, debt
   funds, FDs) for the last `fully_safe_years`, and the share in between falls linearly. The safe amount needed
   is the present value of that share of the goal, so safe money also earns its keep until the date.
2. Risk cap. All goals together set a ceiling on the growth share of the portfolio. `make_plan` trims the target
   to that ceiling, so the rotation strategy still chooses what to hold but cannot hold more risk than the goals allow.
3. Withdrawal plan. For a goal date, `withdrawal_plan` picks which units to sell to raise exactly the net amount,
   cheapest first after tax and trading cost: idle cash, then losses, long-term gains inside the yearly exemption,
   long-term gains, and short-term gains last. FIFO is respected within each holding when `lot_method: fifo`.

Goals live in config/goals.yaml (git-ignored). All rates are assumptions in settings.yaml under `goals:`; the
projections are planning aids, not forecasts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .config import ROOT, Lot, Settings
from .costs import leg_cost
from .tax import BUCKETS, bucket_for, compute_tax, fy_start_year, is_long_term, lt_date, marginal_tax

GOALS_PATH = ROOT / "config" / "goals.yaml"


@dataclass
class Goal:
    name: str
    amount_inr: float
    due: date
    priority: str = "must"       # must | nice: a "nice" goal starts de-risking later (it can slip without harm)
    note: str = ""


def _to_date(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x))


def load_goals(path: Path = GOALS_PATH) -> list[Goal]:
    if not Path(path).exists():
        return []
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return [Goal(name=str(g["name"]), amount_inr=float(g["amount_inr"]), due=_to_date(g["due"]),
                 priority=g.get("priority", "must"), note=g.get("note", ""))
            for g in raw.get("goals", [])]


def save_goals(goals: list[Goal], path: Path = GOALS_PATH) -> None:
    Path(path).write_text(
        "# Money you need on a date (git-ignored). Edit by hand or via `goal` in the shell.\n"
        + yaml.safe_dump({"goals": [{"name": g.name, "amount_inr": g.amount_inr, "due": g.due.isoformat(),
                                     "priority": g.priority, "note": g.note} for g in goals]}, sort_keys=False))


def years_left(due: date, today: date) -> float:
    return max(0.0, (due - today).days / 365.25)


def safe_share(years: float, priority: str, cfg: dict) -> float:
    """Share of the goal that should sit in safe assets with `years` to go (0 = all growth, 1 = all safe)."""
    start = cfg["glide_start_years_nice"] if priority == "nice" else cfg["glide_start_years"]
    end = cfg["fully_safe_years"]
    if years >= start:
        return 0.0
    if years <= end:
        return 1.0
    return (start - years) / (start - end)


def is_goal_safe(symbol: str, settings: Settings) -> bool:
    a = settings.assets.get(symbol)
    return bool(a) and (a.sleeve in settings["goals"]["safe_sleeves"] or a.tax_class == "in_debt")


def _growth_factor(years: float, priority: str, cfg: dict) -> float:
    """Growth of one rupee held until the date while following the glide path (yearly steps)."""
    g, t = 1.0, years
    while t > 1e-9:
        step = min(1.0, t)
        s = safe_share(t, priority, cfg)
        g *= (1 + (1 - s) * cfg["risky_return"] + s * cfg["safe_return"]) ** step
        t -= step
    return g


@dataclass
class GoalStatus:
    goal: Goal
    years: float
    safe_share: float
    safe_needed: float        # rupees of safe assets this goal needs today
    claim_today: float        # rupees of today's portfolio this goal needs to reach its amount on the glide path
    funded_today: float       # part of the claim the portfolio can cover (earliest goal first)
    shortfall_at_due: float   # rupees missing on the date if nothing is added
    monthly_needed: float     # monthly saving that closes the shortfall
    stress_cover: float       # share of the claim still covered after a stress fall in growth assets
    overdue: bool = False


@dataclass
class GoalPlan:
    statuses: list[GoalStatus]
    safe_needed_total: float
    safe_outside: float
    safe_in_portfolio_needed: float
    risk_cap: float                 # highest growth share of the tradable portfolio the goals allow (1 = no limit)
    notes: list[str] = field(default_factory=list)


def assess(goals: list[Goal], today: date, nav: float, safe_value: float, outside_safe: float,
           settings: Settings) -> GoalPlan:
    """nav = tradable portfolio incl. cash; safe_value = the safe part of it; outside_safe = FDs/debt funds held elsewhere."""
    cfg = settings["goals"]
    buf = 1 + cfg["buffer"]
    live = sorted([g for g in goals if g.due >= today], key=lambda g: g.due)
    sts, notes = [], []
    total_assets = nav + outside_safe
    risky_w = max(0.0, 1 - (safe_value + outside_safe) / total_assets) if total_assets > 0 else 0.0
    pool, pool_stress = total_assets, total_assets * (1 - risky_w * cfg["stress_drop"])
    safe_total = 0.0
    for g in live:
        y = years_left(g.due, today)
        s = safe_share(y, g.priority, cfg)
        need_safe = s * g.amount_inr * buf / (1 + cfg["safe_return"]) ** y
        gf = _growth_factor(y, g.priority, cfg)
        claim = g.amount_inr * buf / gf
        got, got_s = min(claim, pool), min(claim, pool_stress)
        pool, pool_stress = pool - got, pool_stress - got_s
        short = max(0.0, claim - got) * gf
        monthly = 0.0
        if short > 0 and y > 0:
            n = max(1, round(y * 12))
            i = ((gf) ** (1 / n)) - 1 if gf > 1 else 0.0
            monthly = short / n if i <= 0 else short * i / ((1 + i) ** n - 1)
        sts.append(GoalStatus(g, y, s, need_safe, claim, got, short, monthly, got_s / claim if claim else 1.0))
        safe_total += need_safe
    overdue = [g for g in goals if g.due < today]
    for g in overdue:
        notes.append(f"Goal '{g.name}' was due {g.due}. Remove it from config/goals.yaml once it is paid.")
    in_port = max(0.0, safe_total - outside_safe)
    cap = 1.0 if nav <= 0 else max(0.0, 1 - in_port / nav)
    for st in sts:
        g = st.goal
        line = (f"Goal '{g.name}': Rs {g.amount_inr:,.0f} on {g.due} ({st.years:.1f} years). "
                f"Safe share now {st.safe_share:.0%} (about Rs {st.safe_needed:,.0f} in cash or debt).")
        if st.shortfall_at_due > 0:
            line += (f" At the planning returns the portfolio falls Rs {st.shortfall_at_due:,.0f} short on the date; "
                     f"saving about Rs {st.monthly_needed:,.0f} a month would close it, or move the date or the amount.")
        elif st.stress_cover < 0.999:
            line += (f" On track, but after a {cfg['stress_drop']:.0%} fall in growth assets only {st.stress_cover:.0%} "
                     f"of it would still be covered.")
        else:
            line += f" On track, and still covered after a {cfg['stress_drop']:.0%} fall in growth assets."
        notes.append(line)
    if sts and cap < 1:
        notes.append(f"Goals cap growth assets at {cap:.0%} of the tradable portfolio (safe money for goals: "
                     f"Rs {safe_total:,.0f}, of which Rs {min(outside_safe, safe_total):,.0f} is already in FDs and debt funds).")
    if len(sts) > 1:
        notes.append("Goals are funded earliest first from one shared portfolio. Money meant for something else "
                     "(retirement, emergency fund) is not set aside here, so lower the amounts if it overlaps.")
    return GoalPlan(sts, safe_total, outside_safe, in_port, cap, notes)


def outside_safe_value(today: date) -> float:
    """Safe money held outside the tradable portfolio: FDs and liquid debt/cash records."""
    total = 0.0
    try:
        from . import fd as F
        total += sum(f.value_on(today) for f in F.load())
    except Exception:
        pass
    try:
        from .profile import load_other
        total += sum(o.value_inr for o in load_other() if o.liquid and o.kind in ("cash_savings", "mutual_fund_debt", "bonds"))
    except Exception:
        pass
    return total


def cap_target(target, held: dict[str, float], cash_inr: float, nav: float, plan: GoalPlan, settings: Settings) -> bool:
    """Trim the policy's target so growth assets stay under the goal cap. Excess goes to the CASH sleeve."""
    weights = dict(target.weights) if target.weights is not None else {s: v / nav for s, v in held.items()}
    if target.weights is None and cash_inr > 0:
        weights["CASH"] = weights.get("CASH", 0.0) + cash_inr / nav
    risky = sum(w for s, w in weights.items() if not is_goal_safe(s, settings))
    if risky <= plan.risk_cap + 1e-9:
        return False
    k = plan.risk_cap / risky if risky > 0 else 0.0
    out = {s: (w if is_goal_safe(s, settings) else w * k) for s, w in weights.items()}
    out["CASH"] = out.get("CASH", 0.0) + (risky - plan.risk_cap)
    target.weights = out
    target.risk_off = True
    soonest = min(plan.statuses, key=lambda s: s.years).goal
    target.risk_reason = f"your goal '{soonest.name}' due {soonest.due} needs safe money"
    target.why.append(f"Goal glide path: growth assets are capped at {plan.risk_cap:.0%} (policy wanted {risky:.0%}) so "
                      f"Rs {plan.safe_in_portfolio_needed:,.0f} of safe assets backs the goals due soon. The cap tightens each month as the dates near.")
    return True


# ---------------------------------------------------------------------------------------------- withdrawal planner

@dataclass
class Sale:
    lot: Lot
    qty: float
    price: float
    value: float
    gain: float
    bucket: str
    long_term: bool


@dataclass
class Withdrawal:
    amount: float
    sale_date: date
    from_cash: float
    sales: list[Sale]
    gross: float
    cost: float
    tax: float
    net: float                  # cash + sale proceeds - cost - extra tax: what actually lands
    shortfall: float
    naive_burden: float         # tax + cost of selling a little of everything instead
    notes: list[str] = field(default_factory=list)

    @property
    def burden(self) -> float:
        return self.tax + self.cost


def _fy_realised(realised: dict | None, today: date, sale_date: date, settings: Settings) -> dict:
    m = settings.tax["fy_start_month"]
    if realised and fy_start_year(sale_date, m) == fy_start_year(today, m):
        return {b: float(realised.get(b, 0.0)) for b in BUCKETS}
    return {b: 0.0 for b in BUCKETS}


def _evaluate(pieces: list[tuple[Lot, float]], px_now, sale_date: date, base: dict, settings: Settings, usd_inr):
    sales, gains, by_sym = [], {b: 0.0 for b in BUCKETS}, {}
    for lot, q in pieces:
        a = settings.assets[lot.symbol]
        p = float(px_now[lot.symbol])
        lt = is_long_term(lot, a.tax_class, sale_date, settings)
        g = q * (p - lot.price)
        b = bucket_for(a.tax_class, lt)
        gains[b] += g
        by_sym[lot.symbol] = by_sym.get(lot.symbol, 0.0) + q * p
        sales.append(Sale(lot, q, p, q * p, g, b, lt))
    gross = sum(by_sym.values())
    cost = sum(leg_cost(settings, settings.assets[s], "sell", v, float(px_now[s]), usd_inr) for s, v in by_sym.items())
    tax = marginal_tax(base, gains, settings) if pieces else 0.0
    return sales, gross, cost, tax


def withdrawal_plan(amount: float, lots: list[Lot], cash_inr: float, px_now, today: date, settings: Settings,
                    sale_date: date | None = None, realised: dict | None = None, usd_inr: float | None = None,
                    _allow_wait: bool = True) -> Withdrawal:
    """Cheapest set of sales that lands `amount` rupees after tax and trading cost. Prices are today's, held flat."""
    import pandas as pd
    sale_date = sale_date or today
    base = _fy_realised(realised, today, sale_date, settings)
    from_cash = min(max(cash_inr, 0.0), amount)
    need = amount - from_cash
    fifo = settings.tax.get("lot_method", "fifo") == "fifo"
    usable = [l for l in lots if l.symbol in settings.assets and pd.notna(px_now.get(l.symbol)) and l.qty > 1e-9]
    by_sym: dict[str, list[Lot]] = {}
    for l in sorted(usable, key=lambda x: x.buy_date):
        by_sym.setdefault(l.symbol, []).append(l)

    def net_of(ps):
        _, gross, cost, tax = _evaluate(ps, px_now, sale_date, base, settings, usd_inr)
        return gross - cost - tax

    def run(seed_losses: bool):
        left = {id(l): l.qty for l in usable}
        picked: list[tuple[Lot, float]] = []

        def candidates():
            for ls in by_sym.values():
                avail = [l for l in ls if left[id(l)] > 1e-9]
                yield from (avail[:1] if fifo else avail)

        def take(l, q):
            picked.append((l, q))
            left[id(l)] -= q

        def is_loss(l):
            return px_now[l.symbol] < l.price

        # A loss only pays once there are gains to offset, so one-lot-at-a-time greedy cannot see it: try both orders.
        while seed_losses and net_of(picked) < need - 0.5:
            nxt = [l for l in candidates() if is_loss(l)]
            if not nxt:
                break
            l = nxt[0]
            take(l, left[id(l)])
        while need > 0.5 and net_of(picked) < need - 0.5:
            best, best_rate = None, None
            _, g0, c0, t0 = _evaluate(picked, px_now, sale_date, base, settings, usd_inr)
            for l in candidates():
                _, g1, c1, t1 = _evaluate(picked + [(l, left[id(l)])], px_now, sale_date, base, settings, usd_inr)
                dv = g1 - g0
                rate = ((t1 - t0) + (c1 - c0)) / dv if dv > 0 else 1.0
                if best_rate is None or rate < best_rate - 1e-12:
                    best, best_rate = l, rate
            if best is None:
                break
            if net_of(picked + [(best, left[id(best)])]) <= need:
                q = left[id(best)]
            else:
                lo, hi = 0.0, left[id(best)]
                for _ in range(50):
                    mid = (lo + hi) / 2
                    if net_of(picked + [(best, mid)]) < need:
                        lo = mid
                    else:
                        hi = mid
                q = hi
            take(best, q)
        return picked

    def burden(ps):
        _, _, cost, tax = _evaluate(ps, px_now, sale_date, base, settings, usd_inr)
        return cost + tax

    options = [run(False), run(True)]
    ok = [p for p in options if net_of(p) >= need - 0.5] or options
    picked = min(ok, key=burden)
    sales, gross, cost, tax = _evaluate(picked, px_now, sale_date, base, settings, usd_inr)
    net = from_cash + gross - cost - tax
    # Baseline: sell the same fraction of every holding (oldest units first within each).
    naive = _naive_burden(need, by_sym, px_now, sale_date, base, settings, usd_inr)
    w = Withdrawal(amount, sale_date, from_cash, sales, gross, cost, tax, net, max(0.0, amount - net), naive)
    _add_notes(w, lots, today, settings, realised, px_now, usd_inr, _allow_wait)
    return w


def _naive_burden(need: float, by_sym, px_now, sale_date, base, settings, usd_inr) -> float:
    if need <= 0:
        return 0.0

    def pieces(f):
        out = []
        for ls in by_sym.values():
            todo = f * sum(l.qty for l in ls)
            for l in ls:
                q = min(l.qty, todo)
                if q > 1e-9:
                    out.append((l, q))
                todo -= q
        return out

    def net(f):
        _, gross, cost, tax = _evaluate(pieces(f), px_now, sale_date, base, settings, usd_inr)
        return gross - cost - tax

    if net(1.0) < need:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if net(mid) < need:
            lo = mid
        else:
            hi = mid
    _, gross, cost, tax = _evaluate(pieces(hi), px_now, sale_date, base, settings, usd_inr)
    return cost + tax


def _add_notes(w: Withdrawal, lots, today: date, settings: Settings, realised, px_now, usd_inr, allow_wait: bool) -> None:
    t = settings.tax
    if w.shortfall > 1:
        w.notes.append(f"The portfolio cannot raise this: Rs {w.shortfall:,.0f} is still missing after selling everything sellable.")
    if w.naive_burden - w.burden > 100:
        w.notes.append(f"Choosing units this way costs Rs {w.burden:,.0f} in tax and charges, against about Rs {w.naive_burden:,.0f} "
                       f"if you sold a slice of every holding.")
    if settings.tax.get("lot_method", "fifo") == "fifo" and w.sales:
        w.notes.append("Units are taken oldest first within each holding, as depositories and the tax return apply them. "
                       "Sell the cheapest holding first and keep each sale a single order.")
    st = [s for s in w.sales if not s.long_term and s.gain > 0]
    if allow_wait and st:
        soon = []
        for s in st:
            a = settings.assets[s.lot.symbol]
            d = lt_date(s.lot, a.tax_class, settings)
            if d and 0 < (d - w.sale_date).days <= 90:
                soon.append(d)
        if soon:
            later = max(soon)
            w2 = withdrawal_plan(w.amount, lots, w.from_cash, px_now, today, settings, later, realised, usd_inr, _allow_wait=False)
            if w.burden - w2.burden > 500 and w2.shortfall < 1:
                w.notes.append(f"If the date can move to {later}, short-term lots turn long term and the tax and charges fall by about "
                               f"Rs {w.burden - w2.burden:,.0f} (at today's prices).")
    eq_lt = sum(s.gain for s in w.sales if s.bucket == "eq_lt" and s.gain > 0)
    if eq_lt > t["ltcg_exemption"] and (w.sale_date - today).days >= 30:
        w.notes.append(f"Long-term equity gains here are Rs {eq_lt:,.0f}, above the Rs {t['ltcg_exemption']:,.0f} yearly exemption. "
                       f"If you can sell part before 31 March and the rest from 1 April, the exemption applies twice.")
    if any(s.lot.symbol in settings.assets and settings.assets[s.lot.symbol].sell_only for s in w.sales):
        w.notes.append("Some units sit in a restricted stock-plan account, which can only sell. They are valid sources here.")
    if any(settings.assets[s.lot.symbol].currency == "USD" for s in w.sales):
        w.notes.append("US sales need repatriation to India: allow a few days for the transfer and the FX spread, which is not counted above.")


# ---------------------------------------------------------------------------------------------- text

def goals_markdown(gp: GoalPlan) -> str:
    out = ["## Goals\n"]
    for st in gp.statuses:
        g = st.goal
        out.append(f"- **{g.name}**: Rs {g.amount_inr:,.0f} on {g.due} ({st.years:.1f} years). Safe share {st.safe_share:.0%}, "
                   f"safe money needed Rs {st.safe_needed:,.0f}. "
                   + ("Short by Rs {:,.0f} on the date; about Rs {:,.0f} a month closes it.".format(st.shortfall_at_due, st.monthly_needed)
                      if st.shortfall_at_due > 0 else f"Funded; stress cover {st.stress_cover:.0%}."))
    out.append(f"\nGrowth assets are capped at {gp.risk_cap:.0%} of the tradable portfolio by these goals.\n" if gp.risk_cap < 1
               else "\nThese goals do not limit growth assets yet.\n")
    return "\n".join(out)


def withdrawal_markdown(w: Withdrawal, name: str = "") -> str:
    out = [f"## Raising Rs {w.amount:,.0f}" + (f" for {name}" if name else "") + f" on {w.sale_date}\n"]
    if w.from_cash:
        out.append(f"- Start with Rs {w.from_cash:,.0f} of idle cash (no tax).")
    for s in w.sales:
        out.append(f"- SELL {s.qty:,.2f} {s.lot.symbol} (bought {s.lot.buy_date}) for Rs {s.value:,.0f}: gain Rs {s.gain:,.0f}, "
                   f"{'long' if s.long_term else 'short'} term.")
    out.append(f"\nSale proceeds Rs {w.gross:,.0f}, charges Rs {w.cost:,.0f}, extra tax Rs {w.tax:,.0f}. "
               f"Net to you Rs {w.net:,.0f}.\n")
    out += [f"- {n}" for n in w.notes]
    return "\n".join(out) + "\n"
