from datetime import date

import numpy as np
import pandas as pd

from pe.forward import forward_lines, holdings_xirr
from pe.stats import block_bootstrap, bootstrap_excess, deflated_sharpe, monte_carlo, xirr
from pe.validate import significance, verdicts


def test_xirr_matches_simple_compounding():
    r = xirr([(date(2022, 1, 1), -100.0), (date(2024, 1, 1), 121.0)])
    assert abs(r - 0.10) < 0.002
    assert xirr([(date(2022, 1, 1), -100.0)]) is None


def test_bootstrap_interval_brackets_a_real_edge_and_excludes_luck():
    rng = np.random.default_rng(1)
    n = 2500
    base = np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    edge = base * np.cumprod(1 + rng.normal(0.0008, 0.002, n))       # steady extra return
    luck = base * np.cumprod(1 + rng.normal(0.0, 0.004, n))          # no edge, same noise scale as a real strategy
    e = bootstrap_excess(edge, base)
    assert e["lo"] > 0
    l = bootstrap_excess(luck, base)
    assert l["lo"] < 0 < l["hi"]


def test_block_bootstrap_shape():
    out = block_bootstrap(np.arange(100.0), 5, 10, np.random.default_rng(0))
    assert out.shape == (5, 100)


def test_deflated_sharpe_falls_with_more_trials():
    rng = np.random.default_rng(2)
    r = rng.normal(0.0004, 0.01, 2500)
    few = deflated_sharpe(r, [0.01, 0.02])
    many = deflated_sharpe(r, list(np.random.default_rng(3).normal(0.02, 0.03, 40)))
    assert 0 <= many <= few <= 1


def test_monte_carlo_ranges_are_ordered():
    r = np.random.default_rng(4).normal(0.0004, 0.01, 1500)
    mc = monte_carlo(r, 100.0, years=2)
    assert mc["end_p10"] < mc["end_p50"] < mc["end_p90"]
    assert -1 < mc["mdd_p10"] <= mc["mdd_p50"] <= 0
    assert monte_carlo(r[:20], 100.0) == {}


def test_significance_withholds_robust_when_range_spans_zero():
    rng = np.random.default_rng(5)
    n = 1500
    idx = pd.bdate_range("2020-01-01", periods=n)
    base = np.cumprod(1 + rng.normal(0.0004, 0.01, n))
    curves = pd.DataFrame({"base": base, "luck": base * np.cumprod(1 + rng.normal(0, 0.004, n)),
                           "other": base * np.cumprod(1 + rng.normal(0, 0.004, n))}, index=idx)
    st = significance(curves, "base")
    assert st["_trials"] == 2 and st["luck"]["lo"] < 0
    win = {"windows": 8, "median_excess": 0.03, "worst_excess": 0.0, "win_rate": 1.0, "median_dd_improvement": 0.0,
           "early_median_excess": 0.02, "late_median_excess": 0.02}
    res = {"windows": {"base": win, "luck": win}, "stats": {"luck": st["luck"]}}
    assert verdicts(res, "base")["luck"] != "robust edge"


def test_holdings_xirr_and_forward_lines():
    pos = pd.DataFrame({"symbol": ["A", "A"], "buy_date": [date(2023, 1, 2), date(2024, 1, 2)],
                        "cost": [100.0, 100.0], "value": [130.0, 110.0]})
    assert holdings_xirr(pos, date(2025, 1, 2)) > 0
    px = pd.DataFrame({"A": 100 * np.cumprod(1 + np.random.default_rng(6).normal(0.0004, 0.01, 800))},
                      index=pd.bdate_range("2022-01-03", periods=800))
    txt = "\n".join(forward_lines(pos, px))
    assert "next 3 years" in txt and "Chance of ending below" in txt


def test_fifo_is_default_and_sells_oldest_first():
    import copy
    from pe.config import Lot, load_settings
    from pe.engine import _oldest_rows, _pick_lots
    s = load_settings()
    assert s.tax["lot_method"] == "fifo"
    old, new = Lot("NIFTYBEES", 10, date(2023, 1, 2), 50.0), Lot("NIFTYBEES", 10, date(2024, 6, 3), 120.0)
    got = _pick_lots([new, old], 10, 80.0, "in_equity", date(2025, 1, 2), s)
    assert [l.buy_date for l, _ in got] == [date(2023, 1, 2)]           # FIFO takes the oldest, though the newer lot is the loss
    sp = copy.deepcopy(s)
    sp.raw["tax"]["lot_method"] = "specific"
    got = _pick_lots([new, old], 10, 80.0, "in_equity", date(2025, 1, 2), sp)
    assert [l.buy_date for l, _ in got] == [date(2024, 6, 3)]           # specific-lot mode picks the loss first
    pos = pd.DataFrame({"symbol": ["A", "A", "B"], "buy_date": [date(2024, 5, 1), date(2023, 5, 1), date(2024, 1, 1)]})
    assert sorted(_oldest_rows(pos)) == [1, 2]


def test_significance_centres_on_after_tax_return():
    rng = np.random.default_rng(8)
    n = 1500
    idx = pd.bdate_range("2020-01-01", periods=n)
    base = np.cumprod(1 + rng.normal(0.0004, 0.01, n))
    strat = base * np.cumprod(1 + rng.normal(-0.0001, 0.003, n))     # pre-tax curve lags (tax paid along the way)
    curves = pd.DataFrame({"base": base, "s": strat, "t": strat}, index=idx)
    full = {"base": {"cagr_after_tax": 0.10}, "s": {"cagr_after_tax": 0.105}, "t": {"cagr_after_tax": 0.10}}
    st = significance(curves, "base", full, 6.0)
    assert abs(st["s"]["excess"] - (np.log(1.105) - np.log(1.10))) < 1e-9
    assert st["s"]["lo"] < st["s"]["excess"] < st["s"]["hi"]


def test_deflated_sharpe_ignores_one_extreme_trial():
    r = np.random.default_rng(9).normal(0.0004, 0.01, 2500)
    base_trials = list(np.random.default_rng(10).normal(0.0, 0.02, 12))
    assert deflated_sharpe(r, base_trials + [5.0]) == deflated_sharpe(r, base_trials + [0.5])
