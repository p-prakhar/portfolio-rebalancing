from datetime import date
from pathlib import Path
import pytest
import yaml

from pe.config import Lot, load_holdings, load_settings, register_assets
from pe.corporate_actions import (
    CorporateActions,
    Demerger,
    Merger,
    ResultingEntity,
    Split,
    apply_corporate_actions,
    apply_to_holdings,
    load_corporate_actions,
    sync_holdings_file,
)
from pe.importer import lots_from_tradebook


def test_load_corporate_actions():
    actions = load_corporate_actions()
    assert any(d.parent == "TATAMOTORS" for d in actions.demergers)
    tata = next(d for d in actions.demergers if d.parent == "TATAMOTORS")
    assert tata.date == date(2025, 10, 14)
    assert not tata.keep_parent
    syms = {r.symbol for r in tata.resulting}
    assert syms == {"TMPV", "TMCV"}
    tmpv = next(r for r in tata.resulting if r.symbol == "TMPV")
    tmcv = next(r for r in tata.resulting if r.symbol == "TMCV")
    assert tmpv.cost_share == 0.6885
    assert tmcv.cost_share == 0.3115
    assert pytest.approx(tmpv.cost_share + tmcv.cost_share) == 1.0


def test_tatamotors_demerger_lots():
    lots = [
        Lot("TATAMOTORS", 20.0, date(2025, 1, 22), 612.40),
        Lot("TATAMOTORS", 10.0, date(2025, 1, 30), 588.0),
    ]
    new_lots, notices = apply_corporate_actions(lots)
    assert len(new_lots) == 4
    assert len(notices) == 1
    assert "TATAMOTORS" not in {l.symbol for l in new_lots}

    # Verify first purchase (20 shares @ 612.40)
    tmpv_1 = next(l for l in new_lots if l.symbol == "TMPV" and l.buy_date == date(2025, 1, 22))
    tmcv_1 = next(l for l in new_lots if l.symbol == "TMCV" and l.buy_date == date(2025, 1, 22))
    assert tmpv_1.qty == 20.0
    assert tmcv_1.qty == 20.0
    assert tmpv_1.price == pytest.approx(612.40 * 0.6885, abs=1e-4)
    assert tmcv_1.price == pytest.approx(612.40 * 0.3115, abs=1e-4)
    # Total cost preserved
    assert tmpv_1.cost + tmcv_1.cost == pytest.approx(20.0 * 612.40, abs=0.01)

    # Verify second purchase (10 shares @ 588.0)
    tmpv_2 = next(l for l in new_lots if l.symbol == "TMPV" and l.buy_date == date(2025, 1, 30))
    tmcv_2 = next(l for l in new_lots if l.symbol == "TMCV" and l.buy_date == date(2025, 1, 30))
    assert tmpv_2.qty == 10.0
    assert tmcv_2.qty == 10.0
    assert tmpv_2.price == pytest.approx(588.0 * 0.6885, abs=1e-4)
    assert tmcv_2.price == pytest.approx(588.0 * 0.3115, abs=1e-4)
    assert tmpv_2.cost + tmcv_2.cost == pytest.approx(10.0 * 588.0, abs=0.01)


def test_post_record_date_lot_unaffected():
    # A lot purchased after record date (e.g. theoretical scenario) is not altered
    lots = [Lot("TATAMOTORS", 10.0, date(2025, 11, 1), 500.0)]
    new_lots, notices = apply_corporate_actions(lots)
    assert len(new_lots) == 1
    assert new_lots[0].symbol == "TATAMOTORS"
    assert not notices


def test_keep_parent_spinoff():
    actions = CorporateActions(
        demergers=[
            Demerger(
                parent="RELIANCE",
                date=date(2023, 7, 20),
                name="Reliance Jio spin-off",
                keep_parent=True,
                parent_cost_share=0.95,
                resulting=[ResultingEntity(symbol="JIOFIN", ratio=1.0, cost_share=0.05)],
            )
        ]
    )
    lots = [Lot("RELIANCE", 100.0, date(2023, 1, 15), 2000.0)]
    new_lots, notices = apply_corporate_actions(lots, actions)
    assert len(new_lots) == 2
    rel = next(l for l in new_lots if l.symbol == "RELIANCE")
    jio = next(l for l in new_lots if l.symbol == "JIOFIN")
    assert rel.qty == 100.0
    assert rel.price == 1900.0
    assert jio.qty == 100.0
    assert jio.price == 100.0
    assert rel.cost + jio.cost == 100.0 * 2000.0


def test_stock_split():
    actions = CorporateActions(
        splits=[Split(symbol="CANBK", date=date(2024, 5, 15), ratio=5.0, name="Canara Bank 1:5 split")]
    )
    lots = [Lot("CANBK", 20.0, date(2024, 1, 10), 500.0)]
    new_lots, notices = apply_corporate_actions(lots, actions)
    assert len(new_lots) == 1
    assert new_lots[0].symbol == "CANBK"
    assert new_lots[0].qty == 100.0
    assert new_lots[0].price == 100.0
    assert new_lots[0].cost == pytest.approx(20.0 * 500.0)


