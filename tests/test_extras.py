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
    for k in ("regime_filter", "rebalance_parameters", "execution_blotter", "cross_sectional_universe"):
        assert parsed[k], k
    assert parsed["regime_filter"]["state"] in ("RISK_ON", "CASH_PRESERVATION")
    w = [r["cur_value"] for r in parsed["execution_blotter"]]
    assert abs(sum(w) - parsed["nav"]) < 2 + 0.01 * parsed["nav"]         # blotter covers the portfolio
    zs = [r["z"] for r in parsed["cross_sectional_universe"] if r["z"] is not None]
    assert abs(np.mean(zs)) < 1e-6


def test_silver_parse_and_compare_math():
    from pe.goldprice import parse_silver
    assert parse_silver("<b>Silver</b> ₹1,95,969 / 1kg +0.1%") == 195969.0
    assert parse_silver("nothing here") is None
    from pe.config import load_settings
    from pe import universe_compare as uc
    s = load_settings()
    idx = pd.bdate_range("2014-01-01", periods=2800)
    px = pd.DataFrame({"NIFTYBEES": 100 * 1.0004 ** np.arange(2800), "GOLDBEES": 50 * 1.0003 ** np.arange(2800),
                       "SMH": 10 * 1.0006 ** np.arange(2800)}, index=idx)
    rows = {r["symbol"]: r for r in uc.compare(px, s, 85.0)}
    assert set(rows) == {"NIFTYBEES", "GOLDBEES", "SMH"}
    r = rows["SMH"]
    assert r["r5"] > rows["NIFTYBEES"]["r5"] > rows["GOLDBEES"]["r5"]
    assert r["after_tax_5y"] < r["r5"]          # costs and tax always take something
    assert "Semiconductors" in uc.report(list(rows.values()))


def test_fd_values_and_penalty():
    from pe import fd
    f = fd.FD("sbi", 100000, 0.07, date(2025, 4, 1), 12)
    assert abs(f.value_on(f.maturity) - 100000 * (1 + 0.07 / 4) ** 4) < 50
    assert f.break_value(date(2025, 10, 1)) < f.value_on(date(2025, 10, 1))
    assert fd.FD("sbi", 900000, 0.07, date(2025, 4, 1), 12).penalty_rate() == 0.01
    s = fd.summary([f], 0.30, today=date(2025, 10, 1))[0]
    assert s["after_tax_yield"] < s["effective_yield"] and s["tds_likely"] is False


def test_mf_lots_from_cas_fifo_and_tax_class(monkeypatch):
    from pe import mf
    monkeypatch.setattr(mf, "scheme_meta", lambda code: {"scheme_category": "Equity Scheme - Flexi Cap Fund"})
    cas = {"folios": [{"schemes": [{"scheme": "X Flexi Cap Fund - Regular Plan - Growth", "amfi": "123", "close": 15,
            "transactions": [{"date": date(2022, 1, 5), "units": 10, "nav": 50, "amount": 500},
                             {"date": date(2023, 1, 5), "units": 10, "nav": 60, "amount": 600},
                             {"date": date(2024, 1, 5), "units": -5, "nav": 70, "amount": -350}]}]}]}
    lots, meta, warns = mf.lots_from_cas(cas)
    assert [(l["qty"], l["buy_date"]) for l in lots] == [(5, "2022-01-05"), (10, "2023-01-05")]
    assert meta["MF123"]["tax_class"] == "in_equity" and not warns
    assert mf.tax_class("Debt Scheme - Corporate Bond Fund", date(2024, 1, 1)) == "in_debt"
    assert mf.tax_class("Other Scheme - FoF Overseas", date(2025, 6, 1)) == "mf_other"
    assert mf.is_regular("X Fund - Regular Plan - Growth") and not mf.is_regular("X Fund - Direct Plan - Growth")


def test_income_sets_slab():
    from pe.config import load_settings
    from pe.profile import Profile, apply_tax_profile, marginal_slab
    p = Profile(gross_salary_inr=3_000_000, tax_regime="new")
    assert marginal_slab(p)[0] == 0.30
    assert marginal_slab(Profile(gross_salary_inr=1_500_000))[0] == 0.15
    s = load_settings()
    apply_tax_profile(s, Profile(gross_salary_inr=900_000))
    assert s.tax["slab_rate"] == 0.10
    assert apply_tax_profile(s, Profile()) is None
