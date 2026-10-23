from datetime import date

import numpy as np
import pandas as pd
import pytest

from pe.config import Lot, load_settings
from pe.data import cash_series
from pe.engine import make_plan
from pe.stopping import ltcg_wait, secretary_cutoff, secretary_decision
from pe.tax import compute_tax, is_long_term, lt_date

S = load_settings()


def test_equity_ltcg_exemption_and_rate():
    r = compute_tax({"eq_lt": 225000}, S)
    assert r.exemption_used == 125000
    assert r.tax == pytest.approx(100000 * 0.125 * 1.04)


def test_stcg_and_loss_setoff_order():
    # ST loss should wipe the slab-rate gain first (30% > 20%)
    r = compute_tax({"eq_st": 100000, "oth_st": 50000, "eq_lt": -40000 + 0, "debt": -50000}, S)
    assert r.taxable["slab"] == 0
    assert r.taxable["eq_st"] == 100000
    # LT loss cannot touch ST gains
    assert r.carry_forward_lt_loss == 40000


def test_holding_periods():
    lot = Lot("X", 1, date(2024, 8, 14), 100)
    assert lt_date(lot, "in_equity", S) == date(2025, 8, 15)
    assert not is_long_term(lot, "in_equity", date(2025, 8, 14), S)
    assert is_long_term(lot, "in_equity", date(2025, 8, 15), S)
    assert lt_date(lot, "foreign", S) == date(2026, 8, 15)
    assert lt_date(lot, "in_debt", S) is None


def test_secretary_rule():
    assert secretary_cutoff(10) == 4
    obs = [100, 101, 99, 100]
    assert secretary_decision(obs, 10, "sell")[0] == "observe"
    assert secretary_decision(obs + [100.5], 10, "sell")[0] == "observe"
    assert secretary_decision(obs + [102], 10, "sell")[0] == "execute"
    assert secretary_decision(obs + [98.5], 10, "buy")[0] == "execute"
    assert secretary_decision([100] * 10, 10, "buy")[0] == "execute"   # last day


def test_ltcg_wait():
    wait, saving, cost, _ = ltcg_wait(gain=200000, value=1000000, days=10, sigma=0.15, st_rate=0.208, lt_rate=0.13)
    assert wait and saving > cost
    wait, *_ = ltcg_wait(gain=5000, value=1000000, days=70, sigma=0.15, st_rate=0.208, lt_rate=0.13)
    assert not wait


def _prices(trend_nifty=0.15, n=600):
    idx = pd.bdate_range(end="2026-10-22", periods=n)
    t = np.arange(n) / 252
    px = pd.DataFrame(index=idx)
    for i, (sym, a) in enumerate(S.assets.items()):
        if sym == "CASH":
            continue
        drift = trend_nifty if sym == "NIFTYBEES" else 0.02 * (i % 5)
        px[sym] = 100 * np.exp(drift * t + 0.01 * np.sin(t * 40 + i))
    px["CASH"] = cash_series(idx, 0.065)
    return px


def test_plan_harvests_ltcg_exemption_in_buy_hold():
    px = _prices()
    p0 = float(px["NIFTYBEES"].loc["2024-08-14":].iloc[0])
    lots = [Lot("NIFTYBEES", 1600000 / p0, date(2024, 8, 14), p0)]
    plan = make_plan(px.index[-1], lots, 0, px, None, S, policy="buy_hold")
    h = [t for t in plan.trades if t.kind == "harvest_gain" and t.side == "sell"]
    assert len(h) == 1
    assert h[0].gains["eq_lt"] == pytest.approx(125000, rel=1e-6)
    assert plan.tax_after == pytest.approx(0, abs=1)
    assert any("same day" in w for w in h[0].why)


def test_plan_every_trade_has_a_why():
    px = _prices(trend_nifty=-0.25)
    p0 = float(px["NIFTYBEES"].loc["2024-08-14":].iloc[0])
    lots = [Lot("NIFTYBEES", 1600000 / p0, date(2024, 8, 14), p0)]
    plan = make_plan(px.index[-1], lots, 0, px, None, S, policy="core_satellite")
    assert plan.trades
    assert all(t.why for t in plan.trades)


def test_equivalent_etfs_share_weight_and_swap_for_harvest():
    px = _prices()
    px["SETFNIF50"] = px["NIFTYBEES"] * 2.0
    p0 = float(px["NIFTYBEES"].loc["2024-08-14":].iloc[0])
    lots = [Lot("NIFTYBEES", 500000 / p0, date(2024, 8, 14), p0),
            Lot("SETFNIF50", 500000 / (2 * p0), date(2024, 8, 14), 2 * p0)]
    plan = make_plan(px.index[-1], lots, 0, px, None, S, policy="core_satellite")
    # never sell one Nifty ETF to buy the other
    sells = {t.symbol for t in plan.trades if t.side == "sell" and t.kind == "rebalance"}
    buys = {t.symbol for t in plan.trades if t.side == "buy" and t.kind == "rebalance"}
    assert not ({"NIFTYBEES", "SETFNIF50"} & sells and {"NIFTYBEES", "SETFNIF50"} & buys)
    hb = make_plan(px.index[-1], lots, 0, px, None, S, policy="buy_hold")
    h = [t for t in hb.trades if t.kind == "harvest_gain" and t.side == "sell"][0]
    partner = "SETFNIF50" if h.symbol == "NIFTYBEES" else "NIFTYBEES"
    assert any(partner in w for w in h.why)