def test_merger():
    actions = CorporateActions(
        mergers=[Merger(old_symbol="HDFC", new_symbol="HDFCBANK", date=date(2023, 7, 13), ratio=1.68)]
    )
    lots = [Lot("HDFC", 25.0, date(2023, 1, 10), 2500.0)]
    new_lots, notices = apply_corporate_actions(lots, actions)
    assert len(new_lots) == 1
    assert new_lots[0].symbol == "HDFCBANK"
    assert new_lots[0].qty == 42.0
    assert new_lots[0].cost == pytest.approx(25.0 * 2500.0, abs=0.01)


def test_importer_applies_corporate_actions(tmp_path):
    csv_file = tmp_path / "tradebook.csv"
    csv_file.write_text(
        "symbol,trade_date,trade_type,quantity,price\n"
        "TATAMOTORS,2025-02-17,buy,20,612.40\n"
        "TATAMOTORS,2025-02-25,buy,10,588.00\n"
    )
    lots, warns = lots_from_tradebook(str(csv_file))
    symbols = {l["symbol"] for l in lots}
    assert symbols == {"TMPV", "TMCV"}
    assert any("Tata Motors" in w for w in warns)


def test_sync_holdings_file(tmp_path):
    h_file = tmp_path / "holdings.yaml"
    h_file.write_text(
        "lots:\n"
        "  - {symbol: TATAMOTORS, qty: 20.0, buy_date: '2025-02-17', price: 612.40}\n"
        "cash_inr: 0\n"
    )
    changed, notices = sync_holdings_file(h_file)
    assert changed
    assert len(notices) >= 1
    assert (tmp_path / "holdings.yaml.bak").exists()
    doc = yaml.safe_load(h_file.read_text())
    syms = {l["symbol"] for l in doc["lots"]}
    assert syms == {"TMPV", "TMCV"}
    assert "TMPV" in doc.get("assets", {})
    assert "TMCV" in doc.get("assets", {})


def test_reapplying_actions_is_idempotent():
    """Keep-parent demergers and splits leave the symbol unchanged, so a second pass must not compound."""
    actions = CorporateActions(
        demergers=[Demerger(parent="PARENT", date=date(2023, 7, 20), name="spin-off", keep_parent=True,
                            parent_cost_share=0.95,
                            resulting=[ResultingEntity(symbol="CHILD", ratio=1.0, cost_share=0.05)])],
        splits=[Split(symbol="SPLITCO", date=date(2024, 5, 15), ratio=5.0)],
    )
    lots = [Lot("PARENT", 100.0, date(2023, 1, 15), 2000.0), Lot("SPLITCO", 20.0, date(2024, 1, 10), 500.0)]
    once, _ = apply_corporate_actions(lots, actions)
    twice, notices = apply_corporate_actions(once, actions)
    assert twice == once and not notices
    # also through the dict / holdings.yaml route
    dicts = [{"symbol": "PARENT", "qty": 100.0, "buy_date": "2023-01-15", "price": 2000.0}]
    d1, _ = apply_corporate_actions(dicts, actions)
    d2, _ = apply_corporate_actions(d1, actions)
    assert d1 == d2 and len(d1) == 2
    assert sum(l["qty"] * l["price"] for l in d2) == pytest.approx(200000.0)


def test_sync_holdings_file_twice_is_stable(tmp_path):
    h = tmp_path / "holdings.yaml"
    h.write_text("lots:\n  - {symbol: RELIANCE, qty: 100, buy_date: '2023-01-15', price: 2000}\n"
                 "  - {symbol: INFY, buy_date: '2023-03-01', amount_inr: 5000}\ncash_inr: 0\n")
    assert sync_holdings_file(h)[0]
    first = h.read_text()
    assert sync_holdings_file(h) == (False, [])
    assert h.read_text() == first
    assert load_holdings(h, apply_actions=False).lots[0].adjusted     # marker survives the round trip


def test_buy_on_ex_date_is_not_entitled():
    lots = [Lot("TATAMOTORS", 10.0, date(2025, 10, 13), 500.0), Lot("TATAMOTORS", 10.0, date(2025, 10, 14), 500.0)]
    new_lots, _ = apply_corporate_actions(lots)
    assert sorted((l.symbol, l.buy_date.day) for l in new_lots) == [("TATAMOTORS", 14), ("TMCV", 13), ("TMPV", 13)]


def test_explicit_ex_date_overrides_record_date():
    actions = CorporateActions(splits=[Split(symbol="X", date=date(2024, 5, 15), ratio=2.0, ex_date=date(2024, 5, 14))])
    lots = [Lot("X", 1.0, date(2024, 5, 13), 100.0), Lot("X", 1.0, date(2024, 5, 14), 100.0)]
    new_lots, _ = apply_corporate_actions(lots, actions)
    assert [(l.qty, l.price) for l in new_lots] == [(2.0, 50.0), (1.0, 100.0)]
