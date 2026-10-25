from datetime import date

import pandas as pd

from pe.etrade import lots_from_benefit_history, lots_from_etrade


def _workbook(path):
    rsu_cols = ["Record Type", "Symbol", "Grant Date", "Vested Qty.", "Sellable Qty.", "Grant Number", "Vest Period", "Vest Date",
                "Vested Qty..1", "Released Qty", "Taxable Gain", "Withholding Amount"]
    rsu = pd.DataFrame([
        ["Grant", "ACME", "12-AUG-2024", 50, 26, "R1", None, None, None, None, None, None],
        ["Vest Schedule", None, None, None, None, "R1", 1, "08/11/2025", 40, 40, None, None],
        ["Tax Withholding", None, None, None, None, "R1", 1, None, None, None, 4000.0, 1200.0],   # FMV 100, 12 shares withheld
        ["Vest Schedule", None, None, None, None, "R1", 2, "11/10/2025", 10, 10, None, None],
        ["Tax Withholding", None, None, None, None, "R1", 2, None, None, None, 500.0, 0.0],
        ["Vest Schedule", None, None, None, None, "R1", 3, "03/15/2027", 10, 0, None, None],       # future vest
    ], columns=rsu_cols)
    rsu.columns = [c.replace("..1", ".") for c in rsu.columns]   # E*TRADE repeats 'Vested Qty.'
    espp = pd.DataFrame([["Purchase", "ACME", "12-FEB-2025", 30.0, 10, 10, 10, "$40.00"]],
                        columns=["Record Type", "Symbol", "Purchase Date", "Purchase Price", "Purchased Qty.", "Net Shares", "Sellable Qty.", "Purchase Date FMV"])
    with pd.ExcelWriter(path) as w:
        espp.to_excel(w, sheet_name="ESPP", index=False)
        rsu.to_excel(w, sheet_name="Restricted Stock", index=False)


def test_benefit_history_rsu_net_of_withholding_espp_at_fmv_and_sold_fifo(tmp_path):
    p = tmp_path / "BenefitHistory.xlsx"
    _workbook(p)
    lots, meta, warns = lots_from_benefit_history(str(p), "acme", lambda d: 80.0)
    # received: ESPP 10 (Mar 2025) + RSU 28 net (Sep 2025) + RSU 10 (Dec 2025) = 48; sellable 26 + 10 = 36 -> 12 sold, oldest first
    assert [(l["buy_date"], l["qty"]) for l in lots] == [("2025-08-11", 26.0), ("2025-11-10", 10.0)]
    assert lots[0]["price"] == 100 * 80.0 and lots[1]["price"] == 50 * 80.0
    assert meta["ACME"]["sell_only"] and any("12 were sold" in w for w in warns)
    assert lots_from_etrade(str(p), "acme", lambda d: 80.0)[0] == lots      # the general entry point uses the same parser


def test_espp_cost_is_fmv_not_discounted_price(tmp_path):
    p = tmp_path / "b.xlsx"
    pd.DataFrame([["Purchase", "ACME", "12-FEB-2025", 30.0, 10, 10, 10, "$40.00"]],
                 columns=["Record Type", "Symbol", "Purchase Date", "Purchase Price", "Purchased Qty.", "Net Shares", "Sellable Qty.", "Purchase Date FMV"]
                 ).to_excel(p, sheet_name="ESPP", index=False)
    lots, _, _ = lots_from_benefit_history(str(p), "ACME", lambda d: 1.0)
    assert lots == [{"symbol": "ACME", "qty": 10.0, "buy_date": "2025-02-12", "price": 40.0, "currency": "USD"}]
