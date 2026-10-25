# When to rebalance: rules beyond the secretary problem

`python main.py timing` runs the comparison (`--demo` uses synthetic prices, a code check only). Output: `reports/timing.md`.
The strategy is held fixed (the configured policy); only the timing rule changes, one thing at a time from a control
(monthly check, immediate fills). Costs, Indian tax, rolling windows, the block bootstrap and the deflated Sharpe all apply,
and every variant counts as a trial. Parameters are not tuned on the windows reported.

## What suits a small Indian retail investor

| idea | what it answers | verdict for this engine |
|---|---|---|
| Secretary rule | which day inside an execution window | Kept as an option. On a random walk no stopping rule raises the average fill; it only changes the spread. Past real runs: secretary fills trailed immediate by about 1 point a year (reports/validation.md). |
| Threshold rule (known distribution) | same, with a barrier of `z * sigma * sqrt(days left)` | Implemented (`threshold`). Same theory, same caveat. |
| No-trade band, fixed (5%, 10%) | whether to act at all | Implemented (`band`). Cheap, easy to explain, cuts trades that cost more than they help. |
| Cost-aware band (Rogers-Mayer / Leland style) | band sized from the plan's own cost and tax | Implemented (`cost_band`). Width grows with the cube root of cost, so a 1% round trip still gives a band of several percent. |
| Calendar (weekly to yearly) | how often to look | Implemented (`quarterly`, `annual_mar`). Yearly in March lines up with the tax year and the LTCG exemption. |
| Tax-aware deferral | wait for the 12-month mark | Already in the engine (`ltcg_wait`); the sweep has an off switch for it as an ablation. |
| Staged entry (DCA) | lump sum or tranches | `dca_study`: before cost and tax, lump sum is ahead about as often as it is behind on a trending market; DCA buys lower regret, not more return. |
| Multi-armed bandit | learn the best fill rule from experience | In `exec_study`. A retail investor places tens of orders, not thousands; the bandit mostly settles on immediate or TWAP. Not worth shipping as a live rule. |
| Kelly / fractional Kelly | how much risk to carry | A sizing rule. The answer moves wildly with a mean-return estimate that ten years cannot pin down; reported for context only. |
| VWAP | match the day's volume profile | Needs intraday data and matters for large orders. At this size TWAP is the same thing. |

## Reading the result

Compare each row with the control row, not with buy and hold. A timing rule has to beat doing the same thing monthly with
no band, after cost and tax, with a bootstrap range that excludes zero, to deserve a place.
