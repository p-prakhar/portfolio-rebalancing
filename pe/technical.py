"""Technical analysis on daily closes, with an explanation for every verdict.

Indicators are weighted by how much evidence stands behind them:
  strong   : long-term trend (200-day average), 12-1 month momentum, nearness to the 52-week high
             (Faber 2007; Jegadeesh & Titman 1993; George & Hwang 2004)
  moderate : 50/200 golden/death cross, volatility-based trailing stop (risk control, not alpha)
  weak     : RSI, MACD, Bollinger bands. Shown as context and timing hints only; they never
             drive a trade on their own.
Only closes are used (no intraday high/low), so the "ATR" is a close-to-close proxy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def rsi(s: pd.Series, n: int = 14) -> float:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up.iloc[-1] / dn.iloc[-1] if dn.iloc[-1] > 0 else np.inf
    return float(100 - 100 / (1 + rs))


def macd_hist(s: pd.Series) -> tuple[float, float]:
    macd = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    return float(hist.iloc[-1]), float(hist.iloc[-2])


@dataclass
class TAResult:
    symbol: str
    score: float                 # roughly -3 (strong downtrend) .. +3 (strong uptrend)
    verdict: str
    stop: float | None
    stop_breached: bool
    metrics: dict = field(default_factory=dict)
    why: list[str] = field(default_factory=list)


def analyse(symbol: str, s: pd.Series, atr_mult: float = 3.0) -> TAResult | None:
    s = s.dropna()
    if len(s) < 210:
        return None
    p = float(s.iloc[-1])
    sma50, sma200 = float(s.iloc[-50:].mean()), float(s.iloc[-200:].mean())
    prev50, prev200 = float(s.iloc[-55:-5].mean()), float(s.iloc[-205:-5].mean())
    hi52 = float(s.iloc[-252:].max())
    mom = float(s.iloc[-22] / s.iloc[-min(253, len(s))] - 1)            # 12-1 month
    vol = float(s.pct_change().iloc[-63:].std() * np.sqrt(252))
    atr = float(s.diff().abs().iloc[-14:].mean())
    stop = float(s.iloc[-22:].max()) - atr_mult * atr                  # chandelier-style trailing stop
    r = rsi(s)
    h, h_prev = macd_hist(s)
    mid = s.iloc[-20:].mean()
    sd = s.iloc[-20:].std()
    pctb = float((p - (mid - 2 * sd)) / (4 * sd)) if sd > 0 else 0.5

    score, why = 0.0, []
    if p > sma200:
        score += 1
        why.append(f"Price is {p / sma200 - 1:+.1%} above its 200-day average: long-term uptrend.")
    else:
        score -= 1
        why.append(f"Price is {p / sma200 - 1:+.1%} below its 200-day average: long-term downtrend.")
    if sma50 > sma200:
        score += 0.5
        if prev50 <= prev200:
            why.append("Fresh golden cross: the 50-day average just moved above the 200-day.")
    else:
        score -= 0.5
        if prev50 >= prev200:
            why.append("Fresh death cross: the 50-day average just moved below the 200-day.")
    score += float(np.clip(mom / 0.2, -1, 1))
    why.append(f"12-1 month momentum {mom:+.1%}.")
    gap = p / hi52 - 1
    if gap > -0.05:
        score += 0.5
        why.append(f"Within {abs(gap):.1%} of its 52-week high; stocks near highs have tended to keep outperforming.")
    elif gap < -0.25:
        score -= 0.5
        why.append(f"{abs(gap):.0%} below its 52-week high.")
    breached = p < stop
    if breached:
        why.append(f"Closed below its trailing stop ({stop:,.2f} = 22-day high minus {atr_mult:g}x average daily move).")
    hints = []
    if r > 75:
        hints.append(f"RSI {r:.0f} (overbought; better to add on a pullback than chase)")
    elif r < 30:
        hints.append(f"RSI {r:.0f} (oversold; selling into this often gets a poor price)")
    if h > 0 > h_prev:
        hints.append("MACD just turned up")
    elif h < 0 < h_prev:
        hints.append("MACD just turned down")
    if pctb > 1:
        hints.append("above the upper Bollinger band")
    elif pctb < 0:
        hints.append("below the lower Bollinger band")
    if hints:
        why.append("Timing hints (weak evidence): " + "; ".join(hints) + ".")

    verdict = ("strong uptrend" if score >= 2 else "uptrend" if score >= 0.75 else "neutral" if score > -0.75
               else "downtrend" if score > -2 else "strong downtrend")
    return TAResult(symbol, score, verdict, stop, breached,
                    {"price": p, "sma50": sma50, "sma200": sma200, "high_52w": hi52, "mom_12_1": mom, "vol_3m": vol,
                     "rsi14": r, "macd_hist": h, "pct_b": pctb}, why)


def analyse_all(px: pd.DataFrame, symbols) -> dict[str, TAResult]:
    out = {}
    for s in symbols:
        if s in px and s != "CASH":
            r = analyse(s, px[s])
            if r:
                out[s] = r
    return out
