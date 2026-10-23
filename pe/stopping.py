"""Optimal-stopping rules used to decide WHEN to act.

1. Secretary rule for execution inside a window of n trading days: observe the first
   round(n/e) days without trading, then act on the first day whose price beats every
   price seen so far (higher for a sell, lower for a buy); if none does, act on the last
   day. For i.i.d. offers this maximises the chance of hitting the single best day (~37%).
   Prices are closer to a random walk than i.i.d., so expect it to reduce regret and
   spread timing risk rather than to add return; the backtest compares it with
   immediate and TWAP execution so you can see which holds up.

2. Long-term-status wait: when a lot that should be sold turns long term within d days,
   waiting saves (STCG rate - LTCG rate) x gain. The expected cost of waiting is the
   expected adverse move of an asset you no longer want, about
   E[max(0, -X)] = sigma * sqrt(d/252) / sqrt(2*pi) of its value for X ~ N(0, sigma^2 d/252).
   Wait if the saving beats that cost (doubled when the exit is a risk-off signal).
"""
from __future__ import annotations

import math


def secretary_cutoff(n: int) -> int:
    return max(1, round(n / math.e))


def secretary_decision(observed: list[float], n: int, side: str) -> tuple[str, str]:
    """Given prices observed so far in the window (including today), decide today.

    Returns (decision, why) with decision in {"observe", "execute"}.
    """
    k = secretary_cutoff(n)
    day = len(observed)
    today = observed[-1]
    if day <= k:
        return "observe", (f"Day {day} of {n}: observation phase (first {k} days). "
                           f"Best {'high' if side == 'sell' else 'low'} so far {max(observed[:day]) if side == 'sell' else min(observed[:day]):.2f}.")
    ref = observed[:k]
    prior = observed[:-1]
    if side == "sell":
        better = today > max(prior)
        bench = max(ref)
    else:
        better = today < min(prior)
        bench = min(ref)
    if better:
        return "execute", (f"Day {day} of {n}: price {today:.2f} beats every price seen in this window "
                           f"(observation-phase benchmark {bench:.2f}), so the secretary rule says act now.")
    if day >= n:
        return "execute", f"Day {day} of {n}: last day of the window, so execute regardless of price."
    return "observe", (f"Day {day} of {n}: price {today:.2f} has not beaten the best seen so far; keep waiting "
                       f"(the window closes in {n - day} trading days).")


def ltcg_wait(gain: float, value: float, days: int, sigma: float, st_rate: float, lt_rate: float,
              risk_off: bool = False) -> tuple[bool, float, float, str]:
    """Should a sale be deferred until the lot turns long term? Returns (wait, saving, cost, why)."""
    if gain <= 0 or days <= 0:
        return False, 0.0, 0.0, ""
    saving = gain * (st_rate - lt_rate)
    cost = value * sigma * math.sqrt(days / 252) / math.sqrt(2 * math.pi)
    if risk_off:
        cost *= 2
    wait = saving > cost
    why = (f"Lot turns long term in {days} days. Waiting saves about Rs {saving:,.0f} of tax "
           f"({st_rate:.1%} vs {lt_rate:.1%}); the expected adverse move while waiting is about Rs {cost:,.0f}"
           f"{' (doubled because this is a risk-off exit)' if risk_off else ''}. "
           + ("Waiting is worth it." if wait else "Not worth waiting."))
    return wait, saving, cost, why
