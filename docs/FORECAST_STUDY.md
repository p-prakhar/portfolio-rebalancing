# Forecasts and fundamentals: do they beat the backtest?

Period 2016-10-23 to 2026-10-23. Same engine as the daily simulation: lots, costs, Indian tax, rolling 3-year windows. Valuation history starts 2012-02 (NSE archive); niftyindices.com was unreachable.

## 1. Do the signals predict returns at all? (no trading rule yet)

- **252d ahead** (2021-11-22 to 2025-10-14, about 3.8 independent periods): P/E percentile rank corr -0.33 (t ≈ -0.47); earnings-yield-minus-bond z -0.34 (t ≈ -0.49); regression forecast +0.33 (t ≈ 0.47)
- **756d ahead** (about 0.6 independent periods): -0.48, +0.12, +0.76 (all t < 1.2)
- Walk-forward regression forecast out-of-sample R² vs past-average forecast: **-1.027**. Below zero means it forecast worse than not forecasting.

## 2. Trading results

| strategy | CAGR after tax | max drawdown | windows won | median excess/yr | worst window | early half | late half |
|---|---|---|---|---|---|---|---|
| Buy & hold Nifty 50 | 10.3% | -36.3% | - | - | - | - | - |
| Nifty + P/E percentile | 8.9% | -17.9% | 38% | -0.8% | -5.8% | -1.2% | +0.2% |
| Nifty + earnings yield vs bond yield | 10.5% | -36.3% | 62% | +0.1% | -1.6% | -0.4% | +0.2% |
| Nifty + regression forecast | 10.7% | -36.3% | 75% | +0.3% | -0.2% | +0.0% | +0.2% |
| Nifty + all three (most cautious) | 8.8% | -17.9% | 38% | -0.6% | -5.9% | -1.2% | +0.2% |
| Core-satellite momentum (current best) | 12.6% | -23.3% | 62% | +1.0% | -2.8% | -2.6% | +7.1% |
| Core-satellite + P/E percentile | 11.8% | -22.2% | 50% | -0.5% | -6.1% | -2.7% | +7.1% |
| Core-satellite + earnings yield vs bond | 13.0% | -22.4% | 62% | +1.5% | -2.3% | -1.9% | +7.1% |
| Core-satellite + regression forecast | 12.5% | -23.3% | 62% | +0.8% | -2.8% | -2.6% | +6.7% |

## 3. Could the best of these be luck?

8 variants tried (plus about 10 strategies tested earlier). Block-bootstrap reality check: chance the best variant (core-satellite + earnings yield vs bond) looks this good by luck: **0.36**. Below 0.05 would be evidence of a real edge.

| variant | excess per year | 95% interval | p (alone) |
|---|---|---|---|
| Nifty + P/E percentile | -2.0% | -6.4% to +2.3% | 0.83 |
| Nifty + earnings yield vs bond yield | -0.4% | -1.0% to +0.3% | 0.86 |
| Nifty + regression forecast | -0.3% | -0.6% to +0.1% | 0.93 |
| Nifty + all three | -2.1% | -6.5% to +2.2% | 0.84 |
| Core-satellite momentum | +1.7% | -4.1% to +7.5% | 0.29 |
| Core-satellite + P/E percentile | +0.9% | -6.9% to +8.6% | 0.41 |
| Core-satellite + earnings yield vs bond | +2.1% | -3.9% to +8.0% | 0.24 |
| Core-satellite + regression forecast | +1.6% | -4.3% to +7.4% | 0.31 |

## Verdict
Nothing is distinguishable from luck. Do not add to the live engine. Rerun with P/E history from 1999 (data/manual/nifty_valuation.csv) for a fair test.
