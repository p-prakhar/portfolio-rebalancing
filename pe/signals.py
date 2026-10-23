"""Signals: NSE-style cross-sectional momentum, Antonacci dual momentum, market regime."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _ann_vol(rets: pd.DataFrame) -> pd.Series:
    return rets.std() * np.sqrt(TRADING_DAYS)


def xs_momentum(px: pd.DataFrame, symbols: list[str], lookbacks=(126, 252), skip: int = 21,
                cash_symbol: str = "CASH") -> pd.DataFrame:
    """Normalised momentum score per symbol, as of the last row of `px`.

    For each lookback M: MR = return over M days (ending `skip` days ago) / annualised vol
    over the same window; Z = cross-sectional z-score of MR; score = mean of Zs.
    Also reports raw 12m return and excess over the cash sleeve (absolute momentum).
    """
    need = max(lookbacks) + skip + 1
    syms = [s for s in symbols if s in px and px[s].iloc[-need:].notna().all()]
    if len(syms) < 2:
        return pd.DataFrame()
    out = pd.DataFrame(index=syms)
    end = len(px) - 1 - skip
    for m in lookbacks:
        window = px[syms].iloc[end - m:end + 1]
        ret = window.iloc[-1] / window.iloc[0] - 1
        vol = _ann_vol(window.pct_change().dropna())
        mr = ret / vol.replace(0, np.nan)
        out[f"ret_{m}"] = ret
        out[f"mr_{m}"] = mr
        out[f"z_{m}"] = (mr - mr.mean()) / (mr.std(ddof=0) or 1.0)
    out["score"] = out[[f"z_{m}" for m in lookbacks]].mean(axis=1)
    long_m = max(lookbacks)
    out["ret_12m"] = px[syms].iloc[-1] / px[syms].iloc[-1 - TRADING_DAYS] - 1
    out["vol_6m"] = _ann_vol(px[syms].iloc[-127:].pct_change().dropna())
    cash_ret = px[cash_symbol].iloc[-1] / px[cash_symbol].iloc[-1 - TRADING_DAYS] - 1 if cash_symbol in px else 0.0
    out["excess_vs_cash"] = out[f"ret_{long_m}"] - cash_ret
    out["rank"] = out["score"].rank(ascending=False).astype(int)
    return out.sort_values("score", ascending=False)


def dual_momentum(px: pd.DataFrame, equity: str, gold: str, cash: str, lookback=252, sma=200) -> dict:
    """Antonacci-style: pick the stronger of equity/gold if it is also above its SMA, else cash."""
    if any(s not in px or px[s].iloc[-lookback - 1:].isna().any() for s in (equity, gold)):
        return {"choice": None, "why": ["Not enough history for dual momentum."]}
    r = {s: px[s].iloc[-1] / px[s].iloc[-1 - lookback] - 1 for s in (equity, gold, cash)}
    above = {s: px[s].iloc[-1] > px[s].iloc[-sma:].mean() for s in (equity, gold)}
    leader = equity if r[equity] > r[gold] else gold
    why = [f"12m return: {equity} {r[equity]:+.1%}, {gold} {r[gold]:+.1%}, cash {r[cash]:+.1%}.",
           f"{equity} is {'above' if above[equity] else 'below'} its {sma}-day average; "
           f"{gold} is {'above' if above[gold] else 'below'}."]
    if above[leader] and r[leader] > r[cash]:
        choice = leader
        why.append(f"{leader} leads on relative momentum and passes the absolute trend filter, so it gets the allocation.")
    else:
        other = gold if leader == equity else equity
        if above[other] and r[other] > r[cash]:
            choice = other
            why.append(f"Leader {leader} fails the trend filter; {other} passes, so it takes the allocation.")
        else:
            choice = cash
            why.append("Neither equity nor gold passes the trend filter, so the model moves to cash.")
    return {"choice": choice, "returns": r, "above_sma": above, "why": why}


def regime(px: pd.DataFrame, vix: pd.Series | None, equity: str = "NIFTYBEES") -> dict:
    """Market condition summary used for the risk overlay and the report."""
    s = px[equity].dropna()
    sma200 = s.iloc[-200:].mean()
    vol20 = s.pct_change().iloc[-20:].std() * np.sqrt(TRADING_DAYS)
    vol252 = s.pct_change().iloc[-252:].std() * np.sqrt(TRADING_DAYS)
    dd = s.iloc[-1] / s.iloc[-252:].max() - 1
    v = float(vix.dropna().iloc[-1]) if vix is not None and vix.dropna().size else None
    below = s.iloc[-1] < sma200
    stress = (v is not None and v > 22) or vol20 > 1.5 * vol252
    label = "risk_off" if below and stress else "caution" if below or stress else "calm"
    why = [f"{equity} is {s.iloc[-1] / sma200 - 1:+.1%} vs its 200-day average, {dd:+.1%} from its 52-week high.",
           f"20-day volatility {vol20:.0%} vs 1-year {vol252:.0%}" + (f"; India VIX {v:.1f}." if v else ".")]
    return {"label": label, "below_sma200": bool(below), "vol20": vol20, "vol252": vol252,
            "drawdown": dd, "vix": v, "why": why}
