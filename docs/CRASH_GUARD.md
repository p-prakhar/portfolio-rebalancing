# Crash guard: leaving fast when a bubble bursts

Not specific to AI. It reads what large falls have in common and acts on the pattern, not the story.

## Audit: what the strategies did before the guard

| Gap found | Detail |
|---|---|
| Default policy never sold the core | `core_xs` leaves 60% in the Nifty ETF on purpose, so the biggest holding had no exit rule at all. |
| Slow checks | Signals ran monthly, so a fall could run for up to a month before any rule looked. |
| Regime label was decoration | `regime()` computed calm, caution, risk-off but only fed the report text. |
| Only two signals | Trend and volatility. Nothing on breadth, credit, speed of a fall, or leaders cracking. |
| Metals, chips and commodities not treated as risk | Risk exits applied to India and global equity sleeves only. |
| Long-term wait could trap an exit | A lot 60 days from long-term status could be held through a crash (the wait was only doubled in risk-off). |
| Buy & hold had no way to come back | A cut needs a remembered target to restore. |

`trend_vol`, `dual_momentum` and `daa` already cut risk on trend breaks, but each was a whole strategy you had to switch to, and the 10-year test found `trend_vol` lost to holding. The guard is an overlay that works on top of any policy.

## What it does

Six signal families, checked daily on a market proxy (60% Nifty ETF, 40% S&P 500 by default):

1. Price damage: below the 200-day average, and/or 10% below the 52-week high (up to 2 points)
2. Speed: down 5% in 5 days or 8% in 10
3. Volatility: 20-day volatility above 1.6x its one-year level (and above 20%), or an India VIX spike
4. Breadth: 60%+ of equity instruments below their 200-day average
5. Credit: high-yield vs treasuries (HYG/IEF) more than 2% under its 100-day average
6. Leaders cracking: two of the three biggest 12-month winners have broken their 50-day average and are 10%+ off their highs (how a bubble bursts: the stars go first)

A run-up (market in the top 5% of its 3-year extension within the last 4 months) lowers every bar by one point.

| Level | Needs | Action |
|---|---|---|
| 0 calm | | nothing changes |
| 1 watch | 2 points | no new money into risk assets |
| 2 elevated | 3 points, 3 families, one a stress signal | keep 75% of risk assets |
| 3 crisis | 5 points, 4 families | keep 25%, stop waiting for long-term tax status |

Excess goes to the shelter: the cash sleeve (arbitrage fund, taxed as equity) plus gold (up to 40% of the freed money, 20% of the portfolio) only while gold is above its 200-day average, because gold also falls in a liquidity squeeze.

Indian tax and costs: the exit goes through the normal planner, so lots are picked losses first then long-term gains, STT, stamp duty, DP charge and spread are charged, and exits skip the "is it worth switching" hurdle (the point is not return). `python main.py crash` prints a drill: what a level 2 or 3 exit would cost you today in tax and costs, and how much further the market must fall for the exit to pay for itself.

Whipsaw defences: families must agree, a price drop alone cannot raise the level above watch (a stress signal must confirm), a level falls one step only after 15 straight days of lower readings, and the level is replayed from history on every call so live and backtest agree.

## How to use

- `python main.py crash`: today's level, each signal, the exit drill
- `python main.py run` and `site`: the guard is on by default (`strategy.crash.enabled`); the report and the first tab show it, and when it fires the plan contains the cuts
- `python main.py crash-test`: 10-year replay with every fall and every false alarm after costs and tax (needs Yahoo data; run it on your own machine)
- Turn it off with `strategy.crash.enabled: false`

## What we do not know yet

The parameters are textbook values chosen before any backtest and not tuned. They have only been exercised on synthetic price paths (a code check, not evidence). Run `crash-test` on real data before trusting the numbers. Crashes are rare, so even 10 years holds only a handful of falls: read the result as case studies. True valuation (PE, CAPE) and fund-flow data are not free to fetch reliably, so valuation enters only through the run-up flag. The cost to expect is false alarms: markets fall 10% far more often than they crash.
