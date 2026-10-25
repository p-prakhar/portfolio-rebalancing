"""Forward look for the live report: what the next few years could be like for what you hold today.

Resamples the past daily returns of your current mix in 3-month-ish blocks (see stats.monte_carlo). Pre-tax and
without rebalancing; it shows the range of outcomes and drawdowns, not a prediction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import monte_carlo, xirr


def holdings_xirr(positions: pd.DataFrame, as_of) -> float | None:
    if positions is None or positions.empty:
        return None
    flows = [(r.buy_date, -float(r.cost)) for r in positions.itertuples()]
    flows.append((as_of, float(positions.value.sum())))
    return xirr(flows)


def mix_returns(positions: pd.DataFrame, px: pd.DataFrame) -> np.ndarray:
    w = positions.groupby("symbol").value.sum()
    w = w[w.index.isin(px.columns)]
    if w.empty:
        return np.array([])
    w = w / w.sum()
    r = px[list(w.index)].pct_change().dropna()
    return (r * w).sum(axis=1).to_numpy()


def forward_lines(positions: pd.DataFrame, px: pd.DataFrame, years: float = 3.0) -> list[str]:
    if positions is None or positions.empty:
        return []
    r = mix_returns(positions, px)
    mc = monte_carlo(r, float(positions.value.sum()), years)
    if not mc:
        return []
    rs = lambda x: f"Rs {x:,.0f}"
    return [f"## What the next {mc['years']:.0f} years could look like\n",
            f"Resampling {len(r) / 252:.1f} years of daily returns of today's mix (before tax, no rebalancing). "
            "This is a range from history repeating in shuffled order, not a forecast.\n",
            f"- Value after {mc['years']:.0f} years: typical **{rs(mc['end_p50'])}**, bad case (1 in 10) {rs(mc['end_p10'])}, "
            f"good case (1 in 10) {rs(mc['end_p90'])}, from {rs(mc['start'])} today.",
            f"- Chance of ending below today's value: **{mc['prob_loss']:.0%}**.",
            f"- Worst fall from a peak along the way: typically **{mc['mdd_p50']:.0%}**, in 1 of 10 paths {mc['mdd_p10']:.0%} or worse.",
            f"- Chance of a fall of 20% or more at some point: **{mc['prob_dd_20']:.0%}**; of 30% or more: {mc['prob_dd_30']:.0%}.", ""]
