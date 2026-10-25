"""When to act: no-trade bands, calendar choices, fill rules and the studies that compare them.

Three separate questions, each with pluggable rules:
  1. Trigger: given a plan from the strategy, is it worth acting now? (`apply_gate`)
       calendar   always act (the check frequency is the only brake)
       band       act only if one-way turnover is at least a fixed share of the portfolio
       cost_band  band sized from the plan's own cost and tax leak, after Rogers and Mayer (1994):
                  half-width = (3 / (2 gamma) * pi^2 * (1 - pi)^2 * lambda) ^ (1/3),
                  pi = risky share, lambda = cost + tax per rupee traded, gamma = risk aversion.
                  Costs enter as a cube root, so a band several times wider than the cost itself is normal.
     Risk-reducing exits always pass: the band is about drift, not about running from a crash.
  2. Fill: how to execute inside the window (immediate, twap, secretary, threshold; see stopping.py and `exec_study`).
  3. Size: Kelly (`kelly_fraction`) answers how much, not when; reported for context only.

`exec_study` and `dca_study` need only a price series, so they run on real prices or synthetic ones.
"""
from __future__ import annotations

import math

import numpy as np

from .engine import RISK_SLEEVES
from .stopping import secretary_decision, threshold_decision


def one_way_turnover(trades, nav: float) -> float:
    sells = sum(t.value for t in trades if t.side == "sell" and t.kind in ("rebalance", "risk_exit"))
    buys = sum(t.value for t in trades if t.side == "buy" and t.kind == "rebalance")
    return max(sells, buys) / nav if nav > 0 else 0.0


def cost_band_width(pi: float, lam: float, gamma: float = 3.0) -> float:
    pi = min(max(pi, 0.05), 0.95)
    return (1.5 / gamma * pi ** 2 * (1 - pi) ** 2 * lam) ** (1 / 3)


def apply_gate(plan, book, kind: str, args: dict, settings) -> tuple[list, str]:
    """Return (trades to keep, reason if the rebalance legs were held back)."""
    if kind == "calendar":
        return plan.trades, ""
    rebal = [t for t in plan.trades if t.kind in ("rebalance", "risk_exit")]
    if not rebal or any(t.kind == "risk_exit" for t in rebal):
        return plan.trades, ""
    d = one_way_turnover(plan.trades, plan.nav)
    if kind == "band":
        width, how = args.get("width", 0.05), "fixed band"
    elif kind == "cost_band":
        moved = sum(t.value for t in rebal) or 1.0
        lam = sum(t.cost + max(t.econ_tax, 0.0) for t in rebal) / moved
        w = plan.target.weights or {}
        pi = sum(v for s, v in w.items() if settings.assets[s].sleeve in RISK_SLEEVES)
        width, how = cost_band_width(pi, lam, args.get("gamma", 3.0)), f"cost band (cost+tax {lam:.2%} per rupee, risky share {pi:.0%})"
    else:
        raise ValueError(f"unknown gate {kind}")
    if d >= width:
        return plan.trades, ""
    kept = [t for t in plan.trades if t.kind.startswith("harvest")]
    return kept, f"HOLD: plan moves {d:.1%} of the portfolio, inside the {width:.1%} {how}; not worth the cost and tax."


def kelly_fraction(excess_return: float, vol: float, shrink: float = 0.5, cap: float = 1.0) -> float:
    """Fractional Kelly weight for a risky asset: shrink * mu / sigma^2, with mu the expected excess return over cash.
    A sizing rule. With honest (small, uncertain) estimates it says how much risk to carry, not when to trade."""
    return float(min(max(shrink * excess_return / vol ** 2, 0.0), cap)) if vol > 0 else 0.0


# ---------------------------------------------------------------- price-only studies

RULES = ("immediate", "twap", "secretary", "threshold")


