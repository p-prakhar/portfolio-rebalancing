"""Invariants the backtest must always satisfy, and guards against a data source that loses an instrument's history.

Synthetic prices only: no network, no real holdings.
"""
import copy
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pe import backtest
from pe.backtest import run_variant
from pe.config import Holdings, Lot, load_settings, resolve_amount_lots
from pe.data import backfill_equivalents, build_prices, splice_history, synthetic_prices

POLICIES = ("dual_momentum", "xs_momentum", "core_xs", "core_satellite", "trend_vol", "risk_parity", "daa", "static_mix", "custom")


def _setup():
    s = load_settings()
    px, vix = synthetic_prices(s)
    start = px.index[300]
    p0 = float(px.loc[start, "NIFTYBEES"])
    return s, px, vix, start, [Lot("NIFTYBEES", 1_000_000 / p0, start.date(), p0)]


def test_backtest_creates_no_money(monkeypatch):
    """Each day: value today = value yesterday + price moves on what was held - costs - tax. Nothing else may change it."""
    s, px, vix, start, lots = _setup()
    val = px.ffill()
    snaps = []
    real = backtest._nav

    def spy(book, row):
        snaps.append(([(l.symbol, l.qty) for l in book.lots], book.cash, book.costs_paid, book.taxes_paid, row.name))
        return real(book, row)

    monkeypatch.setattr(backtest, "_nav", spy)
    for policy in POLICIES:
        snaps.clear()
        nav, book, _, _ = run_variant(policy, policy, "immediate", True, lots, px, vix, s, start)
        eod = {}
        for sn in snaps:            # the journal also values the book mid-day; the last snapshot of a day is the close
            eod[sn[4]] = sn
        days = list(nav.index)
        assert list(eod) == days
        for a, b in zip(days[:-1], days[1:]):
            held, _, cost0, tax0, _ = eod[a]
            _, _, cost1, tax1, _ = eod[b]
            pnl = sum(q * (val.loc[b, sym] - val.loc[a, sym]) for sym, q in held)
            assert nav[b] == pytest.approx(nav[a] + pnl - (cost1 - cost0) - (tax1 - tax0), abs=0.01), (policy, b)
        assert book.costs_paid >= 0 and book.taxes_paid >= 0


def test_backtest_decisions_do_not_see_the_future():
    """Cutting the price history off at a date must not change any trade made before that date."""
    s, px, vix, start, lots = _setup()
    cut = px.index[650]
    for policy in POLICIES + ("core_xs+guard",):
        _, full, _, _ = run_variant(policy, policy, "immediate", True, lots, px, vix, s, start)
        _, short, _, _ = run_variant(policy, policy, "immediate", True, lots, px.loc[:cut], vix.loc[:cut], s, start)
        before = lambda book: [e for e in book.log if pd.Timestamp(e[0]) < cut and e[1] in ("BUY", "SELL")]
        assert before(full) == before(short), policy


def test_orders_fill_after_the_signal_day_at_that_days_close():
    s, px, vix, start, lots = _setup()
    _, book, _, _ = run_variant("dual", "xs_momentum", "immediate", False, lots, px, vix, s, start)
    plans = {e[0] for e in book.log if e[1] == "PLAN"}
    fills = [e for e in book.log if e[1] in ("BUY", "SELL")]
    assert fills
    days = [d.date() for d in px.index]
    for day, _side, text in fills:
        assert day not in plans                                  # never on the day the signal was read
        assert days[days.index(day) - 1] in plans                # the next trading day
        sym, price = text.split()[0], float(text.split("@ ")[1].split()[0].replace(",", ""))
        assert price == pytest.approx(float(px.loc[pd.Timestamp(day), sym]), abs=0.006)


def test_missing_price_carries_last_value_and_blocks_the_fill():
    s, px, vix, start, lots = _setup()
    px = px.copy()
    gap = px.index[(px.index > start)][40:80]
    px.loc[gap, "NIFTYBEES"] = np.nan
    nav, book, _, _ = run_variant("bh", "buy_hold", "immediate", False, lots, px, vix, s, start)
    before = px.index[px.index.get_loc(gap[0]) - 1]
    assert nav[gap[5]] == pytest.approx(nav[before])             # held at the last known price, not reset to cost
    assert nav.notna().all()
    nav2, book2, _, _ = run_variant("dm", "dual_momentum", "immediate", False, lots, px, vix, s, start)
    assert nav2.notna().all() and np.isfinite(book2.cash)
    assert not any(pd.Timestamp(e[0]) in gap and "NIFTYBEES" in e[2] for e in book2.log if e[1] in ("BUY", "SELL"))


def test_download_that_lost_history_keeps_the_cached_rows():
    idx = pd.bdate_range("2023-01-02", periods=400)
    old = pd.Series(np.linspace(100, 180, 400), index=idx)
    stub = old.iloc[-30:] * 0.5                                  # re-adjusted (e.g. a 2:1 split) and truncated
    merged, spliced = splice_history(old, stub)
    assert spliced and len(merged) == 400 and merged.index.is_unique
    assert merged.iloc[-1] == stub.iloc[-1]
    assert merged.pct_change().abs().max() < 0.02                # no step where the two meet
    same, spliced = splice_history(old.iloc[:-5], old)           # a normal refresh just replaces
    assert not spliced and same.equals(old)


def test_equivalent_fund_borrows_the_primarys_history():
    s = load_settings()
    px, _ = synthetic_prices(s)
    prices = {"NIFTYBEES": px["NIFTYBEES"], "SETFNIF50": (px["NIFTYBEES"] * 0.9).where(px.index >= px.index[600])}
    assert backfill_equivalents(s, prices) == ["SETFNIF50"]
    assert prices["SETFNIF50"].notna().all()
    assert (prices["SETFNIF50"] / prices["NIFTYBEES"]).round(6).nunique() == 1
    # a feed that stops (Yahoo's SETFNIF50 did): the tail follows the primary instead of sitting at a stale price
    dead = (px["NIFTYBEES"] * 0.9).where(px.index <= px.index[-30])
    prices = {"NIFTYBEES": px["NIFTYBEES"], "SETFNIF50": dead}
    assert backfill_equivalents(s, prices) == ["SETFNIF50"]
    assert prices["SETFNIF50"].iloc[-1] == pytest.approx(px["NIFTYBEES"].iloc[-1] * 0.9)
    # end to end through build_prices, keyed by ticker
    closes = pd.DataFrame({"NIFTYBEES.NS": px["NIFTYBEES"], "SETFNIF50.NS": prices["NIFTYBEES"].where(px.index >= px.index[600]) * 0.9,
                           "INR=X": 85.0})
    out, _ = build_prices(s, closes)
    assert out["SETFNIF50"].notna().all()


def test_amount_lot_is_not_priced_long_after_its_purchase():
    idx = pd.bdate_range("2024-01-01", periods=500)
    px = pd.DataFrame({"X": pd.Series(np.linspace(100, 200, 500), index=idx).where(idx >= idx[300])})
    h = Holdings(lots=[], pending_amounts=[{"symbol": "X", "buy_date": idx[10].date(), "amount_inr": 100000.0}])
    with pytest.raises(ValueError, match="price history only starts"):
        resolve_amount_lots(copy.deepcopy(h), px)
    h.pending_amounts[0]["buy_date"] = (idx[300] - pd.Timedelta(days=3)).date()      # a weekend or holiday gap is fine
    assert resolve_amount_lots(h, px).lots[0].price == pytest.approx(float(px["X"].loc[idx[300]]))
