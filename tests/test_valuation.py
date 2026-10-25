import numpy as np
import pandas as pd

from pe import valuation as V
from pe.config import load_settings
from pe.data import synthetic_prices
from pe.strategy import build_target

S = load_settings()
CFG = S.strategy["valuation"]


def _fake(n=4200, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2008-01-01", periods=n)
    price = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n))), index=idx)
    pe = pd.Series(18 + 4 * np.sin(np.arange(n) / 400) + rng.normal(0, 0.3, n), index=idx)
    bond = pd.Series(0.07 + 0.01 * np.sin(np.arange(0, n, 21) / 30), index=idx[::21])
    return pd.DataFrame({"pe": pe, "pb": 3.0, "div_yield": 1.2}), bond, price


def test_signals_are_point_in_time():
    val, bond, price = _fake()
    full = V.build_signals(val, bond, price, CFG, 0.065)
    cut = val.index[3000]
    part = V.build_signals(val.loc[:cut], bond.loc[:cut], price.loc[:cut], CFG, 0.065)
    cols = ["pe_pct", "f_pe", "spread_z", "f_spread", "yhat", "f_fcst"]
    a, b = full.loc[:cut - pd.Timedelta(days=1), cols], part.loc[:cut - pd.Timedelta(days=1), cols]
    pd.testing.assert_frame_equal(a.dropna(how="all"), b.dropna(how="all"), check_exact=False, atol=1e-9)


def test_scale_never_below_floor_or_above_one():
    val, bond, price = _fake()
    sig = V.build_signals(val, bond, price, CFG, 0.065)
    for k in ("f_pe", "f_spread", "f_fcst"):
        assert sig[k].between(CFG["floor"] - 1e-9, 1.0).all()


def test_overlay_moves_equity_to_cash():
    px, vix = synthetic_prices(S, start="2022-01-01", end="2024-06-01")
    sig = pd.DataFrame({"f_pe": 0.5, "f_spread": 1.0, "f_fcst": 1.0}, index=pd.bdate_range("2020-01-01", "2024-12-31"))
    S.raw["_valuation_signals"] = sig
    try:
        t = build_target(px, vix, S, "nifty+pe")
        assert abs(t.weights["NIFTYBEES"] - 0.5) < 1e-9 and abs(t.weights["CASH"] - 0.5) < 1e-9
        assert abs(sum(t.weights.values()) - 1) < 1e-9
    finally:
        S.raw.pop("_valuation_signals")


def test_reality_check_flags_noise():
    from pe.forecast_study import reality_check
    rng = np.random.default_rng(0)
    base = np.cumprod(1 + rng.normal(0.001, 0.01, 600))
    curves = {"b": list(base)} | {f"v{i}": list(np.cumprod(1 + rng.normal(0.001, 0.01, 600))) for i in range(7)}
    assert reality_check(curves, "b", n=300)["family_p_best_by_chance"] > 0.05
