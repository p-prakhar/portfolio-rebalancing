"""Build reports/index.html: one self-contained page that answers "is it worth rebalancing, and how?".

Everything (data, styles, scripts) is inlined, so the page works offline and can be opened by double-click.
The only network use is optional: the "live chart" buttons load a TradingView embed when clicked.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import VARIANTS
from .config import ROOT, Settings
from .engine import Plan
from .profile import KINDS, OtherAsset, Profile, guardrails

POLICY_VARIANT = {
    "buy_hold": VARIANTS[1][0], "custom": VARIANTS[2][0], "dual_momentum": VARIANTS[3][0], "xs_momentum": VARIANTS[4][0],
    "trend_vol": VARIANTS[5][0], "risk_parity": VARIANTS[6][0], "daa": VARIANTS[7][0], "core_satellite": VARIANTS[8][0],
    "core_xs": VARIANTS[11][0], "static_mix": VARIANTS[12][0], "rp_blend": VARIANTS[13][0],
}
EXEC_RE = re.compile(r"^(\S+) (\d+)% of Rs ([\d,]+) @ ([\d,.]+) \[(\w+)\]")
PLAN_RE = re.compile(r"^(buy|sell) (\S+) Rs ([\d,]+) \[(\w+)\] - (.*)$")


def _tv_symbol(settings: Settings, sym: str) -> str | None:
    a = settings.assets.get(sym)
    if sym == "CASH" or a is None:
        return None
    if a.currency == "USD":
        return {"SPY": "AMEX:SPY", "QQQ": "NASDAQ:QQQ", "EFA": "AMEX:EFA", "EEM": "AMEX:EEM", "GLD": "AMEX:GLD", "TLT": "NASDAQ:TLT"}.get(sym, sym)
    return f"NSE:{sym}"


def _events(logs: list, settings: Settings) -> list[dict]:
    ev, why = [], {}
    for d, kind, msg in logs:
        if kind == "PLAN":
            m = PLAN_RE.match(msg)
            if m:
                why[(m.group(2), m.group(1))] = m.group(5)
        elif kind in ("BUY", "SELL"):
            m = EXEC_RE.match(msg)
            if m:
                sym = m.group(1)
                ev.append({"date": str(d), "type": kind.lower(), "symbol": sym, "pct": int(m.group(2)), "value": float(m.group(3).replace(",", "")),
                           "price": float(m.group(4).replace(",", "")), "kind": m.group(5),
                           "why": why.get((sym, kind.lower()), ""), "tv": _tv_symbol(settings, sym)})
        elif kind == "TAX":
            ev.append({"date": str(d), "type": "tax", "symbol": "", "value": 0, "price": 0, "kind": "tax", "why": msg, "tv": None})
    return ev


def _verdict(plan: Plan, settings: Settings, bt_table: pd.DataFrame | None, validation: dict | None) -> dict:
    pol = settings.strategy["policy"]
    actionable = [t for t in plan.trades if not t.kind.startswith("harvest")]
    cost = sum(t.cost for t in plan.trades)
    tax = max(0.0, plan.tax_after - plan.tax_before)
    friction = (cost + tax) / plan.nav if plan.nav else 0
    variant = POLICY_VARIANT.get(pol)
    ev_lines, delta = [], None
    if bt_table is not None and variant in bt_table.index:
        bh = bt_table.iloc[0]
        me = bt_table.loc[variant]
        delta = me["after_tax_return_liquidated"] - bh["after_tax_return_liquidated"]
        ev_lines.append(f"Last 12 months: this strategy returned {me['after_tax_return_liquidated']:+.1%} after tax vs {bh['after_tax_return_liquidated']:+.1%} for doing nothing "
                        f"({delta * 100:+.1f} points). One year is one sample.")
    label = None
    if validation and variant in validation.get("windows", {}):
        from .validate import verdicts
        label = verdicts(validation, VARIANTS[0][0]).get(variant, "baseline")
        w = validation["windows"][variant]
        if w.get("win_rate") is not None and variant != VARIANTS[0][0]:
            ev_lines.append(f"Over {validation['years']:.0f} years in {w['windows']} rolling {validation['window_years']}-year windows it beat buy & hold in {w['win_rate']:.0%} of them "
                            f"(median {w['median_excess'] * 100:+.1f} points a year, worst {w['worst_excess'] * 100:+.1f}). Verdict: {label}.")
    risk_exit = [t for t in actionable if t.kind == "risk_exit"]
    if not actionable:
        call, head = "HOLD", "Not worth rebalancing right now."
        why = ["The model already matches your portfolio, or every possible move costs more in tax and fees than it is expected to earn."]
        if plan.blocked or plan.deferred:
            why.append("Moves were considered and held back: " + "; ".join((plan.blocked + plan.deferred)[:2]))
    elif risk_exit and friction <= 0.03:
        call, head = "REBALANCE", "Yes, a defensive rebalance looks worth it."
        why = [f"The trend signals say risk is rising ({plan.target.risk_reason or 'market below trend'}), and the move costs {friction:.2%} of your portfolio in fees and tax.",
               "Exits that cut risk skip the wait-for-a-better-price rule, because the point is to be out before a fall."]
    elif delta is not None and delta >= 0.02 and friction <= delta:
        call, head = "REBALANCE", "Yes, the expected gain is larger than the cost."
        why = [f"Fees and tax come to {friction:.2%} of your portfolio; the strategy's recent edge was {delta * 100:+.1f} points."]
    else:
        call, head = "HOLD", "Not worth it: the cost is as large as the expected gain."
        why = [f"Fees and tax would be {friction:.2%} of your portfolio" + (f" against an edge of {delta * 100:+.1f} points last year." if delta is not None else ".")]
    if label in ("no reliable edge",) and call == "REBALANCE" and not risk_exit:
        call, head = "HOLD", "Not worth it: this strategy has not shown a dependable edge over 10 years."
    return {"call": call, "headline": head, "reasons": why + ev_lines, "cost": cost, "tax": tax, "friction_pct": friction,
            "delta": delta, "policy": pol, "label": label, "n_trades": len(actionable)}


def _blotter(plan: Plan, settings: Settings, px: pd.DataFrame) -> list[dict]:
    """One row per asset held or targeted: exact shares, weights, drift, cost model and tax estimate (the UI applies the theta rule)."""
    from .costs import leg_cost
    from .tax import effective_rate
    pos = plan.positions
    cur_val = pos.groupby("symbol").value.sum().to_dict() if not pos.empty else {}
    cur_qty = pos.groupby("symbol").qty.sum().to_dict() if not pos.empty else {}
    nav = plan.nav
    cash_now = nav - sum(cur_val.values())
    tw = plan.target.weights
    tgt_val = dict(cur_val) if tw is None else {k: v * nav for k, v in tw.items()}
    if cash_now > 1:
        cur_val["CASH"] = cur_val.get("CASH", 0) + cash_now
        if tw is None:
            tgt_val["CASH"] = cur_val["CASH"]
    # Same-index twins (e.g. SETFNIF50 for NIFTYBEES) share one target weight; split it across the twins you hold, pro rata to value.
    groups: dict[str, list[str]] = {}
    for sym in set(cur_val) | set(tgt_val):
        if sym in settings.assets:
            groups.setdefault(settings.assets[sym].equivalent_of or sym, []).append(sym)
    for prim, members in groups.items():
        if len(members) < 2:
            continue
        total = sum(tgt_val.get(m, 0.0) for m in members)
        held = [m for m in members if cur_val.get(m, 0) > 0] or [prim]
        base = sum(cur_val.get(m, 0.0) for m in held) or 1.0
        for m in members:
            tgt_val[m] = total * cur_val.get(m, 0.0) / base if m in held and base else 0.0
        if held == [prim] and not any(cur_val.get(m, 0) > 0 for m in held):
            tgt_val[prim] = total
    engine = {}
    for t in plan.trades:
        if not t.kind.startswith("harvest"):
            engine[t.symbol] = t.side.upper()
    rows = []
    for sym in sorted(set(cur_val) | set(tgt_val), key=lambda k: -(max(cur_val.get(k, 0), tgt_val.get(k, 0)))):
        if sym not in px or sym not in settings.assets:
            continue
        a = settings.assets[sym]
        price = float(px[sym].dropna().iloc[-1])
        v0 = max(nav * 0.01, 10_000)
        try:
            c1 = leg_cost(settings, a, "buy", v0, price, plan.usd_inr)
            c2 = leg_cost(settings, a, "buy", 2 * v0, price, plan.usd_inr)
        except Exception:
            c1 = c2 = 0.0
        pct = max(0.0, (c2 - c1) / v0)
        fixed = max(0.0, c1 - pct * v0)
        taxr = 0.0
        if not pos.empty and sym in set(pos.symbol):
            sub = pos[pos.symbol == sym]
            gains = sum(max(float(r.gain), 0.0) * effective_rate(r.bucket, settings) for _, r in sub.iterrows())
            taxr = gains / max(float(sub.value.sum()), 1.0)
        rows.append({"symbol": sym, "name": a.name, "price": round(price, 4), "cur_value": round(cur_val.get(sym, 0.0)), "tgt_value": round(tgt_val.get(sym, 0.0)),
                     "cur_shares": round(cur_qty.get(sym, 0.0), 4) if sym != "CASH" else round(cur_val.get(sym, 0.0) / price, 4),
                     "cost_fixed": round(fixed, 2), "cost_pct": round(pct, 6), "tax_rate_on_sale": round(taxr, 5), "engine": engine.get(sym, ""),
                     "lt_note": "" if pos.empty or sym not in set(pos.symbol) else ("all long term" if bool(pos[pos.symbol == sym].long_term.all()) else "has short-term lots")})
    return rows


def _momentum_matrix(plan: Plan, settings: Settings, px: pd.DataFrame) -> list[dict]:
    """12-1 month return R, annualised volatility over the same window, M = R / vol and its cross-sectional z-score."""
    lb = max(settings.strategy["xs"]["lookbacks"])
    skip = settings.strategy["xs"]["skip_recent"]
    tiers = {"NIFTYBEES": "Large cap", "SETFNIF50": "Large cap", "JUNIORBEES": "Next 50", "MID150BEES": "Mid cap", "LOWVOLIETF": "Factor", "MOM30IETF": "Factor"}
    syms = [s for s in settings.rotatable() if s in px] + [s for s in plan.positions.symbol.unique() if s in px and s not in settings.rotatable()] if not plan.positions.empty else settings.rotatable()
    rows = []
    for sym in dict.fromkeys(syms):
        s = px[sym].dropna()
        if sym == "CASH" or len(s) < lb + skip + 5:
            continue
        win = s.iloc[-(lb + 1):-skip]
        r = float(win.iloc[-1] / win.iloc[0] - 1)
        rets = win.pct_change().dropna()
        sig = float(np.sqrt(252 / (len(rets) - 1) * ((rets - rets.mean()) ** 2).sum()))
        a = settings.assets[sym]
        rows.append({"symbol": sym, "name": a.name, "region": "US" if a.currency == "USD" else "India", "sleeve": a.sleeve, "tier": tiers.get(sym, ""),
                     "R": r, "sigma": sig, "M": r / sig if sig > 0 else None, "held": sym in set(plan.positions.symbol) if not plan.positions.empty else False,
                     "in_target": bool(plan.target.weights and plan.target.weights.get(sym, 0) > 0.005)})
    ms = np.array([x["M"] for x in rows if x["M"] is not None])
    mu, sd = (ms.mean(), ms.std(ddof=0)) if len(ms) else (0, 1)
    for x in rows:
        x["z"] = None if x["M"] is None or sd == 0 else float((x["M"] - mu) / sd)
    rows.sort(key=lambda x: -(x["M"] if x["M"] is not None else -9))
    for i, x in enumerate(rows, 1):
        x["rank"] = i
    return rows


def _regime_filter(plan: Plan, settings: Settings, px: pd.DataFrame) -> dict:
    sym = settings.strategy["dual_momentum"]["equity"]
    s = px[sym].dropna()
    sma = float(s.iloc[-200:].mean())
    p = float(s.iloc[-1])
    eng = plan.target.regime or {}
    cash_w = None if plan.target.weights is None else float(plan.target.weights.get("CASH", 0.0))
    tail = s.iloc[-260:]
    sma_s = s.rolling(200).mean().iloc[-260:]
    series = {"dates": [str(d.date()) for d in tail.index], "price": [round(float(v), 2) for v in tail],
              "sma": [None if pd.isna(v) else round(float(v), 2) for v in sma_s]}
    return {"benchmark": sym, "series": series, "price": round(p, 2), "sma200": round(sma, 2), "gap": p / sma - 1, "state": "RISK_ON" if p > sma else "CASH_PRESERVATION",
            "engine_label": (eng.get("label") or "").replace("_", "-"), "vix": eng.get("vix"), "target_cash_weight": cash_w}


def _platform(settings: Settings, sym: str) -> str:
    a = settings.assets.get(sym)
    if a and a.currency == "USD":
        return "E*TRADE (employer shares) or your US broker"
    return "Kite (or your Indian broker)"


def _steps(plan: Plan, settings: Settings, timing: list[str]) -> list[dict]:
    steps = [{"title": "Check your lots are current", "detail": "Open the shell (`python main.py shell`) and re-import your latest Kite tradebook / E*TRADE file if you traded since the last import. Stale lots give wrong tax numbers.", "cmd": "python main.py shell"}]
    acts = [t for t in plan.trades if not t.kind.startswith("harvest")]
    sells = [t for t in acts if t.side == "sell"]
    buys = [t for t in acts if t.side == "buy"]
    if timing:
        steps.append({"title": "Check the timing rule", "detail": "\n".join(timing).replace("**", "")})
    for t in sells:
        lots = "; ".join(f"{q:,.2f} units of the {l.buy_date} lot" for l, q in t.lots) or "see report"
        tax = f" Tax on this sale: about Rs {t.tax_now:,.0f}." if t.tax_now else " No tax is due on this sale."
        steps.append({"title": f"Sell {t.qty:,.2f} {t.symbol} (about Rs {t.value:,.0f})",
                      "detail": f"In {_platform(settings, t.symbol)}: Orders > Sell {t.symbol}, quantity {t.qty:,.0f} (round down), type Limit at the last price {t.price:,.2f}"
                                f" or a touch below, product CNC (delivery). Lots used: {lots}.{tax} Costs about Rs {t.cost:,.0f}.",
                      "symbol": t.symbol, "why": t.why[:3]})
    if sells and buys:
        steps.append({"title": "Wait for the sale to settle", "detail": "NSE sales settle the next trading day (T+1); US sales settle T+1 as well. Proceeds show as cash in the broker app."})
    for t in buys:
        if t.symbol == "CASH":
            steps.append({"title": f"Park about Rs {t.value:,.0f} in the cash sleeve", "detail": "Use a liquid or arbitrage fund (Coin > Mutual funds), or leave it in your bank sweep. The model uses an arbitrage fund as proxy.", "symbol": "CASH"})
            continue
        usd = settings.assets[t.symbol].currency == "USD"
        extra = " Buying US assets from India goes through the RBI LRS route: your bank will collect TCS on remittances above the yearly limit, which you can claim as a credit when filing." if usd else ""
        steps.append({"title": f"Buy about {t.qty:,.0f} {t.symbol} (Rs {t.value:,.0f})",
                      "detail": f"In {_platform(settings, t.symbol)}: Buy {t.symbol}, Limit at {t.price:,.2f}, product CNC. Costs about Rs {t.cost:,.0f}.{extra}",
                      "symbol": t.symbol, "why": t.why[:3]})
    steps.append({"title": "Record what you actually did", "detail": "Re-import your tradebook in the shell (or edit config/holdings.yaml with your real fills), then run `python main.py reset-window` to close the execution window.", "cmd": "python main.py reset-window"})
    return steps


def _factors(plan: Plan, settings: Settings, profile: Profile | None, validation: dict | None, verdict: dict) -> list[dict]:
    pos = plan.positions
    f = []
    if not pos.empty:
        lt = pos[pos.long_term].value.sum()
        st = pos[~pos.long_term].value.sum()
        soon = pos[(~pos.long_term) & (pos.days_to_lt > 0) & (pos.days_to_lt <= 90)]
        f.append({"name": "Tax", "status": "warn" if verdict["tax"] > 0 else "ok",
                  "line": f"Selling everything today would cost Rs {max(0, plan.tax_after - plan.tax_before):,.0f}" if plan.trades else "No tax event in this plan",
                  "detail": f"Long term holdings Rs {lt:,.0f}, short term Rs {st:,.0f}. Equity LTCG {settings.tax['equity_ltcg_rate']:.1%} above Rs {settings.tax['ltcg_exemption']:,.0f}/yr, STCG {settings.tax['equity_stcg_rate']:.0%}. "
                            + (f"{len(soon)} lot(s) turn long term within 90 days, so waiting can save tax." if len(soon) else "")})
    f.append({"name": "Costs", "status": "ok" if verdict["friction_pct"] < 0.01 else "warn", "line": f"Rs {verdict['cost']:,.0f} in fees ({verdict['cost'] / max(plan.nav, 1):.2%})",
              "detail": "Brokerage, STT, exchange and SEBI fees, GST, stamp duty, DP charge and bid-ask spread; IBKR commission and currency conversion for US assets."})
    reg = plan.target.regime or {}
    if reg:
        f.append({"name": "Market regime", "status": {"calm": "ok", "caution": "warn", "risk_off": "bad"}.get(reg["label"], "info"),
                  "line": reg["label"].replace("_", "-"), "detail": " ".join(reg["why"])})
    dm = plan.target.dual
    if dm:
        f.append({"name": "Dual momentum", "status": "ok" if dm["choice"] in (None, settings.strategy["dual_momentum"]["equity"]) else "bad",
                  "line": f"prefers {dm['choice']}", "detail": " ".join(dm["why"])})
    if plan.target.scores is not None and len(plan.target.scores):
        top = plan.target.scores.head(3)
        f.append({"name": "Cross-sectional momentum", "status": "info", "line": "top: " + ", ".join(top.index),
                  "detail": "Ranks the India, US and gold universe by 6- and 12-month return per unit of volatility (skipping the last month), and only holds assets that also beat cash."})
    if plan.ta:
        down = [s for s, r in plan.ta.items() if r.score < -1]
        f.append({"name": "Trend of what you hold", "status": "bad" if down else "ok", "line": f"{len(down)} of {len(plan.ta)} in downtrend",
                  "detail": "; ".join(f"{s}: {r.verdict or ('score %+.1f' % r.score)}" for s, r in plan.ta.items())})
    f.append({"name": "Timing", "status": "info", "line": f"{settings.timing['window_days']}-day window",
              "detail": "Secretary rule: watch the first ~37% of the window without acting, then take the first price better than all you saw. Exits that cut risk skip it."})
    if validation:
        f.append({"name": "10-year evidence", "status": "ok" if verdict.get("label") in ("robust edge", "promising, not proven") else "warn",
                  "line": verdict.get("label") or "n/a", "detail": f"Rolling-window test over {validation['years']:.0f} years against doing nothing; see the table below."})
    if profile:
        f.append({"name": "You", "status": "info", "line": f"age {profile.age}, {profile.risk}",
                  "detail": f"Equity guide {profile.equity_cap():.0%} of everything you own. Horizon {profile.horizon_years} years."})
    return f


def build(plan: Plan, settings: Settings, timing: list[str], px: pd.DataFrame, bt: tuple | None, profile: Profile | None,
          others: list[OtherAsset], validation: dict | None, data_note: str, usd_inr: float | None,
          universe: list[dict] | None = None) -> dict:
    sleeve = lambda s: settings.assets[s].sleeve if s in settings.assets else "other"
    pos = plan.positions
    cur = pos.groupby("symbol").value.sum().to_dict() if not pos.empty else {}
    tw = plan.target.weights
    nav = plan.nav
    if tw is None:
        tgt = dict(cur)
    else:
        tgt = {k: v * nav for k, v in tw.items()}
    cash_now = nav - sum(cur.values())
    if cash_now > 1:
        cur["CASH"] = cur.get("CASH", 0) + cash_now
    nodes = lambda d: [{"symbol": k, "name": settings.assets[k].name if k in settings.assets else k, "value": round(v), "sleeve": sleeve(k)}
                       for k, v in sorted(d.items(), key=lambda kv: -kv[1]) if v > 1]
    bt_table = bt[1] if bt else None
    verdict = _verdict(plan, settings, bt_table, validation)
    waits = [l for l in timing if "**wait**" in l]
    if verdict["call"] == "REBALANCE" and waits:
        verdict["reasons"].append(f"Timing: don't place the orders on day one. {len(waits)} leg(s) are in the observation phase of the {settings.timing['window_days']}-day window, "
                                  "and the checklist below says which day to act. Moves that cut risk are exempt.")
    equity_now = sum(v for k, v in cur.items() if sleeve(k) in ("india_equity", "global_equity"))
    equity_after = sum(v for k, v in tgt.items() if sleeve(k) in ("india_equity", "global_equity"))
    emp = profile.employer_ticker.upper() if profile and profile.employer_ticker else ""
    guards = guardrails(profile, others, equity_now, nav, cur.get(emp, 0.0) if emp else 0.0,
                        (equity_after + sum(o.value_inr for o in others if o.asset_class == "equity")) / (nav + sum(o.value_inr for o in others)) if nav else None)
    trades = []
    for t in plan.trades:
        trades.append({"symbol": t.symbol, "side": t.side, "value": round(t.value), "qty": round(t.qty, 4), "price": round(t.price, 2), "kind": t.kind,
                       "cost": round(t.cost), "tax_now": round(t.tax_now), "why": t.why, "tv": _tv_symbol(settings, t.symbol),
                       "lots": [{"buy_date": str(l.buy_date), "qty": round(q, 4)} for l, q in t.lots]})
    holdings = []
    for _, r in pos.iterrows():
        holdings.append({"symbol": r.symbol, "buy_date": str(r.buy_date), "qty": round(r.qty, 3), "cost": round(r.cost), "value": round(r.value), "gain": round(r.gain),
                         "term": "long term" if r.long_term else f"short term ({r.days_to_lt} days to long)"})
    data = {"asof": str(plan.as_of), "nav": round(nav), "data_note": data_note, "usd_inr": usd_inr, "verdict": verdict, "guardrails": guards,
            "current": nodes(cur), "target": nodes(tgt), "trades": trades, "holdings": holdings, "factors": _factors(plan, settings, profile, validation, verdict),
            "steps": _steps(plan, settings, timing), "timing": timing, "notes": plan.notes[:6], "policy_why": plan.target.why,
            "others": [{"kind": o.kind, "name": o.name, "value": round(o.value_inr), "cls": o.asset_class} for o in others],
            "universe": universe, "profile": profile.__dict__ if profile else None, "policy": settings.strategy["policy"], "validation": None, "backtest": None}
    data["regime_filter"] = _regime_filter(plan, settings, px)
    xs = settings.strategy["xs"]
    data["rebalance_parameters"] = {"lookback": max(xs["lookbacks"]), "skip": xs["skip_recent"], "top_k": xs["top_k"], "theta_default": 0.015, "theta_min": 0.005, "theta_max": 0.05,
                                    "sma": settings.strategy["dual_momentum"]["sma"], "core_weight": settings.strategy.get("core_weight"), "check_frequency": settings.timing["check_frequency"],
                                    "ltcg_exemption": settings.tax["ltcg_exemption"]}
    data["execution_blotter"] = _blotter(plan, settings, px)
    # the flow diagram uses the same twin-aware targets as the blotter, so both views agree
    data["target"] = nodes({r["symbol"]: r["tgt_value"] for r in data["execution_blotter"] if r["tgt_value"] > 1})
    data["cross_sectional_universe"] = _momentum_matrix(plan, settings, px)
    if validation:
        from .validate import verdicts
        v = verdicts(validation, VARIANTS[0][0])
        data["validation"] = {"start": validation["start"], "end": validation["end"], "years": validation["years"], "window_years": validation["window_years"],
                              "rows": [{"name": n, **validation["full"][n], **validation["windows"][n], "verdict": v.get(n, "baseline")} for n in validation["full"]],
                              "curves": validation.get("curves")}
    if bt:
        curves, table, logs, start = bt
        used = set()
        evs = {}
        for name, lg in logs.items():
            evs[name] = _events(lg, settings)
            used |= {e["symbol"] for e in evs[name] if e["symbol"]}
        used |= set(cur) | {"NIFTYBEES"}
        used = [s for s in used if s in px and s != "CASH"]
        win = px.loc[curves.index[0] - pd.Timedelta(days=100):curves.index[-1], used].ffill()
        dates = [str(d.date()) for d in win.index]
        pxn = {s: [None if pd.isna(v) else round(float(v), 2) for v in win[s]] for s in used}
        data["backtest"] = {"dates": [str(d.date()) for d in curves.index],
                            "series": {c: [round(float(v)) for v in curves[c]] for c in curves.columns},
                            "summary": [{"name": n, "ret": r["return"], "after_tax": r["after_tax_return_liquidated"], "mdd": r["max_drawdown"], "taxes": r["taxes_paid"], "costs": r["costs"],
                                         "turnover": r["turnover_x"]} for n, r in table.iterrows()],
                            "events": evs, "px_dates": dates, "px": pxn, "active": POLICY_VARIANT.get(settings.strategy["policy"])}
    return data


def _clean(o):
    """NaN/inf are not valid JSON; make them null."""
    if isinstance(o, float):
        return o if np.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        return _clean(o.item())
    return o


def render(data: dict, out: Path) -> Path:
    tpl = (Path(__file__).parent / "site_template.html").read_text()
    blob = json.dumps(_clean(data), default=str).replace("</", "<\\/")
    out.parent.mkdir(exist_ok=True)
    out.write_text(tpl.replace("__DATA__", blob))
    return out
