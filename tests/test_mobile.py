"""The Android app's JSON bridge (pe/mobile.py), run the way the phone runs it: a fresh interpreter with PE_HOME set.

Synthetic prices only (demo=True), made-up holdings, no network.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SHIPPED = ("settings.yaml", "asset_classes.yaml", "real_assets.yaml", "corporate_actions.yaml", "holdings.example.yaml")


@pytest.fixture()
def home(tmp_path):
    (tmp_path / "config").mkdir()
    for n in SHIPPED:
        shutil.copyfile(REPO / "config" / n, tmp_path / "config" / n)
    return tmp_path


def call(home, code: str):
    """Run `code` (which must assign `out`, the JSON string from a bridge call) in a fresh interpreter."""
    env = {**os.environ, "PE_HOME": str(home), "PE_PRICE_SOURCE": "lite", "PYTHONPATH": str(REPO)}
    script = "import json\nfrom pe import mobile as M\n" + textwrap.dedent(code) + "\nprint('\\n@@' + out)"
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, cwd=str(home))
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.rsplit("\n@@", 1)[1])


def ok(res):
    assert res["ok"], res
    return res["data"]


def test_starter_then_check_and_trade(home):
    st = ok(call(home, "out = M.init()"))
    assert not st["has_holdings"] and st["settings"]["policy"]
    res = call(home, "out = M.check(False, True)")
    assert not res["ok"] and res["kind"] == "no_holdings"
    st = ok(call(home, "out = M.apply_starter(json.dumps({'id': 'india_mix', 'amount_inr': 1000000, 'buy_date': '2024-08-14'}))"))
    assert st["has_holdings"] and st["symbols"] == ["GOLDBEES", "JUNIORBEES", "NIFTYBEES"]
    d = ok(call(home, "out = M.check(False, True)"))
    assert d["verdict"]["call"] in ("HOLD", "REBALANCE")
    assert abs(d["nav"] - sum(r["cur_value"] for r in d["execution_blotter"])) < 0.02 * d["nav"]
    assert all("python main.py" not in s["detail"] for s in d["steps"])
    assert d["demo"] is True and d["backtest"] is None


def test_manual_lots_cash_and_fifo_sale(home):
    ok(call(home, "out = M.init()"))
    h = ok(call(home, "out = M.add_lot(json.dumps({'symbol': 'tcs-eq', 'buy_date': '2023-01-10', 'qty': 10, 'price': 3000}))"))
    assert h["lots"][0]["symbol"] == "TCS"
    ok(call(home, "out = M.add_lot(json.dumps({'symbol': 'TCS', 'buy_date': '2025-12-01', 'qty': 5, 'price': 4000}))"))
    h = ok(call(home, "out = M.set_account(json.dumps({'cash_inr': 20000}))"))
    assert h["cash_inr"] == 20000
    bad = call(home, "out = M.add_lot(json.dumps({'symbol': 'TCS', 'buy_date': '2024-01-01', 'qty': -1, 'price': 5}))")
    assert not bad["ok"] and bad["kind"] == "invalid"
    over = call(home, "out = M.apply_trade(json.dumps({'symbol': 'TCS', 'side': 'sell', 'qty': 99, 'price': 4100, 'date': '2026-01-15'}))")
    assert not over["ok"]
    h = ok(call(home, "out = M.apply_trade(json.dumps({'symbol': 'TCS', 'side': 'sell', 'qty': 12, 'price': 4100, 'date': '2026-01-15'}))"))
    # oldest lot (10) goes first as a long-term gain, then 2 of the young lot as short term
    assert [(l["qty"], l["buy_date"]) for l in h["lots"]] == [(3.0, "2025-12-01")]
    assert h["realised_this_fy"]["equity_ltcg"] == 10 * 1100 and h["realised_this_fy"]["equity_stcg"] == 2 * 100
    assert h["cash_inr"] == 20000 + 12 * 4100
    h = ok(call(home, "out = M.delete_lot(0)"))
    assert h["lots"] == []


def test_import_tradebook_snapshot_text_and_yaml(home, tmp_path):
    ok(call(home, "out = M.init()"))
    tb = tmp_path / "trades.csv"
    tb.write_text("symbol,trade_date,trade_type,quantity,price,trade_id\n"
                  "NIFTYBEES,2024-08-14,buy,100,250,1\nNIFTYBEES,2024-09-02,buy,50,260,2\nNIFTYBEES,2025-01-06,sell,120,270,3\n"
                  "TCS-EQ,2024-09-16,buy,4,4000,4\n")
    pv = ok(call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(tb)!r}, {str(tb)!r}]}}))"))
    assert pv["kind"] == "tradebook" and pv["needs"] == []
    rows = {r["symbol"]: r for r in pv["by_symbol"]}
    assert rows["NIFTYBEES"]["qty"] == 30 and rows["TCS"]["qty"] == 4      # the same file twice does not double count
    st = ok(call(home, "out = M.import_commit()"))
    assert st["lots"] == 2
    # a Groww-style order sheet: title rows above the header, day-first dates, value instead of price
    gw = tmp_path / "orders.csv"
    gw.write_text("Order history,,,,,\n,,,,,\nStock name,Symbol,Type,Quantity,Value,Execution date and time,Order status\n"
                  "Example Co,GOLDBEES,BUY,10,600,25-08-2024 10:15 AM,Executed\nExample Co,GOLDBEES,BUY,10,700,26-08-2024 10:15 AM,Cancelled\n")
    pv = ok(call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(gw)!r}]}}))"))
    assert pv["kind"] == "tradebook" and pv["by_symbol"][0]["qty"] == 10 and pv["by_symbol"][0]["first"] == "2024-08-25"
    ok(call(home, "out = M.import_commit()"))
    # a holdings list has no dates: the bridge asks for one
    sn = tmp_path / "holdings.csv"
    sn.write_text("Instrument,Qty.,Avg. cost,LTP\nJUNIORBEES,20,700.5,720\nTCS,0,0,4000\n")
    pv = ok(call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(sn)!r}]}}))"))
    assert pv["kind"] == "snapshot" and pv["needs"] == ["approx_date"]
    pv = ok(call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(sn)!r}], 'approx_date': '2024-01-05'}}))"))
    assert pv["lots"] == 1 and pv["by_symbol"][0]["cost"] == 20 * 700.5
    st = ok(call(home, "out = M.import_commit()"))
    assert st["symbols"] == ["GOLDBEES", "JUNIORBEES", "NIFTYBEES", "TCS"]
    pv = ok(call(home, "out = M.import_preview(json.dumps({'text': 'BANKBEES 10 @ 500 2024-03-01\\nITBEES 2 lakh 01/04/2024\\n???'}))"))
    assert pv["lots"] == 2 and len(pv["warnings"]) == 1
    st = ok(call(home, "out = M.import_commit()"))
    assert st["lots"] == 6
    d = ok(call(home, "out = M.check(False, True)"))
    assert {r["symbol"] for r in d["execution_blotter"]} >= {"BANKBEES", "ITBEES", "TCS"}
    # backup, wipe, restore
    z = tmp_path / "backup.zip"
    ok(call(home, f"out = M.export_backup({str(z)!r})"))
    assert not ok(call(home, "out = M.clear_holdings()"))["has_holdings"]
    pv = ok(call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(z)!r}]}}))"))
    assert pv["kind"] == "backup" and "holdings.yaml" in pv["restore_files"]
    assert ok(call(home, "out = M.import_commit()"))["lots"] == 6
    unknown = call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(REPO / 'requirements.txt')!r}]}}))")
    assert not unknown["ok"] and unknown["kind"] == "unknown_file"


def test_profile_other_assets_deposits_settings_and_reports(home):
    ok(call(home, "out = M.init()"))
    p = ok(call(home, "out = M.save_profile(json.dumps({'age': 35, 'risk': 'aggressive', 'monthly_expenses_inr': 50000, 'gross_salary_inr': 3000000}))"))
    assert p["exists"] and p["profile"]["age"] == 35 and abs(p["equity_cap"] - 0.90) < 1e-9 and "30%" in p["tax_note"]
    o = ok(call(home, "out = M.save_other(json.dumps({'kind': 'epf', 'name': 'EPF', 'value_inr': 400000}))"))
    assert o["items"][0]["cls"] == "debt" and len(o["kinds"]) > 5
    assert ok(call(home, "out = M.save_other(json.dumps({'index': 0, 'delete': True}))"))["items"] == []
    f = ok(call(home, "out = M.save_fd(json.dumps({'bank': 'sbi', 'principal': 200000, 'rate': 7.25, 'start': '2025-06-01', 'months': 24}))"))
    assert f["items"][0]["maturity"] == "2027-06-01" and f["items"][0]["after_tax_yield"] < f["items"][0]["effective_yield"]
    assert not call(home, "out = M.save_fd(json.dumps({'bank': 'sbi', 'principal': 1, 'rate': 99, 'months': 12}))")["ok"]
    s = ok(call(home, "out = M.save_settings(json.dumps({'policy': 'buy_hold', 'crash_enabled': True, 'execution': 'immediate'}))"))
    assert (s["policy"], s["crash_enabled"], s["execution"]) == ("buy_hold", True, "immediate")
    ok(call(home, "out = M.apply_starter(json.dumps({'id': 'etf_stock', 'amount_inr': 500000, 'buy_date': '2024-08-14'}))"))
    d = ok(call(home, "out = M.check(False, True)"))
    assert d["policy"] == "buy_hold" and d["fds"] and any(o["kind"] == "fixed_deposit" for o in d["others"])
    r = ok(call(home, "out = M.report('asset_classes')"))
    html = Path(r["path"]).read_text()
    assert "<table>" in html and "<h1>" in html
    r = ok(call(home, "out = M.full_report(False, True)"))
    assert Path(r["path"]).stat().st_size > 50_000


def test_yahoo_chart_parsing_and_transport_hook():
    from pe import yahoo_lite as Y
    payload = {"chart": {"result": [{"meta": {"gmtoffset": 19800}, "timestamp": [1723607100, 1723693500, 1723693500],
                                     "indicators": {"quote": [{"close": [250.0, 251.0, 252.0]}], "adjclose": [{"adjclose": [249.0, None, 251.5]}]}}]}}
    s = Y.parse_chart(payload)
    assert [str(d.date()) for d in s.index] == ["2024-08-14", "2024-08-15"] and list(s) == [249.0, 251.5]
    assert Y.parse_chart({"chart": {"result": None}}).empty
    with pytest.raises(ValueError):
        Y.parse_chart({"chart": {"error": {"description": "No data found"}}})
    Y.set_fetcher(lambda url: json.dumps(payload))
    try:
        df = Y.download(["AAA", "BBB"], "2024-01-01")
        assert list(df.columns) == ["AAA", "BBB"] and len(df) == 2
    finally:
        Y.set_fetcher(None)


def test_markdown_pages_keep_tables_and_escape_html():
    from pe.mobile import md_to_html
    html = md_to_html("# Title\n\n| a | b |\n|---|---|\n| 1 | **x** |\n\n- one\n- two <script>\n")
    assert "<th>a</th>" in html and "<td><b>x</b></td>" in html and "<li>one</li>" in html and "<script>" not in html


def test_password_protected_excel(home, tmp_path):
    """Groww-style protected report: asks for the password, rejects a wrong one, then reads the trades."""
    msoffcrypto = pytest.importorskip("msoffcrypto")
    import io
    import pandas as pd
    ok(call(home, "out = M.init()"))
    plain = io.BytesIO()
    pd.DataFrame({"symbol": ["BANKBEES", "BANKBEES"], "trade_date": ["2024-03-01", "2024-04-01"], "trade_type": ["buy", "buy"],
                  "quantity": [10, 5], "price": [500, 510], "trade_id": [1, 2]}).to_excel(plain, index=False)
    plain.seek(0)
    locked = tmp_path / "orders.xlsx"
    with open(locked, "wb") as f:
        msoffcrypto.OfficeFile(plain).encrypt("ABCDE1234F", f)
    pv = ok(call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(locked)!r}]}}))"))
    assert pv["needs"] == ["password"]
    pv = ok(call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(locked)!r}], 'password': 'nope'}}))"))
    assert pv["needs"] == ["password"] and "did not open" in pv["message"]
    pv = ok(call(home, f"out = M.import_preview(json.dumps({{'paths': [{str(locked)!r}], 'password': 'ABCDE1234F'}}))"))
    assert pv["kind"] == "tradebook" and pv["lots"] == 2


def test_backtest_on_own_lots_and_window_replay(home):
    ok(call(home, "out = M.init()"))
    ok(call(home, "out = M.add_lot(json.dumps({'symbol': 'NIFTYBEES', 'buy_date': '2024-08-14', 'qty': 3000, 'price': 250}))"))
    ok(call(home, "out = M.add_lot(json.dumps({'symbol': 'GOLDBEES', 'buy_date': '2025-03-03', 'qty': 500, 'price': 70}))"))
    s = ok(call(home, "out = M.backtest_setup(json.dumps({'demo': True}))"))
    assert s["start"] >= "2024-08-14" and s["deposits"] == 1 and len(s["dates"]) == len(s["invested"]) <= 122
    assert s["invested"][-1] > s["invested"][0]          # the second purchase is money added, not a gain
    mine = ok(call(home, "out = M.backtest_run('yours', json.dumps({'demo': True}))"))
    assert len(mine["curve"]) == len(s["dates"]) and mine["trades"] == 0 and mine["costs"] == 0
    assert all(len(a["values"]) == len(s["dates"]) for a in mine["alloc"]) and {a["sleeve"] for a in mine["alloc"]} == {"india_equity", "gold"}
    assert abs(mine["end_value"] - sum(a["values"][-1] for a in mine["alloc"])) < 5
    other = ok(call(home, "out = M.backtest_run('dual_momentum', json.dumps({'demo': True}))"))
    assert other["invested"] == mine["invested"] and other["trades"] > 0 and other["costs"] > 0
    assert sum(f["bought"] + f["sold"] for f in other["flows"]) > 0
    assert not call(home, "out = M.backtest_run('nope', json.dumps({'demo': True}))")["ok"]
    recent = ok(call(home, "out = M.backtest_setup(json.dumps({'demo': True, 'range': '6m'}))"))
    assert recent["start"] > s["start"] and recent["deposits"] == 0

    ok(call(home, "out = M.save_settings(json.dumps({'policy': 'dual_momentum'}))"))
    r = ok(call(home, "out = M.secretary_replay(json.dumps({'demo': True}))"))
    assert r["n"] == 10 and r["decision"] in ("execute", "observe", "mixed", "none")
    for leg in r["legs"]:
        assert len(leg["prices"]) == r["n"] and leg["signal"][-1] is True and 1 <= leg["run"] <= r["n"]
        assert leg["full"]["decision"] == "execute"       # a full window always ends in a trade
        assert leg["now"]["day"] == leg["run"]
    if r["legs"]:
        b = ok(call(home, "out = M.backdate_window(json.dumps({'demo': True, 'mode': 'full'}))"))
        assert b["legs"] == len(r["legs"]) and (home / "state" / "execution.json").exists()


def test_replay_leg_has_no_lookahead():
    from pe.replay import replay_leg
    dates = [f"2026-01-{d:02d}" for d in range(1, 11)]
    falling = [100 - i for i in range(10)]
    buy = replay_leg(dates, falling, [True] * 10, 10, "buy")
    assert buy["now"]["fired"] == dates[4] and buy["now"]["reason"] == "fired_earlier" and buy["now"]["edge"] > 0   # first new low after 4 watching days
    sell = replay_leg(dates, falling, [True] * 10, 10, "sell")
    assert sell["now"]["fired"] == dates[9] and sell["now"]["reason"] == "last_day"
    fresh = replay_leg(dates, falling, [False] * 7 + [True] * 3, 10, "buy")
    assert fresh["run"] == 3 and fresh["now"]["decision"] == "observe" and fresh["now"]["left"] == 7 and fresh["full"]["decision"] == "execute"
    # changing a later price never changes an earlier day's decision
    bumped = replay_leg(dates, falling[:6] + [200, 200, 200, 200], [True] * 10, 10, "buy")
    assert [s["decision"] for s in bumped["full"]["steps"][:6]] == [s["decision"] for s in buy["full"]["steps"][:6]]


def test_profile_help_is_a_list_for_the_phone(home):
    ok(call(home, "out = M.init()"))
    p = ok(call(home, "out = M.profile()"))
    assert [i["label"] for i in p["income_where_items"]][:2] == ["Gross salary", "RSU/ESPP perquisite"]
    assert all(i["lines"] and "  " not in " ".join(i["lines"]) for i in p["income_where_items"])
