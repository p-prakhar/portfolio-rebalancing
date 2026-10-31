from datetime import date

import numpy as np
import pandas as pd
import pytest

from pe import goals as G
from pe.config import Lot, load_settings
from pe.engine import make_plan

S = load_settings()
CFG = S["goals"]
TODAY = date(2026, 6, 1)


def test_glide_path_shape():
    assert G.safe_share(8, "must", CFG) == 0
    assert G.safe_share(5, "must", CFG) == 0
    assert G.safe_share(1, "must", CFG) == 1
    assert G.safe_share(0.2, "must", CFG) == 1
    assert 0 < G.safe_share(3, "must", CFG) < 1
    # a goal that can slip starts de-risking later
    assert G.safe_share(4, "nice", CFG) == 0 < G.safe_share(4, "must", CFG)
    shares = [G.safe_share(y / 2, "must", CFG) for y in range(12, 0, -1)]
    assert shares == sorted(shares)


def test_far_goal_does_not_cap_risk():
    far = [G.Goal("far", 500000, date(2036, 6, 1))]
    gp = G.assess(far, TODAY, 2_000_000, 0.0, 0.0, S)
    assert gp.risk_cap == 1.0


def test_near_goal_caps_risk_and_outside_safe_money_counts():
    near = [G.Goal("near", 1_000_000, date(2027, 1, 1))]
    gp = G.assess(near, TODAY, 2_000_000, 0.0, 0.0, S)
    assert gp.risk_cap == pytest.approx(1 - gp.safe_needed_total / 2_000_000)
    assert gp.safe_needed_total > 900_000
    with_fd = G.assess(near, TODAY, 2_000_000, 0.0, 600_000, S)
    assert with_fd.risk_cap > gp.risk_cap


def test_underfunded_goal_reports_shortfall_and_saving():
    big = [G.Goal("big", 5_000_000, date(2027, 6, 1))]
    st = G.assess(big, TODAY, 1_000_000, 0.0, 0.0, S).statuses[0]
    assert st.shortfall_at_due > 0 and st.monthly_needed > 0
    assert st.monthly_needed * 12 * st.years == pytest.approx(st.shortfall_at_due, rel=0.1)


def test_goals_are_funded_earliest_first():
    gs = [G.Goal("later", 600_000, date(2029, 1, 1)), G.Goal("sooner", 900_000, date(2027, 3, 1))]
    sts = G.assess(gs, TODAY, 1_000_000, 0.0, 0.0, S).statuses
    assert [s.goal.name for s in sts] == ["sooner", "later"]
    assert sts[0].shortfall_at_due == 0 and sts[1].shortfall_at_due > 0


def _book():
    # losing lot, long-term gain lot, short-term gain lot: all different symbols so FIFO does not bind
    lots = [Lot("BANKBEES", 100, date(2025, 1, 1), 600.0),     # held > 12m, will be at a loss
            Lot("NIFTYBEES", 1000, date(2024, 1, 1), 200.0),    # long-term gain
            Lot("JUNIORBEES", 500, date(2026, 4, 1), 600.0)]    # short-term gain
    px = pd.Series({"BANKBEES": 500.0, "NIFTYBEES": 400.0, "JUNIORBEES": 700.0})
    return lots, px


def test_withdrawal_sells_loss_first_then_long_term_before_short_term():
    lots, px = _book()
    w = G.withdrawal_plan(300_000, lots, 0.0, px, TODAY, S)
    assert w.shortfall == 0 and w.net == pytest.approx(300_000, abs=5)
    assert any(s.lot.symbol == "BANKBEES" and s.gain < 0 for s in w.sales)   # the loss offsets taxable long-term gain
    big = G.withdrawal_plan(380_000, lots, 0.0, px, TODAY, S)
    syms = [s.lot.symbol for s in big.sales]
    assert "JUNIORBEES" not in syms           # short-term gain is last resort
    assert big.burden <= big.naive_burden + 1


def test_cash_is_used_first_and_shortfall_is_reported():
    lots, px = _book()
    w = G.withdrawal_plan(50_000, lots, 80_000, px, TODAY, S)
    assert w.from_cash == 50_000 and not w.sales and w.tax == 0
    huge = G.withdrawal_plan(10_000_000, lots, 0.0, px, TODAY, S)
    assert huge.shortfall > 0 and any("cannot raise" in n for n in huge.notes)


def test_fifo_takes_oldest_units_within_a_symbol():
    lots = [Lot("NIFTYBEES", 100, date(2026, 5, 1), 270.0), Lot("NIFTYBEES", 100, date(2023, 1, 1), 150.0)]
    px = pd.Series({"NIFTYBEES": 280.0})
    w = G.withdrawal_plan(10_000, lots, 0.0, px, TODAY, S)
    assert w.sales[0].lot.buy_date == date(2023, 1, 1)


def test_waiting_for_long_term_status_is_suggested():
    lots = [Lot("NIFTYBEES", 1000, date(2025, 7, 1), 200.0)]     # turns long term on 2026-07-02
    px = pd.Series({"NIFTYBEES": 300.0})
    w = G.withdrawal_plan(150_000, lots, 0.0, px, TODAY, S)
    assert any("long term" in n for n in w.notes)


def test_make_plan_trims_growth_to_goal_cap():
    idx = pd.bdate_range("2025-01-01", "2026-06-01")
    px = pd.DataFrame({c: np.linspace(100, 130, len(idx)) for c in S.assets if S.assets[c].ticker}, index=idx)
    px["CASH"] = np.linspace(100, 106, len(idx))
    lots = [Lot("NIFTYBEES", 10_000, date(2024, 1, 1), 90.0)]
    goals = [G.Goal("soon", 700_000, date(2027, 1, 1))]
    plan = make_plan(idx[-1], lots, 0.0, px, None, S, goals=goals, harvest=False)
    assert plan.goals is not None and plan.goals.risk_cap < 1
    assert plan.target.weights is not None
    risky = sum(w for s, w in plan.target.weights.items() if not G.is_goal_safe(s, S))
    assert risky <= plan.goals.risk_cap + 1e-9
    assert any(n.startswith("Goal 'soon'") for n in plan.notes)
    assert any(t.side == "sell" for t in plan.trades)