def _fill(rule: str, window: np.ndarray, side: str, sigma: float, z: float = 0.5) -> float:
    """Average price paid (or received) for one order given the next n closes; window[0] is the day the order is placed."""
    n = len(window)
    if rule == "immediate":
        return float(window[0])
    if rule == "twap":
        return float(window.mean())
    for k in range(1, n + 1):
        obs = list(window[:k])
        dec = (secretary_decision(obs, n, side) if rule == "secretary" else threshold_decision(obs, n, side, sigma, z))[0]
        if dec == "execute":
            return float(window[k - 1])
    return float(window[-1])


def exec_study(prices: np.ndarray, window: int = 10, step: int = 5, side: str = "buy", seed: int = 3,
               n_boot: int = 2000) -> dict:
    """Over many order windows, slippage of each fill rule against filling at once, in basis points of the price.
    Positive = better than immediate. Includes a Thompson-sampling bandit that learns which rule to use, one order at a time."""
    p = np.asarray(prices, dtype=float)
    rets = np.diff(np.log(p))
    sigma = float(np.std(rets))
    starts = list(range(60, len(p) - window, step))
    sgn = -1.0 if side == "buy" else 1.0           # lower fill is better for a buy, higher for a sell
    gain = {r: np.array([sgn * (_fill(r, p[s:s + window], side, float(np.std(rets[s - 60:s]))) / p[s] - 1) for s in starts]) * 1e4
            for r in RULES}
    rng = np.random.default_rng(seed)
    arms, mean, cnt, picks, bandit = list(RULES), {r: 0.0 for r in RULES}, {r: 0 for r in RULES}, {r: 0 for r in RULES}, []
    for i in range(len(starts)):
        draw = {r: rng.normal(mean[r], 50 / math.sqrt(cnt[r] + 1)) for r in arms}        # wide prior: 50 bp
        r = max(draw, key=draw.get)
        x = gain[r][i]
        cnt[r] += 1
        mean[r] += (x - mean[r]) / cnt[r]
        picks[r] += 1
        bandit.append(x)
    gain["bandit"] = np.array(bandit)
    out = {"window": window, "side": side, "orders": len(starts), "daily_sigma": sigma,
           "bandit_picks": {r: picks[r] / len(starts) for r in RULES}, "rules": {}}
    n = len(starts)
    for r, g in gain.items():
        blk = max(1, window // step + 1)
        idx = (rng.integers(0, n, size=(n_boot, int(np.ceil(n / blk))))[:, :, None] + np.arange(blk)).reshape(n_boot, -1)[:, :n] % n
        means = g[idx].mean(axis=1)
        out["rules"][r] = {"mean_bp": float(g.mean()), "lo": float(np.percentile(means, 5)), "hi": float(np.percentile(means, 95)),
                           "sd_bp": float(g.std()), "worst_bp": float(g.min())}
    return out


def dca_study(prices: np.ndarray, tranches: int = 6, gap_days: int = 21, step: int = 21, seed: int = 3, n_boot: int = 2000) -> dict:
    """Lump sum today versus equal tranches every `gap_days`, compared at the end of the
    DCA period. Before cost and tax (both favour the lump sum, so this flatters DCA)."""
    p = np.asarray(prices, dtype=float)
    span = tranches * gap_days
    starts = list(range(0, len(p) - span - 1, step))
    diff = []
    for s in starts:
        end = p[s + span]
        lump = end / p[s]
        dca = np.mean([end / p[s + k * gap_days] for k in range(tranches)])
        diff.append(lump - dca)
    d = np.array(diff)
    rng = np.random.default_rng(seed)
    blk = max(1, span // step)
    idx = (rng.integers(0, len(d), size=(n_boot, int(np.ceil(len(d) / blk))))[:, :, None] + np.arange(blk)).reshape(n_boot, -1)[:, :len(d)] % len(d)
    m = d[idx].mean(axis=1)
    return {"tranches": tranches, "months": span / 21, "samples": len(d), "lump_wins": float((d > 0).mean()),
            "mean_edge": float(d.mean()), "lo": float(np.percentile(m, 5)), "hi": float(np.percentile(m, 95)),
            "dca_worst_saved": float(-d.min())}
