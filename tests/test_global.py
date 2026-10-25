"""Global-market additions: UCITS costs, dividend drag by fund domicile, universe sanity."""
import pandas as pd
import pytest

from pe.config import load_settings
from pe.costs import cost_breakdown
from pe.global_markets import apply_dividend_drag, dividend_drag


def test_ucits_cost_has_floor_and_no_stamp_duty():
    s = load_settings()
    a = s.assets["CSPX"]
    small = cost_breakdown(s, a, "buy", 100_000, 5_000, 85.0)   # about USD 1,176: floor applies
    assert small["commission"] == pytest.approx(3.0 * 85.0)
    assert not any("stamp" in k.lower() for k in small)
    big = cost_breakdown(s, a, "sell", 5_000_000, 5_000, 85.0)
    assert big["commission"] == pytest.approx(5_000_000 * 0.0005)


def test_dividend_drag_by_domicile():
    s = load_settings()
    india = 0.30 * 1.04
    assert dividend_drag(s, s.assets["SPY"]) == pytest.approx(0.013 * india)   # credit capped at Indian tax, so slab wins
    assert dividend_drag(s, s.assets["CSPX"]) == 0.0                           # accumulating Irish fund: already in NAV
    assert dividend_drag(s, s.assets["NIFTYBEES"]) == 0.0


def test_dividend_drag_series_compounds():
    s = load_settings()
    idx = pd.date_range("2024-01-01", periods=3, freq="365D")
    out = apply_dividend_drag(s, s.assets["SPY"], pd.Series([100.0, 100.0, 100.0], index=idx))
    assert out.iloc[0] == 100.0 and out.iloc[2] < out.iloc[1] < 100.0


def test_every_foreign_asset_has_domicile_and_known_venue():
    s = load_settings()
    for sym, a in s.assets.items():
        assert a.venue in s["costs"], sym
        if a.currency == "USD":
            assert a.tax_class == "foreign" and a.domicile in ("US", "IE"), sym
        if a.domicile == "IE":
            assert a.venue == "ibkr_ucits", sym
