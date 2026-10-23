import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pe.data import drop_bad_prints
from pe.etrade import lots_from_etrade
from pe.profile import OtherAsset, Profile, guardrails, load_other, merge_lots, save_other
from pe import site


def test_bad_print_removed_but_real_step_kept():
    idx = pd.bdate_range("2020-01-01", periods=30)
    s = pd.Series(100.0, index=idx)
    s.iloc[10] = 10.0                       # one-day glitch
    s.iloc[20:] = 50.0                      # lasting step (a real crash/split)
    out = drop_bad_prints(pd.DataFrame({"X": s}))["X"]
    assert np.isnan(out.iloc[10])
    assert out.iloc[25] == 50.0 and not np.isnan(out.iloc[20])


def test_etrade_vests_to_lots_and_sold_removed(tmp_path):
    f = tmp_path / "bh.csv"
    pd.DataFrame({"Record Type": ["Grant", "Vest Schedule", "Vest Schedule"],
                  "Vest Date": ["01/15/2023", "01/15/2023", "07/15/2023"],
                  "Vested Qty.": [0, 10, 10], "Vest Date FMV": [0, "$100.00", "$120.00"]}).to_csv(f, index=False)
    lots, meta, warns = lots_from_etrade(str(f), "acme", lambda d: 80.0, sold_qty=4)
    assert [l["qty"] for l in lots] == [6, 10]              # oldest sold first
    assert lots[0]["price"] == 8000.0 and lots[1]["price"] == 9600.0
    assert meta["ACME"]["currency"] == "USD" and meta["ACME"]["tax_class"] == "foreign"


def test_merge_lots_replaces_symbol_and_keeps_rest(tmp_path):
    p = tmp_path / "h.yaml"
    merge_lots([{"symbol": "A", "qty": 1, "buy_date": "2024-01-01", "price": 10}, {"symbol": "B", "qty": 2, "buy_date": "2024-01-01", "price": 5}], path=p)
    merge_lots([{"symbol": "A", "qty": 3, "buy_date": "2024-02-01", "price": 11}], path=p)
    import yaml
    lots = yaml.safe_load(p.read_text())["lots"]
    assert sorted((l["symbol"], l["qty"]) for l in lots) == [("A", 3), ("B", 2)]


def test_equity_cap_and_guardrails(tmp_path):
    assert Profile(age=30, risk="moderate").equity_cap() == 0.80
    assert Profile(age=70, risk="conservative").equity_cap() == 0.25
    g = guardrails(Profile(age=60, risk="moderate"), [OtherAsset("fixed_deposit", "FD", 100)], 900, 900, 400)
    assert any(x["level"] == "warn" and "Equity share" in x["title"] for x in g)       # 90% equity vs 50% guide
    assert any(x["level"] == "warn" and "Employer" in x["title"] for x in g)           # 40% in one stock
    p = tmp_path / "o.yaml"
    save_other([OtherAsset("epf", "EPF", 5)], p)
    assert load_other(p)[0].value_inr == 5


def test_static_mix_and_core_xs_targets_sum_to_one():
    from pe.config import load_settings
    from pe.data import synthetic_prices
    from pe.strategy import build_target
    s = load_settings()
    px, vix = synthetic_prices(s)
    for pol in ("static_mix", "core_xs", "rp_blend"):
        t = build_target(px, vix, s, pol)
        assert abs(sum(t.weights.values()) - 1) < 1e-6, pol


def test_site_builds_valid_json(tmp_path):
    from pe.backtest import run_all
    from pe.config import load_holdings, load_settings, register_assets, resolve_amount_lots
    from pe.data import synthetic_prices
    from pe.engine import make_plan
    s = load_settings()
    h = load_holdings()
    register_assets(s, h)
    px, vix = synthetic_prices(s)
    h = resolve_amount_lots(h, px)
    plan = make_plan(px.index[-1], h.lots, 0, px, vix, s, {})
    start = px.index[-1] - pd.Timedelta(days=200)
    c, t, logs = run_all(h.lots, px, vix, s, start, None, variants=__import__("pe.backtest", fromlist=["x"]).VARIANTS[:3])
    data = site.build(plan, s, [], px, (c, t, logs, start), None, [], None, "synthetic", None)
    out = site.render(data, tmp_path / "index.html")
    blob = out.read_text().split('type="application/json">')[1].split("</script>")[0]
    parsed = json.loads(blob)
    assert parsed["verdict"]["call"] in ("HOLD", "REBALANCE") and parsed["steps"]
