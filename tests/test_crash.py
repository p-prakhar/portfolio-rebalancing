import numpy as np
import pandas as pd

from pe import crash, crash_backtest as cb
from pe.backtest import VARIANTS, run_all
from pe.config import Lot, load_settings
from pe.strategy import Target

S = load_settings()


def test_level_hysteresis_steps_down_slowly():
    raw = [0, 3, 0, 0, 0, 0, 0, 0]
    lv = crash.levels(pd.DataFrame({"raw": raw}), exit_days=3)
    assert list(lv) == [0, 3, 3, 3, 2, 2, 2, 1]


def test_bubble_burst_is_flagged_early_and_steady_market_mostly_left_alone():
    px, vix = cb.synthetic_panel(S, "bubble_burst")
    lv = crash.level_series(px, vix, S)["level"]
    burst = px.index[2400]
    assert lv.loc[burst:].iloc[:60].max() >= 2          # flagged within ~3 months of the burst starting
    comp = crash._proxy(px, crash.cfg(S)["proxy"])
    first = lv.loc[burst:][lv.loc[burst:] >= 2].index[0]
    assert comp.loc[first] / comp.loc[burst] - 1 > -0.30    # ...before most of the fall
    px, vix = cb.synthetic_panel(S, "steady")
    quiet = crash.level_series(px, vix, S)["level"].iloc[1000:]
    assert (quiet >= 2).mean() < 0.15                          # a calm market is mostly left alone


def test_guard_cuts_drawdown_in_a_synthetic_burst():
    px, vix = cb.synthetic_panel(S, "bubble_burst")
    px, vix = px.iloc[1700:3000], vix.iloc[1700:3000]
    p0 = float(px["NIFTYBEES"].iloc[420])
    lots = [Lot("NIFTYBEES", 1e6 / p0, px.index[420].date(), p0)]
    variants = [v for v in VARIANTS if v[0] in ("Buy & hold (your current portfolio)", "Buy & hold + crash guard")]
    curves, table, _ = run_all(lots, px, vix, S, px.index[420], None, variants)
    assert table.loc["Buy & hold + crash guard", "max_drawdown"] > table.iloc[0]["max_drawdown"] + 0.2


def test_buy_hold_guard_restores_weights_at_all_clear():
    px, vix = cb.synthetic_panel(S, "steady")
    held = {"NIFTYBEES": 0.7, "CASH": 0.3}
    mem = {}
    up = {"level": 3, "keep": {2: 0.75, 3: 0.25}, "why": ["x", "y"]}
    t = crash.apply_guard(Target(None), up, px, S, held, mem)
    assert abs(t.weights["NIFTYBEES"] - 0.175) < 1e-9 and abs(sum(t.weights.values()) - 1) < 1e-9 and mem["base"] == held
    t = crash.apply_guard(Target(None), {**up, "level": 0}, px, S, {"NIFTYBEES": 0.175, "CASH": 0.825}, mem)
    assert t.weights == held and "base" not in mem


def test_drill_prices_the_exit_with_tax():
    px, vix = cb.synthetic_panel(S, "steady")
    buy = px.index[-400]
    lots = [Lot("NIFTYBEES", 1000.0, buy.date(), float(px["NIFTYBEES"].loc[buy]) * 0.5)]    # bought at half today's-ish price: big gain
    d = crash.drill(lots, 0.0, px, vix, S, {}, None, 3)
    assert d["sold"] > 0.5 * d["nav"] and d["tax"] > 0 and d["cost"] > 0 and d["breakeven_fall"] > 0
    assert "sell NIFTYBEES" in crash.drill_text(d)


def test_episode_finder():
    s = pd.Series([100, 105, 90, 80, 95, 106, 107], index=pd.bdate_range("2020-01-01", periods=7))
    e = cb.drawdown_episodes(s)
    assert len(e) == 1 and abs(e[0]["depth"] - (80 / 105 - 1)) < 1e-9 and e[0]["recovered"] == s.index[5]