def test_technical_analysis_trend_and_stop():
    from pe.technical import analyse
    idx = pd.bdate_range(end="2026-10-22", periods=400)
    up = pd.Series(np.linspace(100, 200, 400), index=idx)
    r = analyse("UP", up)
    assert r.verdict in ("uptrend", "strong uptrend") and not r.stop_breached and r.why
    crash = pd.Series(np.r_[np.linspace(100, 200, 380), np.linspace(200, 120, 20)], index=idx)
    r = analyse("CRASH", crash)
    assert r.stop_breached and r.score < analyse("UP", up).score


def test_register_assets_for_custom_holdings(tmp_path):
    from pe.config import load_holdings, register_assets
    f = tmp_path / "h.yaml"
    f.write_text("lots:\n  - {symbol: RELIANCE, qty: 10, buy_date: '2025-01-15', price: 1250}\n"
                 "  - {symbol: AAPL, qty: 5, buy_date: '2025-05-01', price: 17892, currency: USD}\n")
    s = load_settings()
    added = register_assets(s, load_holdings(f))
    assert set(added) == {"RELIANCE", "AAPL"}
    assert s.assets["RELIANCE"].ticker == "RELIANCE.NS" and s.assets["RELIANCE"].venue == "nse_stock"
    assert s.assets["AAPL"].tax_class == "foreign" and s.assets["AAPL"].ticker == "AAPL"


def test_tradebook_fifo(tmp_path):
    from pe.importer import lots_from_tradebook
    f = tmp_path / "tb.csv"
    f.write_text("symbol,trade_date,trade_type,quantity,price\nX,2024-01-01,buy,10,100\nX,2024-06-01,buy,10,120\n"
                 "X,2024-09-01,sell,15,130\n")
    lots, warns = lots_from_tradebook(str(f))
    assert lots == [{"symbol": "X", "qty": 5.0, "buy_date": "2024-06-01", "price": 120.0}] and not warns


def test_irr_and_generic_asset_framework():
    from pe.assetclasses import evaluate
    from pe.realassets import irr
    assert irr([-100, 0, 121]) == pytest.approx(0.10, abs=1e-6)
    scen = {"equity": 0.10, "inr_vs_usd": 0.0}
    fd = {"key": "fd", "name": "FD", "group": "Debt", "income_yield": 0.07, "income_tax": "slab", "income_paid": False, "gains_tax": "exempt"}
    r = evaluate(fd, scen, "base", 5, 100000, slab=0.30)
    assert r.irr == pytest.approx(0.07 * (1 - 0.312), abs=1e-4)     # accrual taxation every year
    ppf = {"key": "ppf", "name": "PPF", "group": "x", "income_yield": 0.071, "income_tax": "exempt", "income_paid": False,
           "gains_tax": "exempt", "cap_inr_per_year": 150000}
    r = evaluate(ppf, scen, "base", 10, 500000, slab=0.30)
    assert r.invested == 150000 and r.irr == pytest.approx(0.071, abs=1e-4)
    eq = {"key": "e", "name": "E", "group": "x", "growth": "equity", "gains_tax": "equity"}
    r = evaluate(eq, scen, "base", 10, 100000, slab=0.30)
    assert 0.088 < r.irr < 0.10                                      # 12.5% LTCG + cess at exit


def test_real_asset_frameworks_run_and_warn():
    from pe import realassets
    cfg = realassets.load()
    d = realassets.dubai_flat(cfg, 0.03, 0.025)
    assert d.warnings and "LRS" in d.warnings[0]
    k = realassets.farmland(cfg, "karnataka", 0.07)
    assert k.breakdown["exit_tax"] == 0                               # rural land is not a capital asset
    c = realassets.farmland(cfg, "chhattisgarh", 0.07)
    assert c.warnings
    coin, etf = realassets.physical_gold(cfg, "coin", 0.08), realassets.gold_etf(cfg, 0.08)
    assert etf.irr > coin.irr                                        # making charges, GST and locker cost money


def test_gold_page_parser():
    from pe.goldprice import parse_rates
    html = ('<div class="card"><span>24K</span><small>99.9% pure</small><p>per 10g</p><b>&#8377;1,42,128</b>'
            '<i>&#8377;14,213/g</i></div><div><span>22K</span><p>per 10g</p><b>₹1,30,284</b><i>₹13,028/g</i></div>')
    assert parse_rates(html) == {"24K": 14213.0, "22K": 13028.0}
