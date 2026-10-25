# Choosing a strategy automatically

Question: is there a reliable rule that picks which of our strategies to follow? Short answer from the literature: weakly, and costs and tax eat most of it. The engine tests this directly instead of assuming it (`python main.py switch`).

## What the research says

- **Picking the recent winner (strategy momentum).** Works in some asset classes at 3 to 12 month horizons, but the edge is small, unstable, and needs frequent switching. In India every switch realises capital gains (20% short term, 12.5% long term), so a switch must beat the tax it triggers before it earns anything.
- **Equal weight across options (1/N).** DeMiguel, Garlappi and Uppal (2009) found optimised allocation rules rarely beat 1/N out of sample. Blending strategies instead of choosing one is the standard hard-to-beat baseline here.
- **Online learning (Hedge / exponentiated gradient).** Meta-algorithms over expert portfolios have regret guarantees against the best expert in hindsight, not guarantees of beating a simple blend after costs. See the survey [Online Portfolio Selection](https://arxiv.org/pdf/1212.2129) and [Meta Algorithms for Portfolio Selection](https://conservancy.umn.edu/items/ba8b2791-ac2b-447e-a2c1-007c0954c299).
- **Selection bias.** Choosing the best of many backtests overstates the live result. Bailey and Lopez de Prado, [The Deflated Sharpe Ratio](https://papers.ssrn.com/abstract=2460551), is the correction used here, together with a block bootstrap. Related discussion of in-sample versus out-of-sample strategy performance: [CXO Advisory](https://www.cxoadvisory.com/big-ideas/in-sample-vs-out-of-sample-performance-of-888-trading-strategies).

Only titles and abstracts were reviewed; read the papers before relying on the specific claims above.

## What is implemented (`pe/switcher.py`)

All parameters were fixed before looking at results.

| rule | idea |
|---|---|
| equal_weight | split money equally across strategies (the baseline) |
| inverse_vol | weight by 1 / 12-month volatility |
| momentum_switch | 100% in the best 12-month strategy, switch only if a challenger leads by 3 points |
| hedge | multiplicative weights on monthly outperformance, 40% cap per strategy |

Each strategy is a sleeve. Moving money out of a sleeve pays 0.1% each way plus tax on that sleeve's gain, with the yearly exemption. Decisions use data to the previous day.

## How it is judged

A rule is called a switcher worth using only if all hold: bootstrap 90% range of its yearly gap over the equal blend is above zero, deflated Sharpe above 0.95 (trial count includes every rule and strategy), it wins 60% of rolling 3-year windows, and no window is worse than -5 points a year. Otherwise the verdict is "no reliable edge".

## Limits

- The strategies were themselves designed and screened on the same history, so every number is optimistic.
- Sleeve curves already contain their own internal tax, so tax on sleeve gains is approximated. Losses are not refunded.
- Rolling windows overlap and are not independent.

## Result on real prices (2017-10 to 2026-10, 9 years, 13 variants tried)

Verdict: **do not switch automatically.** None of the four rules passed the gate.

| rule | per year after tax | worst fall | gap vs equal blend | deflated Sharpe |
|---|---|---|---|---|
| momentum_switch | 11.5% | -35.2% | +0.1% (range -6.5 to +7.4) | 0.06 |
| equal_weight (baseline) | 10.4% | -18.9% | - | - |
| hedge | 9.4% | -22.7% | -1.5% | 0.00 |
| inverse_vol | 6.8% | -6.0% | -3.8% | 0.00 |

- Momentum switching matched the blend before tax drag but paid about twice the tax and costs for it, and its worst fall equalled holding Nifty alone.
- Hedge beat the blend in 8 of 12 rolling windows by a median of 0.3 points, well inside the noise.
- Every single strategy also failed the gate against the blend (deflated Sharpe at most 0.27). The year-by-year table shows winners rotate, so last year's leader says little about next year's.
- The equal blend beat just holding Nifty in all 12 rolling windows (median +3.5 points a year) with a much smaller worst fall. That is the practical answer: spread across the strategies, rebalance rarely, and do not chase the leader.
- Caveat: these strategies were designed and screened on the same history, so the blend's edge over holding is probably overstated too.
