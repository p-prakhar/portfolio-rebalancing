from types import SimpleNamespace as NS

import numpy as np
import pandas as pd

from pe.backtest import _check_days
from pe.stopping import threshold_decision
from pe.timing import apply_gate, cost_band_width, dca_study, exec_study, kelly_fraction


def test_threshold_rule_waits_then_forces():
    assert threshold_decision([100, 100.1], 10, "buy", 0.01)[0] == "observe"
    assert threshold_decision([100, 97], 10, "buy", 0.01)[0] == "execute"      # fell past the barrier: good buy
    assert threshold_decision([100, 103], 10, "sell", 0.01)[0] == "execute"
    assert threshold_decision([100] * 10, 10, "buy", 0.01)[0] == "execute"      # last day always fills


def test_cost_band_widens_with_cost_and_is_a_cube_root():
    assert cost_band_width(0.6, 0.02) > cost_band_width(0.6, 0.005)
    assert abs(cost_band_width(0.6, 0.008) / cost_band_width(0.6, 0.001) - 2.0) < 1e-9     # 8x the cost -> 2x the band
    assert cost_band_width(0.6, 0.01, gamma=6) < cost_band_width(0.6, 0.01, gamma=2)


def _trade(kind, side, value, cost=0.0):
    return NS(kind=kind, side=side, value=value, cost=cost, econ_tax=0.0)


def test_gate_holds_small_moves_but_never_risk_exits_or_harvests():
    plan = NS(nav=1_000_000, trades=[_trade("rebalance", "sell", 40_000), _trade("rebalance", "buy", 40_000),
                                     _trade("harvest_gain", "sell", 5_000)], target=NS(weights={}))
    kept, why = apply_gate(plan, None, "band", {"width": 0.05}, None)
    assert [t.kind for t in kept] == ["harvest_gain"] and "inside" in why
    plan.trades[0].value = plan.trades[1].value = 80_000
    assert apply_gate(plan, None, "band", {"width": 0.05}, None)[0] == plan.trades
    plan.trades[0].value, plan.trades[0].kind = 10_000, "risk_exit"
    assert apply_gate(plan, None, "band", {"width": 0.05}, None)[0] == plan.trades
    assert apply_gate(plan, None, "calendar", {}, None)[0] == plan.trades


def test_calendar_frequencies():
    idx = pd.bdate_range("2020-01-01", "2022-12-31")
    assert len(_check_days(idx, "quarterly")) == 12
    a = _check_days(idx, "annual_mar")
    assert len(a) == 3 and all(pd.Timestamp(d).month == 3 for d in a)


def test_random_walk_gives_no_fill_rule_a_reliable_edge():
    rng = np.random.default_rng(0)
    p = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 3000)))
    e = exec_study(p, side="buy")
    for r in ("twap", "secretary", "threshold", "bandit"):
        assert e["rules"][r]["lo"] < 5 and e["rules"][r]["hi"] > -5, r       # range straddles zero (basis points)


def test_lump_sum_wins_on_a_rising_market_and_kelly_is_capped():
    p = 100 * np.exp(np.arange(1500) * 0.0005 + np.random.default_rng(1).normal(0, 0.004, 1500).cumsum())
    d = dca_study(p, tranches=6)
    assert d["lump_wins"] > 0.5 and d["mean_edge"] > 0
    assert kelly_fraction(0.5, 0.1) == 1.0 and kelly_fraction(-0.02, 0.2) == 0.0
