"""Turn signals into target weights, with a plain-English explanation."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Settings
from .signals import dual_momentum, regime, xs_momentum
from .technical import analyse


@dataclass
class Target:
    weights: dict[str, float] | None      # None => keep current weights (buy & hold)
    risk_off: bool = False                 # equity exits driven by the trend overlay
    why: list[str] = field(default_factory=list)
    scores: pd.DataFrame | None = None
    dual: dict | None = None
    regime: dict | None = None
    review: dict = field(default_factory=dict)   # custom policy: per-holding verdicts
    risk_reason: str = ""                         # one line on why risk is being cut
    guard: dict | None = None                     # crash guard assessment (pe/crash.py)
    urgent: bool = False                          # crisis: skip waiting for long-term tax status


def _xs_sleeve(px: pd.DataFrame, settings: Settings, why: list[str]) -> tuple[dict[str, float], pd.DataFrame]:
    xs = settings.strategy["xs"]
    scores = xs_momentum(px, settings.rotatable(), tuple(xs["lookbacks"]), xs["skip_recent"])
    if scores.empty:
        why.append("Momentum sleeve: not enough price history yet, holding cash.")
        return {"CASH": 1.0}, scores
    eligible = scores[scores["excess_vs_cash"] > 0]
    picks = list(eligible.index[: xs["top_k"]])
    dropped = [s for s in scores.index[: xs["top_k"]] if s not in picks]
    if dropped:
        why.append(f"Momentum sleeve: {', '.join(dropped)} rank high but trail cash over 12 months, so they are skipped (absolute momentum).")
    if not picks:
        why.append("Momentum sleeve: nothing beats cash over 12 months; sleeve goes to cash.")
        return {"CASH": 1.0}, scores
    if xs["weighting"] == "inverse_vol":
        iv = 1 / scores.loc[picks, "vol_6m"]
        w = (iv / iv.sum()).to_dict()
    else:
        w = {s: 1 / len(picks) for s in picks}
    # sleeve caps (e.g. at most 50% offshore), excess to cash
    caps = xs.get("max_per_sleeve", {})
    by_sleeve: dict[str, float] = {}
    for s, x in w.items():
        by_sleeve.setdefault(settings.assets[s].sleeve, 0.0)
        by_sleeve[settings.assets[s].sleeve] += x
    for sl, tot in by_sleeve.items():
        cap = caps.get(sl)
        if cap is not None and tot > cap:
            for s in w:
                if settings.assets[s].sleeve == sl:
                    w[s] *= cap / tot
    w["CASH"] = w.get("CASH", 0.0) + max(0.0, 1 - sum(w.values()))
    top = ", ".join(f"{s} (score {scores.loc[s, 'score']:+.2f}, 12m {scores.loc[s, 'ret_12m']:+.1%})" for s in picks)
    why.append(f"Momentum sleeve picks the top {len(picks)} by 6m+12m volatility-adjusted momentum: {top}.")
    return w, scores


def build_target(px: pd.DataFrame, vix: pd.Series | None, settings: Settings, policy: str | None = None,
                 held_weights: dict[str, float] | None = None, guard_level: int | None = None, guard_mem: dict | None = None) -> Target:
    """`policy+guard` runs the policy, then lets the crash guard (pe/crash.py) cut risk assets when warning signals stack up."""
    st = settings.strategy
    policy = policy or st["policy"]
    if policy.endswith("+guard"):
        from . import crash
        t = build_target(px, vix, settings, policy[:-6], held_weights)
        return crash.apply_guard(t, crash.assess(px, vix, settings, guard_level), px, settings, held_weights or {}, guard_mem)
    if "+" in policy:      # valuation / forecast overlay on any base policy, e.g. "core_xs+pe"
        return _with_valuation(px, vix, settings, policy, held_weights)
    dm_cfg = st["dual_momentum"]
    reg = regime(px, vix, dm_cfg["equity"])
    dm = dual_momentum(px, dm_cfg["equity"], dm_cfg["gold"], dm_cfg["cash"], dm_cfg["lookback"], dm_cfg["sma"])
    why = [f"Market regime: {reg['label'].replace('_', '-')}. " + " ".join(reg["why"])]

    if policy == "buy_hold":
        return Target(None, why=why + ["Policy is buy & hold: no rotation."], dual=dm, regime=reg)

    if policy == "dual_momentum":
        choice = dm["choice"] or dm_cfg["equity"]
        return Target({choice: 1.0}, risk_off=choice != dm_cfg["equity"], why=why + dm["why"],
                      dual=dm, regime=reg, risk_reason=dm["why"][-1])

    if policy == "xs_momentum":
        w, scores = _xs_sleeve(px, settings, why)
        return Target(w, why=why, scores=scores, dual=dm, regime=reg)

    if policy == "core_satellite":
        core_w = st["core_weight"]
        core = st["core_symbol"]
        risk_off = False
        if st.get("core_overlay") == "dual_momentum" and dm["choice"] and dm["choice"] != dm_cfg["equity"]:
            risk_off = True
            why.append(f"Core ({core_w:.0%}) overlay: dual momentum says {dm['choice']} instead of {core}. " + " ".join(dm["why"]))
            core = dm["choice"]
        else:
            why.append(f"Core ({core_w:.0%}) stays in {core}: the trend overlay is not signalling risk-off, and leaving it alone defers tax.")
        sat, scores = _xs_sleeve(px, settings, why)
        w = {core: core_w}
        for s, x in sat.items():
            w[s] = w.get(s, 0.0) + x * (1 - core_w)
        return Target(w, risk_off=risk_off, why=why, scores=scores, dual=dm, regime=reg,
                      risk_reason=f"dual momentum prefers {dm['choice']} to {dm_cfg['equity']}" if risk_off else "")

    if policy == "static_mix":
        c = st["static_mix"]
        w = {k: float(v) for k, v in c["weights"].items() if k in px and px[k].iloc[-1] == px[k].iloc[-1]}
        w["CASH"] = w.get("CASH", 0.0) + 1 - sum(w.values())
        return Target(w, why=why + [f"Fixed mix {', '.join(f'{k} {v:.0%}' for k, v in w.items())}: no forecasting. Only trades when drift from target is large "
                                    "enough to beat costs and tax, which is why it suits a taxable account."], dual=dm, regime=reg)

    if policy == "core_xs":   # core_satellite without the core trend overlay: the core is never sold on a signal
        saved = st.get("core_overlay")
        st["core_overlay"] = "none"
        try:
            return build_target(px, vix, settings, "core_satellite", held_weights)
        finally:
            st["core_overlay"] = saved

    if policy == "rp_blend":   # half Nifty, half risk parity
        c = st["rp_blend"]
        rp = _risk_parity(px, settings, [], dm, reg)
        w = {k: v * (1 - c["nifty_weight"]) for k, v in rp.weights.items()}
        w[c["nifty_symbol"]] = w.get(c["nifty_symbol"], 0.0) + c["nifty_weight"]
        return Target(w, why=why + [f"{c['nifty_weight']:.0%} stays in {c['nifty_symbol']} (tax deferral, upside), the rest follows risk parity. " + " ".join(rp.why)],
                      dual=dm, regime=reg)

    if policy == "custom":
        return _custom(px, settings, why, dm, reg, held_weights or {})
    if policy == "trend_vol":
        return _trend_vol(px, settings, why, dm, reg)
    if policy == "risk_parity":
        return _risk_parity(px, settings, why, dm, reg)
    if policy == "daa":
        return _daa(px, settings, why, dm, reg)
    raise ValueError(f"Unknown policy {policy}")


def _avail(px: pd.DataFrame, syms: list[str], need: int) -> list[str]:
    return [s for s in syms if s in px and px[s].iloc[-need:].notna().all()]


def _cap(w: dict[str, float], cap: float) -> dict[str, float]:
    """Cap single weights, redistributing the excess pro rata to uncapped names (excess to CASH if all capped)."""
    w = dict(w)
    for _ in range(10):
        over = {s: x for s, x in w.items() if x > cap + 1e-12}
        if not over:
            break
        excess = sum(x - cap for x in over.values())
        for s in over:
            w[s] = cap
        free = {s: x for s, x in w.items() if x < cap - 1e-12 and s != "CASH"}
        tot = sum(free.values())
        if tot <= 0:
            w["CASH"] = w.get("CASH", 0.0) + excess
            break
        for s in free:
            w[s] += excess * free[s] / tot
    return w


def _trend_vol(px, settings, why, dm, reg) -> Target:
    c = settings.strategy["trend_vol"]
    syms = _avail(px, c["assets"], c["sma"] + 1)
    up = [s for s in syms if px[s].iloc[-1] > px[s].iloc[-c["sma"]:].mean()]
    down = [s for s in syms if s not in up]
    why.append(f"Trend filter ({c['sma']}-day average): uptrend {', '.join(up) or 'none'}; downtrend {', '.join(down) or 'none'}.")
    if not up:
        why.append("Every asset is in a downtrend, so the whole portfolio goes to the cash sleeve.")
        return Target({"CASH": 1.0}, risk_off=True, why=why, dual=dm, regime=reg, risk_reason="every asset is below its trend line")
    rets = px[up].pct_change().iloc[-c["vol_window"]:]
    iv = 1 / (rets.std() * np.sqrt(252))
    w = _cap((iv / iv.sum()).to_dict(), c["max_weight"])
    wv = pd.Series(w).reindex(up).fillna(0.0).values        # _cap may have parked excess in CASH, which is not in `up`
    port_vol = float(np.sqrt(wv @ (rets[up].cov().values * 252) @ wv))
    scale = min(1.0, c["target_vol"] / port_vol) if port_vol > 0 else 1.0
    w = {s: x * scale for s, x in w.items()}
    w["CASH"] = w.get("CASH", 0.0) + 1 - sum(w.values())
    why.append(f"Inverse-volatility weights across the uptrending assets; their mix has {port_vol:.1%} recent volatility "
               f"vs the {c['target_vol']:.0%} target, so exposure is {scale:.0%} and the rest sits in cash. "
               "Volatility clusters, so cutting exposure when it rises historically trims crash losses more than returns.")
    return Target(w, risk_off=bool(down) or scale < 0.999, why=why, dual=dm, regime=reg,
                  risk_reason=(f"downtrend in {', '.join(down)}" if down else "") + ("; " if down and scale < 0.999 else "")
                  + (f"volatility above target, exposure cut to {scale:.0%}" if scale < 0.999 else ""))


def _risk_parity(px, settings, why, dm, reg) -> Target:
    c = settings.strategy["risk_parity"]
    syms = _avail(px, c["assets"], c["vol_window"] + 1)
    vol = px[syms].pct_change().iloc[-c["vol_window"]:].std() * np.sqrt(252)
    vol = vol.clip(lower=0.02)   # the cash sleeve has ~0 volatility; floor it so it does not swallow the book
    w = _cap((1 / vol / (1 / vol).sum()).to_dict(), c["max_weight"])
    why.append("Risk parity: each asset class gets weight in inverse proportion to its volatility "
               f"({', '.join(f'{s} {v:.0%}' for s, v in vol.items())}), so no single market dominates the risk. "
               "No return forecast is needed, which makes it robust when forecasts are least reliable.")
    return Target(w, why=why, dual=dm, regime=reg)


def _m13612(px: pd.DataFrame, s: str) -> float:
    p = px[s]
    r = lambda d: p.iloc[-1] / p.iloc[-1 - d] - 1
    return (12 * r(21) + 4 * r(63) + 2 * r(126) + r(252)) / 4


def _daa(px, settings, why, dm, reg) -> Target:
    c = settings.strategy["daa"]
    canary = _avail(px, c["canary"], 253)
    risky = _avail(px, c["risky"], 253)
    defensive = _avail(px, c["defensive"], 253)
    cm = {s: _m13612(px, s) for s in canary}
    bad = [s for s, v in cm.items() if v <= 0]
    frac_def = len(bad) / max(len(canary), 1)
    why.append("DAA canaries (13612W momentum): " + ", ".join(f"{s} {v:+.1%}" for s, v in cm.items())
               + f". {len(bad)} of {len(canary)} negative, so {frac_def:.0%} goes defensive. "
               "Emerging markets and bonds tend to crack before broad equity crashes, which is why they are used as early warnings.")
    w: dict[str, float] = {}
    if frac_def < 1 and risky:
        rm = sorted(((s, _m13612(px, s)) for s in risky), key=lambda x: -x[1])[: c["top_risky"]]
        for s, v in rm:
            w[s] = w.get(s, 0.0) + (1 - frac_def) / len(rm)
        why.append("Offensive picks: " + ", ".join(f"{s} ({v:+.1%})" for s, v in rm) + ".")
    if frac_def > 0:
        best = max(defensive, key=lambda s: _m13612(px, s)) if defensive else "CASH"
        w[best] = w.get(best, 0.0) + frac_def
        why.append(f"Defensive slot goes to {best}, the strongest of {', '.join(defensive)}.")
    return Target(w, risk_off=frac_def > 0, why=why, dual=dm, regime=reg,
                  risk_reason=f"canary momentum negative for {', '.join(bad)}")


def _custom(px, settings, why, dm, reg, held: dict[str, float]) -> Target:
    """Keep what you own; exit only on converging evidence, trim concentration, optional regime cut.

    A holding is exited when at least `min_flags` of these agree: technical downtrend,
    trailing stop breached, bottom-quartile momentum that also trails cash over 12 months.
    """
    c = settings.strategy["custom"]
    held = {s: w for s, w in held.items() if w > 0}
    if not held:
        why.append("Custom policy: nothing held yet.")
        return Target(None, why=why, dual=dm, regime=reg)
    pool = sorted(set(settings.rotatable()) | {s for s in held if s != "CASH"})
    xs = xs_momentum(px, pool, tuple(settings.strategy["xs"]["lookbacks"]), settings.strategy["xs"]["skip_recent"])
    w = dict(held)
    review, exits, risk, reasons = {}, [], False, []
    for s in held:
        if s == "CASH":
            continue
        a = settings.assets[s]
        ta = analyse(s, px[s]) if s in px else None
        flags, notes = [], []
        if ta is None:
            review[s] = {"verdict": "no data", "flags": [], "why": ["Not enough price history for analysis."], "ta": None}
            continue
        if ta.score <= -0.75:
            flags.append("downtrend")
        if ta.stop_breached:
            flags.append("stop breached")
        if not xs.empty and s in xs.index:
            pct = 1 - (xs.loc[s, "rank"] - 1) / max(len(xs) - 1, 1)
            notes.append(f"Momentum rank {int(xs.loc[s, 'rank'])} of {len(xs)} (score {xs.loc[s, 'score']:+.2f}).")
            if pct <= 0.25 and xs.loc[s, "excess_vs_cash"] < 0:
                flags.append("weak momentum")
        verdict = "hold"
        if len(flags) >= c["min_flags"]:
            verdict = "exit"
            exits.append(s)
            w[s] = 0.0
        elif flags:
            verdict = "watch"
        is_stock = a.venue in ("nse_stock",) or (a.venue == "ibkr_us" and a.sleeve != "global_equity")
        if verdict != "exit" and is_stock and w[s] > c["max_single_stock"]:
            notes.append(f"Position is {w[s]:.0%} of the portfolio, above the {c['max_single_stock']:.0%} single-stock cap.")
            w[s] = c["max_single_stock"]
            verdict = "trim" if verdict == "hold" else verdict + " + trim"
            risk = True
            reasons.append(f"{s} above the single-stock cap")
        review[s] = {"verdict": verdict, "flags": flags, "why": [f"Technical view: {ta.verdict} (score {ta.score:+.1f})."] + ta.why + notes,
                     "ta": ta}
    freed = sum(held.values()) - sum(w.values())
    if exits:
        why.append(f"Custom policy: exit {', '.join(exits)} (at least {c['min_flags']} of: downtrend, stop breached, weak momentum).")
        risk = True
        reasons.append(f"converging weakness in {', '.join(exits)}")
    if c.get("overlay") == "dual_momentum" and dm.get("choice") and dm["choice"] != settings.strategy["dual_momentum"]["equity"]:
        cut = c["risk_off_cut"]
        for s in list(w):
            if s != "CASH" and settings.assets[s].sleeve in ("india_equity", "global_equity"):
                freed += w[s] * cut
                w[s] *= 1 - cut
        why.append(f"Regime overlay: dual momentum is risk-off ({dm['choice']}), so equity holdings are cut by {cut:.0%}. " + " ".join(dm["why"]))
        risk = True
        reasons.append(f"market trend overlay is risk-off ({dm['choice']} preferred)")
    if freed > 1e-9:
        dest = c["exit_to"] if not (c.get("overlay") == "dual_momentum" and dm.get("choice") and dm["choice"] != settings.strategy["dual_momentum"]["equity"]) else dm["choice"]
        w[dest] = w.get(dest, 0.0) + freed
        why.append(f"Freed weight ({freed:.0%}) goes to {dest}.")
    if not exits and freed <= 1e-9:
        why.append("Custom policy: no holding shows enough converging weakness to sell; keep everything.")
    return Target(w, risk_off=risk, why=why, scores=xs, dual=dm, regime=reg, review=review, risk_reason="; ".join(reasons))


def _with_valuation(px, vix, settings, policy: str, held_weights) -> Target:
    """Base policy, then cut India-equity weight by the valuation/forecast scale factor; the cut goes to cash."""
    from .valuation import scale_for
    base_name, kind = policy.split("+", 1)
    if base_name == "nifty":      # pure test of the signal: Nifty 50 ETF scaled up and down, remainder cash
        sym = settings.strategy["dual_momentum"]["equity"]
        base = Target({sym: 1.0}, why=[f"Nifty-only baseline in {sym}."], regime=regime(px, vix, sym))
    else:
        base = build_target(px, vix, settings, base_name, held_weights)
    sig = settings.raw.get("_valuation_signals")
    if sig is None or base.weights is None:
        return base
    f = scale_for(sig, kind, px.index[-1])
    if f >= 0.999:
        return base
    w = dict(base.weights)
    cut = 0.0
    for s in list(w):
        if settings.assets[s].sleeve == "india_equity":
            cut += w[s] * (1 - f)
            w[s] *= f
    w["CASH"] = w.get("CASH", 0.0) + cut
    base.weights = w
    base.risk_off = True
    base.risk_reason = f"{kind} signal cuts India equity to {f:.0%}"
    base.why.append(f"Valuation overlay ({kind}): India equity scaled to {f:.0%} of its base weight; the difference sits in cash.")
    return base
