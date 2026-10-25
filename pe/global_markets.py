"""Dividend tax drag for foreign funds held by an Indian resident, and the market vetting list.

US-domiciled ETF (SPY, QQQ, EWJ...): the US withholds on dividends paid to an Indian individual
(`dividends.us_wht`, treaty rate, needs a W-8BEN), and India taxes the same dividend at slab. Form 67 gives
a credit for the US tax, capped at the Indian tax on that income, so the total is the larger of the two.
Price series are adjusted closes (dividends reinvested gross), so this is taken off every year.

Irish UCITS accumulating ETF (CSPX, VWRA...): the fund's NAV is already net of the withholding the fund paid, and
India taxes nothing until you sell, so no extra drag. A distributing line would be taxed at slab on the payout.
"""
from __future__ import annotations

import pandas as pd

from .config import Asset, Settings


def india_dividend_rate(settings: Settings) -> float:
    t = settings.tax
    return t["slab_rate"] * (1 + t.get("surcharge", 0.0)) * (1 + t["cess"])


def dividend_drag(settings: Settings, asset: Asset) -> float:
    """Extra yearly return lost to dividend tax, as a fraction of value, beyond what the price series shows."""
    if not asset.div_yield or asset.domicile is None:
        return 0.0
    d = settings.raw.get("dividends", {})
    india = india_dividend_rate(settings)
    if asset.domicile == "US":
        return asset.div_yield * max(d.get("us_wht", 0.25), india)   # credit under Form 67 is capped at the Indian tax
    if asset.domicile == "IE" and not asset.accumulating:
        return asset.div_yield * india
    return 0.0


def apply_dividend_drag(settings: Settings, asset: Asset, series: pd.Series) -> pd.Series:
    drag = dividend_drag(settings, asset)
    if drag <= 0 or series.empty:
        return series
    years = (series.index - series.index[0]).days.values / 365.0
    return series * (1 - drag) ** years
