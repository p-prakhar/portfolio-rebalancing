# Tax-aware portfolio rebalancing engine for an Indian resident: full strategy description, for outside critique

_Version of 25 Oct 2026. Written to be read on its own, with no access to the code. Everything is anonymised: no holdings, names, employers, places or amounts from the real user._

## 0. What I am asking you to do

You are asked to act as a hostile but fair reviewer: a quantitative researcher, an Indian chartered accountant and a retail-investing sceptic in one. Find what is wrong, overfitted, mis-specified, illegal, misleading or missing. Section 15 lists the questions I most want answered. Please separate (a) errors of fact (tax law, costs, market rules), (b) errors of method (backtest, statistics), and (c) judgement calls where you would decide differently. Cite sources where you can. If you think the project should be reduced to "buy a Nifty index fund and harvest the tax exemption each year", say so and say why.

**Status of the evidence, in one paragraph.** The engine is decision support: it never places orders. The 10-year results below come from one data source (Yahoo Finance), one market (mostly India, plus a few US ETFs), strategies that were designed and screened on that same history, and today's tax rules applied to all years. The crash guard now has a real-data replay (Section 8). The strategy switcher and the valuation and forecast overlays have been built and unit-tested on synthetic data only and have **no real-data results yet** (runs in progress). Treat every performance number as optimistic until shown otherwise.

---

## 1. Goal and investor context

- **Who:** one Indian tax-resident individual, salaried, in a high slab (the engine assumes 30% plus 4% cess by default, configurable). Technically capable, makes every final decision, no advisor in the loop for this part.
- **Portfolio:** small, taxable, mostly Indian equity ETFs bought about two years ago, a little single-stock, some bank fixed deposits, some mutual funds placed by a distributor (probably regular plans), and a small amount of restricted employer stock in a US broker account that can only be sold, not used to buy anything else. Very little is in US or other foreign assets so far; buying them would go through the Liberalised Remittance Scheme (LRS) to an overseas broker such as Interactive Brokers (IBKR).
- **Why the project exists:** the owner expects financially turbulent times and wants a periodic, rule-based answer to "should I rebalance now, into what, and what will it cost after tax?". The size of the portfolio is treated as a feature: no market impact, no mandate, no tracking error to a benchmark, and full control of when each gain is realised.
- **Non-goals:** it does not trade, predict single stocks, use leverage, sell options, or manage someone else's money.
- **Stated wishes that shaped the design:** consider Indian and US markets and other asset classes; count tax (short-term vs long-term capital gains) and every transaction cost; use "secretary problem" style stopping rules for timing; compare several strategies such as cross-sectional momentum; give a written reason for every recommendation.

## 2. System overview

Python, one command line. Daily or monthly run:

1. Load tax lots (units, buy date, buy price, per instrument) from a local file or a broker tradebook (FIFO lots).
2. Download adjusted daily closes (Yahoo Finance via `yfinance`), India VIX, and USD/INR. Isolated bad prints are dropped by a glitch filter.
3. A **policy** turns prices into target weights (Section 5).
4. A **crash guard** may override the target with a fast risk reduction (Section 8).
5. A **planner** turns target minus current weights into trades, choosing lots, costing tax and fees, and keeping a trade only if its expected benefit beats its cost (Sections 6 and 7).
6. A **timing layer** decides today vs later, using the secretary rule and a long-term-status wait rule (Section 9).
7. A report (offline HTML, six tabs) shows the decision, the plan, the steps, the track record, and the reasoning.

Continuous integration runs only unit tests, with no network.

## 3. Data

| Item | Source | Notes and known problems |
|---|---|---|
| Prices of NSE ETFs and stocks, US ETFs, gold, silver, INR=X, India VIX | Yahoo Finance (`yfinance`), adjusted close | Single provider; glitches on thin ETFs; adjusted prices embed dividends, so dividend tax is not modelled. History for newer ETFs is short (some begin 2019 to 2021), so the effective universe grows over the 10-year test. |
| US instruments in INR | Yahoo `INR=X` | Tax in India uses the SBI telegraphic-transfer buying rate on specific dates, not Yahoo's close. The engine approximates. |
| Cash proxy | Fixed yield (6.5% a year) | Models an arbitrage mutual fund, not market data. |
| Mutual fund NAVs | `mfapi.in` (mirror of AMFI) | Used for the regular-vs-direct plan cost gap. |
| Nifty 50 P/E, P/B, dividend yield | niftyindices.com (or a manual CSV) | Used only by the new valuation overlay. |
| India 10-year government yield | FRED monthly series, lagged 60 days to avoid look-ahead | Same. |
| Gold in Indian cities | scraped retail price pages | Only for physical-gold comparison, not for the strategies. |

## 4. Asset universe

Defined in a config file; each instrument has a tax class, a venue (cost model), a sleeve, and a flag `rotate` that says whether the rotation strategies may buy it.

- **India equity ETFs** (tax class: equity): Nifty 50 (two different AMCs' ETFs tracking the same index, used as same-day swap partners for tax harvesting), Nifty Next 50, Midcap 150, Momentum 30, Low Volatility 30, Bank, IT, PSU Bank, CPSE, Pharma.
- **Gold and silver ETFs** (tax class: other, 12-month long-term threshold).
- **NSE-listed international ETFs** (Nasdaq 100, FANG+, Hang Seng; "other" class). They can trade at large premiums to NAV when the industry's overseas investment limit is exhausted.
- **US-listed ETFs via IBKR** (foreign class, 24-month long-term threshold): SPY, QQQ, EFA, EEM, GLD, TLT.
- **Wider "explore" universe, `rotate: false`:** silver, platinum, copper, base metals, gold miners, lithium, rare earths, uranium, broad commodities, semiconductor ETFs, semiconductor stocks (US and Indian), Indian metals stocks. Allowing the rotation to pick from these made the 10-year result slightly worse (more turnover and tax), so they are only compared, not traded by default.
- **Cash:** a synthetic sleeve at 6.5% a year, modelled as an arbitrage fund.
- **Other assets handled outside the rotation:** bank fixed deposits (after-tax yield and early-break cost for a few banks), mutual funds from a consolidated account statement (regular vs direct plan cost gap), and a comparison of about 45 asset classes (flats, plots, farmland by state, a Dubai flat, physical gold, PPF/EPF/NPS, REITs and so on) as yearly after-tax cash-flow models under base, bear and bull scenarios. Those models have not been validated against any data and are explicitly illustrative.
- **Under construction, not merged at the time of writing:** a broader global universe through IBKR with other countries' markets, to be added only where the Indian tax treatment and the practical purchase route are well understood.

## 5. The strategies (policies)

All policies output target weights over the universe. Each one rebalances only if the planner's hurdle (Section 7) says the benefit exceeds cost, except risk-off exits.

Notation: P_t is price, r the return over a lookback, sigma the annualised volatility, SMA_n the n-day simple average, RF the cash yield.

1. **Buy and hold (baseline).** No rotation. Optionally with tax harvesting (Section 6).
2. **Dual momentum (Antonacci).** Hold Nifty if its 12-month return beats cash and price > SMA_200; otherwise hold gold if gold's own trend is positive; otherwise cash. Absolute momentum plus a relative choice among three assets.
3. **Cross-sectional momentum, top 3.** For lookbacks M in {126, 252} trading days, skipping the most recent 21 days: MR_M = (return over M) / (sigma over the same window). Z_M is the cross-sectional z-score of MR_M across eligible instruments; score = mean of Z_M. Take the top 3, require positive return over cash, weight by inverse volatility, cap sleeves (global equity 50%, gold 50%, commodity 25%, bonds 50%, metals 25%, semis 20%). Modelled on the NSE momentum index methodology.
4. **Trend filter plus volatility targeting.** Hold each asset only if price > SMA_210 (about 10 months); scale total exposure by min(1, target_vol / realised_vol_63d), target 10%, per-asset cap 35%. Faber (2007), Moreira and Muir (2017).
5. **Risk parity (inverse volatility)** over Nifty, low-vol, gold, S&P 500, long US Treasuries: w_i proportional to 1 / sigma_i over 126 days, cap 40%.
6. **Defensive asset allocation (Keller and Keuning).** Canary assets (EM equity, long Treasuries). If either has negative momentum, move some or all of the risky sleeve to defensive assets.
7. **Core-satellite (default family).** 60% core in a Nifty 50 ETF that is left alone for tax deferral, 40% satellite in the top 3 by cross-sectional momentum. Two versions: with a dual-momentum overlay on the core (rotates the core to gold or cash in a confirmed downtrend) and **without** the overlay (`core_xs`, the current default). The default was chosen after the first 10-year run showed the overlay hurt; see Section 11.
8. **Static mix.** Fixed weights (55% Nifty, 20% gold, 10% S&P 500, 15% cash), drift-triggered rebalance.
9. **Half Nifty, half risk parity.**
10. **Custom (keep what you hold).** Sells a holding only when at least 2 of 3 independent flags agree: technical downtrend, volatility trailing stop breached, weak momentum; trims single stocks above 10%; cuts equity by 50% when the market trend overlay is risk-off.
11. **Technical layer (reporting, not trading on its own).** 200/50-day trend and cross, 12-1 month momentum, distance from 52-week high, RSI, MACD, Bollinger. Only trend, momentum and 52-week-high drive verdicts; oscillators appear as timing hints because their evidence is weak.
12. **Valuation and forecast overlays (new, branch only).** Cut India equity weight, never below 50% of base and never levered, using: Nifty P/E percentile within its own expanding history (cut starts at the 70th percentile, full cut at the 95th); earnings yield minus the 10-year yield as an expanding z-score (cut from z = -1 to full at z = -2); and a walk-forward OLS forecast of next-year Nifty excess return from P/E percentile and 12-month momentum (cut when the forecast is below zero), refit monthly using only outcomes already known. Thresholds were set before any result was seen.

Design intent: a pre-registered, finite set; parameters are textbook values and were not tuned on the reported windows.

## 6. Indian tax model

Resident individual, post 23 July 2024 regime, updated for Budget 2026 (effective 1 April 2026). The Income-tax Act 2025 renumbers sections (111A becomes 196, 112A becomes 198) but I understand rates were unchanged. **I am not a tax professional; please check all of this.**

| Class | Instruments | Long term if held | Short-term gain | Long-term gain |
|---|---|---|---|---|
| equity | listed shares, equity ETFs, arbitrage funds | more than 12 months | 20% | 12.5% above Rs 1.25 lakh per financial year |
| other | gold, silver, NSE-listed international ETFs | more than 12 months | slab | 12.5%, no indexation |
| foreign | US-listed shares and ETFs | more than 24 months | slab | 12.5%, no indexation |
| debt | liquid and specified debt funds | never | slab | n/a |
| unlisted non-equity MFs bought after 1 Apr 2025 | gold or international fund-of-funds | more than 24 months | slab | 12.5% |

Plus 4% cess, surcharge configurable (capped at 15% on equity gains).

**Mechanics modelled**
- Set-off: short-term losses against any gain; long-term losses only against long-term gains. No carry-forward is modelled in the backtest.
- The Rs 1.25 lakh exemption is applied per financial year, per individual.
- Gains are measured in INR on both legs for foreign assets.
- **Lot selection is FIFO per ISIN** by default (my reading is that depositories consume the oldest units first, so "choose the cheapest lot" is not available in one demat account). A `specific` mode models multiple demat accounts.
- **Economic cost of tax** used by the planner: tax paid now minus the present value of the tax that would be paid anyway on a later sale (default horizon 5 years, discount rate 7%). A sale that merely brings forward a tax you would pay eventually is therefore cheaper than it looks, and a sale that converts a long-term gain into one is expensive.
- **Harvesting:** (a) use the annual long-term exemption by selling one Nifty ETF and buying a different AMC's ETF on the same index the same day (a real trade, new 12-month clock; no wash-sale rule in India as I understand it); (b) book losses only where they offset gains actually realised; the engine refuses a pointless long-term loss.
- **Gift to family:** units gifted to parents or adult children (not spouse, because of clubbing) realise gains in their own exemption. Documented as an edge, not automated.
- **LRS:** 20% TCS above Rs 10 lakh per year on investment remittances, credited against tax later; the planner warns when a plan crosses it. FX spread assumed at 0.35% each way.
- **Tax payment in the backtest:** paid from the portfolio at the start of the next financial year; advance-tax interest ignored.

**Known simplifications I want challenged:** today's rates applied to all ten years (rates differed before July 2024, and indexation existed before); dividends ignored for tax; TCS and Schedule FA/FSI reporting not modelled; no carry-forward of losses; no surcharge by default; no treatment of the 87A rebate; no GST treatment of brokerage beyond a flat 18% on fees; foreign-asset tax conversion at the wrong FX rate.

## 7. Cost model and the "is it worth trading" hurdle

Itemised per venue (config file):
- **NSE ETF:** zero brokerage assumed (discount broker), STT 0.001% on sell, exchange charge 0.00297%, SEBI 0.0001%, stamp duty 0.015% on buy, GST 18% on charges, DP charge Rs 15.93 per sell, half-spread 4 basis points.
- **NSE stock (delivery):** STT 0.1% each way, half-spread 3 bps.
- **IBKR US:** USD 0.005 per share, minimum USD 1, max 1% of value, SEC fee on sells, half-spread 2 bps, FX 0.35% each way.
- **Mutual funds:** stamp duty on buy; exit loads flagged.

**The hurdle for a rotation.** Expected benefit B = min(alpha_cap, shrink × trailing momentum spread) × horizon, with shrink 0.25, alpha_cap 12% a year and horizon 6 months. Execute if B ≥ switch_safety × (costs + economic tax cost), with switch_safety 1.25. Drifts under 3% of the portfolio are ignored. Risk-off exits skip the hurdle. These constants (0.25, 12%, 6 months, 1.25, 3%) are judgement, not estimates.

## 8. The crash guard (open pull request) and its 10-year result

An overlay on any policy. Purpose: leave quickly and cheaply when a bubble bursts, whatever the story. Six daily signal families on a market proxy (60% Nifty ETF, 40% S&P 500):

1. **Price damage:** below SMA_200 and/or 10% under the 52-week high.
2. **Speed:** down 5% in 5 days or 8% in 10.
3. **Volatility:** 20-day vol above 1.6× its one-year level and above 20%, or an India VIX spike.
4. **Breadth:** 60% or more of equity instruments below their SMA_200.
5. **Credit:** HYG/IEF ratio more than 2% under its 100-day average.
6. **Leaders cracking:** two of the three biggest 12-month winners have broken their 50-day average and are 10% or more off their highs.

A recent run-up (market in the top 5% of its 3-year extension within the last 4 months) lowers every bar by one point.

| Level | Needs | Action |
|---|---|---|
| 0 calm | | nothing |
| 1 watch | 2 points | no new money into risk |
| 2 elevated | 3 points, 3 families, one a stress signal | keep 75% of risk assets |
| 3 crisis | 5 points, 4 families | keep 25% of risk assets; stop waiting for long-term tax status |

The freed money goes to cash plus gold (only while gold is above its 200-day average, since gold also falls in liquidity squeezes). Whipsaw defences: families must agree, price alone cannot exceed "watch", a level steps down only after 15 calm days, and the level is recomputed from history so live and backtest agree. Exits go through the normal planner, so tax-smart lots and all costs apply. A drill shows what an exit would cost today and how far the market must fall further for it to pay for itself. Buy-and-hold books remember their pre-exit weights so an all-clear restores them.

**Status:** thresholds are textbook values chosen before any backtest and were not tuned on the test data. The 10-year real-data replay (`crash-test`, Oct 2016 to Oct 2026, Rs 10 lakh lump sum, lots, costs and today's tax rules, Yahoo data) has now been run.

| Strategy | After-tax CAGR | Max drawdown | Tax paid (Rs) | Costs (Rs) |
|---|---|---|---|---|
| Buy and hold Nifty ETF | 10.4% | -36.3% | 0 | 0 |
| Buy and hold + crash guard | 8.9% | -14.0% | 2,194 | 6,981 |
| Core-satellite (`core_xs`) | 12.7% | -23.3% | 120,709 | 26,149 |
| Core-satellite + crash guard | 9.8% | -18.4% | 76,750 | 42,344 |

Days at each level over the ten years: calm 1,721, watch 380, elevated 172, crisis 195.

**Falls of 10% or more in the buy-and-hold portfolio** (market peak-to-trough; guard flagged = first day at "elevated"):
- Aug to Oct 2018, market -12.2%: guard **never flagged**; guarded buy and hold lost -14.0%.
- Jan to Mar 2020, market -32.6%: flagged 41 days after the peak with the market only -7.2% down; guarded buy and hold lost -12.5% against -36.3% unguarded. This one episode does most of the work.
- Oct 2021 to Jun 2022, market -14.9%: flagged 129 days after the peak at -7.8%; guarded buy and hold lost -2.4%.
- Sep 2024 to Mar 2025, market -12.3%: guard **never flagged** until after the fall; guarded buy and hold -2.0% but the core-satellite plus guard lost -18.4%, worse than unguarded buy and hold (-15.2%).
- Jan to Mar 2026, market -9.9%: flagged at -6.0%; guarded buy and hold -9.3%.

**Whipsaw ledger:** the guard reached elevated or worse 8 times. Only 1 was justified (Feb 2020: a further -27.4% followed within 120 days). The other 7 were false alarms, during which the market *rose* 3% to 9% while the investor was out (for example +7.6% during May to Sep 2022 and +8.8% during Mar to May 2025).

**Reading:** the guard cuts the worst drawdown from -36% to -14% and costs 1.4 points a year after tax plus about Rs 9,000 of extra tax and fees. On the core-satellite default it reduces the drawdown from -23% to -18% but gives up 2.9 points a year, a poor trade. With only one large crash in the sample, the benefit rests on a single episode (COVID 2020); two falls of about 12% (2018 and 2024 to 2025) were missed entirely; and 7 of 8 alarms were false. I do not regard this as evidence that the guard is worth running, only as a cost-of-insurance estimate. The guard's own audit of the older strategies found that the default never sold its core, checks were monthly, and the regime label was decoration.

## 9. Execution and timing: the secretary rule and others

- **Secretary rule for fills.** Once a rebalance is approved, spread execution over a window of n = 10 trading days. Observe the first round(n/e) = 4 days without trading, then act on the first day whose price is better than everything seen so far (higher for a sell, lower for a buy), else act on the last day. For i.i.d. offers this maximises the chance of picking the single best day (about 1/e = 37%). Prices are closer to a random walk than i.i.d., so I expect it to reduce regret, not add return. It is compared against immediate and TWAP fills. In the 10-year test, secretary-rule fills were slightly worse than immediate (10.3% vs 11.3% a year after tax for the overlay version; difference within noise). Risk-off exits always execute at once.
- **Long-term-status wait rule (the one with real money in it).** If a lot becomes long term in d days, waiting saves (STCG rate − LTCG rate) × gain. Expected cost of waiting for a position V with volatility sigma ≈ V · sigma · sqrt(d/252) / sqrt(2π). Wait if saving > cost, with the cost doubled when the exit is a risk-off signal; overridden at crisis level.
- **Rebalancing rule:** drift bands plus signal changes, not calendar. New money is spent before anything is sold.
- **Signal checks:** monthly in the backtest by default; daily in the daily-follow simulation and the crash guard.

## 10. Choosing between strategies: the switcher (branch, not merged)

Question: can a rule pick which strategy to follow? The literature suggests weakly, and costs and tax eat most of it. Implemented and tested as meta-policies over strategy "sleeves": equal blend (1/N, the baseline); inverse volatility of each strategy's returns over 12 months; momentum switch (100% in the best 12-month strategy, switch only if a challenger leads by 3 points); Hedge / exponentiated-gradient weights on monthly outperformance, 40% cap. Moving money out of a sleeve costs 0.1% each way plus approximate tax on that sleeve's gain. A switcher is declared worth using only if all hold: bootstrap 90% range of its yearly gap over the equal blend is above zero; deflated Sharpe above 0.95 with the trial count including all rules and strategies; it wins at least 60% of rolling 3-year windows; no window is worse than −5 points a year. Otherwise "no reliable edge". **No real-data result yet.** Known limit: the sleeves were themselves designed and screened on the same history, and sleeve curves already include internal tax, so tax on sleeve switches is approximate.

## 11. Validation method and results

### 11.1 Method
- **Rolling robustness test (`validate`).** Start Rs 10 lakh in a Nifty 50 ETF, run every strategy day by day through the real planner with lots, costs and tax, over 10 years, then over 3-year windows starting every 12 months. Reported per strategy: whole-period after-tax CAGR, max drawdown, tax and costs, share of windows beating hold, median excess per year, worst window, early-half and late-half medians.
- **Label rules:** "robust edge" needs wins in at least 60% of windows, a positive median in both halves, and no window worse than −5 points a year; "promising" needs 70%+ wins but fails one test; "cuts drawdown at little cost"; otherwise "no reliable edge".
- **Statistical checks (open pull request):** 90% block-bootstrap interval for the annual excess over buy and hold; deflated Sharpe ratio (Bailey and López de Prado) using the number of variants tried; "robust edge" withheld when the interval includes zero. The overlap of the 3-year windows is acknowledged (windows are not independent; about three independent ones fit in ten years).
- **Daily-follow simulation:** the engine is run each day on data up to that day, every order is followed, tax is paid each April, and the remaining holdings are taxed as if sold on the last day. Reported for 10, 5 and 2 years, daily vs monthly checking.
- **Out-of-sample discipline claimed:** parameters fixed in config before results; but see weaknesses.

### 11.2 Results so far (Yahoo data, today's tax rules, Rs 10 lakh lump sum, 10 years to Oct 2026)

| Strategy | After-tax CAGR | Max drawdown | Tax + costs (Rs) | Windows won | Verdict |
|---|---|---|---|---|---|
| Buy and hold Nifty ETF | 10.4% | −36.3% | 0 | n/a | baseline |
| Buy and hold + tax harvesting | 10.9% | −36.3% | 8,460 | 75% | robust edge (small, +0.3 to +0.5 points) |
| Keep holdings, exit on technicals | 5.3% | −10.0% | 1,734 | 25% | no reliable edge |
| Dual momentum (Nifty/gold/cash) | 10.8% | −24.5% | 108,125 | 38% | no reliable edge |
| Cross-sectional momentum, top 3 | 15.0% | −32.6% | 279,597 | 62% | no reliable edge |
| Trend filter + vol targeting | 11.2% | −23.8% | 193,767 | 25% | no reliable edge |
| Risk parity | 12.7% | −14.7% | 12,697 | 38% | cuts drawdown at little cost |
| Defensive asset allocation | 10.4% | −24.7% | 333,507 | 38% | no reliable edge |
| Core-satellite, immediate fills | 11.3% | −24.9% | 138,799 | 38% | no reliable edge |
| Core-satellite, secretary fills | 10.3% | −25.2% | 143,884 | 38% | no reliable edge |
| Core-satellite, TWAP fills | 10.1% | −24.7% | 161,580 | 38% | no reliable edge |
| Core-satellite without core overlay (`core_xs`) | 12.7% | −23.3% | 146,537 | 75% | promising, not proven |
| Static mix 55/20/10/15 | 12.0% | −22.9% | 11,063 | 38% | cuts drawdown at little cost |
| Half Nifty + half risk parity | 12.1% | −24.1% | 12,047 | 38% | cuts drawdown at little cost |

The last three rows were added after seeing earlier results, so they were chosen on the same data and are optimistic.

**Daily-follow simulation of the default (`core_xs`), after tax and fees:**

| Horizon | Hold | Engine daily | Engine monthly | Worst fall (hold / engine) |
|---|---|---|---|---|
| 10 years | 10.3% | 13.1% | 12.7% | −35.2% / −21.8% |
| 5 years | 5.1% | 11.1% | 11.6% | −15.8% / −20.0% |
| 2 years | −2.7% | 4.9% | 5.2% | −14.9% / −20.7% |

A second table runs every strategy daily over the same horizons. Rankings change completely between horizons: over 2 years dual momentum shows +35 points a year over holding (an implausible number driven by a short window, a gold rally and a 6.5% cash proxy during an Indian equity drawdown); over 10 years it is only +1.0.

### 11.3 My own reading
- Rotation strategies mostly **do not** reliably beat holding after Indian tax. Tax harvesting is the only edge that repeated, and it is worth a few tenths of a point a year.
- Simple diversification (static mix, risk parity) cut the worst drawdown from about −36% to between −15% and −23% at small cost.
- The default policy was promoted to default after it topped a table of 14 variants. That is a selection effect.

## 12. Does a good mutual fund beat this engine?

For the core equity book, probably not. S&P's SPIVA India scorecard for year-end 2025 shows 76% of large-cap and 79% of mid/small-cap funds trailing their benchmark over 10 years, and about 27% of funds dying in that decade. A fund's internal churn is not taxed in the investor's hands; every rotation the engine makes is. The engine's cross-sectional momentum paid about Rs 2.3 lakh of tax and Rs 0.5 lakh of costs on a Rs 10 lakh start, versus a Nifty 200 Momentum 30 index fund giving the same tilt with tax-free internal churn. Conclusion of the project's own notes: hold the core in a low-cost Nifty index ETF or fund; use the engine for harvesting, lot-aware timing, gold/cash/US allocation, a risk-off rule, LRS and event trades.

## 13. Small-investor edges considered

Tax edges: annual exemption harvest via the two-AMC swap (worth roughly 12.5% of the exempted gain each year); family exemptions via gifts; arbitrage fund instead of liquid fund for cash; loss harvesting without a wash-sale rule; wait for long-term status; spend new money first; employer NPS and VPF. Event edges: small-shareholder quota in tender-offer buybacks (back as capital gains since April 2026), momentum-index reconstitution front-running (the NSE rebuild is replicable from public prices; flows were about Rs 16,000 crore in December 2025), index inclusion, delisting and open offers, IPO retail quota. Global: Ireland-domiciled UCITS ETFs over US-listed (15% vs 25% dividend withholding, no US estate-tax exposure), avoid NSE-listed international ETFs at a premium, LRS TCS threshold, GIFT City funds, FX cost. Market-structure: go to cash or gold when trend breaks, limit orders near NAV in panics, REITs/InvITs. Explicitly rejected: option selling (one Nifty lot is about the whole portfolio and F&O STT rose in April 2026), do-it-yourself cash-futures arbitrage, HFT-style gaps, dividend stripping. Changes in 2026: exchange-bought SGBs lost tax-free redemption; buybacks taxed as capital gains again; F&O STT up.

**Forecast and fundamental tests.** The valuation overlays in Section 5 come with a study (`forecast`) that (1) checks, before any trading, whether P/E percentile, earnings-yield spread and the regression forecast predict Nifty returns out of sample (rank correlation, number of independent periods, out-of-sample R² against the expanding mean), (2) runs each as an overlay on a Nifty-only strategy and on `core_xs` through the same lot, cost and tax engine, and (3) applies a White-style stationary-bootstrap reality check across all variants tried. Not yet run on real data. With roughly eighteen years of Nifty valuation history there are only about eighteen non-overlapping one-year outcomes, so I expect low power whatever the answer.

## 14. Known weaknesses I already suspect (please confirm, rank, and add)

1. **Selection and overfitting.** Fourteen variants screened on one ten-year history; the default was picked from the table. Deflated Sharpe and the bootstrap now exist but have not been re-run on real data for the full set; tests (crash guard, switcher, valuation) add more trials on the same history.
2. **Hindsight universe.** The ETF list contains instruments that exist and are liquid today (survivorship), and the Nifty and the 2016 to 2026 period include a strong run for Indian equity. Candidates such as semiconductors and uranium were added because they have done well.
3. **Single data source.** Yahoo only, adjusted closes, known glitches, possible survivorship in tickers and adjusted-dividend treatment. No second source reconciliation.
4. **Tax rules applied backwards.** Today's regime used for all years. Tax law, indexation, holding periods and surcharge differed.
5. **Regime-dependence.** Results hinge on a few episodes (2020 crash, 2022 sideways, the recent drawdown). Rolling 3-year windows overlap heavily.
6. **Short and conflicting horizons.** 2-year and 5-year tables rank strategies very differently from the 10-year table.
7. **Fixed cash yield and fixed FX spread** hide real variance; arbitrage-fund returns are not 6.5% in every regime.
8. **ETF liquidity and tracking** modelled by a flat half-spread; wide spreads in panics are not modelled; NSE-listed international ETFs can trade at 5% to 10% premiums.
9. **No advance-tax timing, no dividends, no TCS cash drag, no Schedule FA, no loss carry-forward.**
10. **Secretary rule** is applied to a non-i.i.d. price series; it may be pure behavioural scaffolding.
11. **Crash guard:** real-data replay shows 7 false alarms in 8, two missed ~12% falls, and a benefit that rests on one crash (2020). Its thresholds are untuned, and tuning them on this history would overfit.
12. **Behavioural risk:** the user, not the engine, executes; the report's complexity may itself drive bad overrides.
13. **Model risk in the asset-class comparison** (flats, farmland, Dubai flat): inputs are assumptions, not data.
14. **Regulatory risk:** I did not check whether a retail user running this on someone else's money would need registration (this is for one person's own money).

## 15. Questions for the critic

**Method**
1. Given 14 to 30 variants tried on a single 10-year Indian history, what is the correct way to state the probability that any of them has a real after-tax edge? Is deflated Sharpe plus a block bootstrap enough, or should I demand a full out-of-sample period, a different country's data, or a pre-registered live paper-trading period of N months? Which N?
2. Is a 3-year rolling window with a yearly step a sensible unit? How would you correct for the overlap?
3. How should I measure the value of the "core is never sold" rule versus a trend overlay when the sample contains a single major crash (2020) and one long flat patch?
4. Would you replace the single-start lump-sum test with a Monte Carlo over block-resampled returns, a regime-based test, or a multi-start test with periodic contributions (since a real saver adds money)?

**Strategy**
5. Is core-satellite with 60% passive core and 40% cross-sectional momentum defensible for a small taxable investor, or is a static 55/20/10/15 mix plus annual harvesting strictly better after tax and effort?
6. Is cross-sectional momentum on a universe of broad ETFs (a handful of assets, mostly correlated) even a meaningful implementation of the factor? What should the universe be?
7. Which of the six crash-guard signals are redundant, lag too much, or are proxies for the same thing? Which well-documented crash or bubble indicators am I missing (credit spreads in India, FII flows, margin debt, term spread, valuation extremes)? Would you drop the guard entirely and rely on a static allocation with a gold and cash sleeve?
8. Is the idea of an automatic strategy switcher sound at all, or should it be replaced by a fixed blend?
9. Do valuation (P/E percentile, earnings yield minus bond yield) and a simple regression forecast carry any out-of-sample information for Nifty one-year returns? If you know published tests for India, please cite them.
10. Is the secretary rule useful anywhere here (execution timing, deciding when to rebalance, picking an entry from a set of offers) or is it decoration? What stopping problem do you think actually fits "when should I realise a gain"? (I considered long-term-status waiting as the one real optimal-stopping problem.)

**Tax and legal**
11. Are the tax classes, holding periods, rates and the FIFO assumption right as of October 2026? In particular: (a) is same-day sale of one Nifty ETF and purchase of another AMC's ETF tracking the same index fully effective as an exemption harvest in India, with no GAAR or substance risk; (b) is gifting units to adult children or parents for their exemption safe, and what documentation matters; (c) are arbitrage funds still taxed as equity; (d) the treatment of NSE-listed international ETFs and unlisted international funds of funds; (e) any 2026 changes I missed.
12. For buying US or European ETFs via LRS: what is the right instrument choice for an Indian resident (Ireland-domiciled UCITS ETF on the London exchange vs a US-listed ETF), and what are the tax and reporting obligations (Schedule FA, Form 67 and foreign tax credit, TCS, Form 15CA/CB at the bank)? What dividend withholding applies to each?
13. Which other country markets would you consider adding, given tax treatment and a realistic purchase route from India?

**Practicality and risk**
14. What is the biggest way this system could lose the owner real money that none of the above covers?
15. If you could keep only three components, which would they be?

## 16. Reference list of the main literature the design leans on

Faber (2007) trend rule; Moskowitz, Ooi and Pedersen (2012) time-series momentum; Hurst, Ooi and Pedersen (2017); Antonacci dual momentum; Daniel and Moskowitz (2016) momentum crashes; Barroso and Santa-Clara (2015) risk-managed momentum; Moreira and Muir (2017) and Harvey et al. (2018) volatility targeting; Asness, Frazzini and Pedersen (2012) risk parity; Keller and Keuning (2018) defensive asset allocation; George and Hwang (2004) 52-week high; DeMiguel, Garlappi and Uppal (2009) 1/N; Bailey and López de Prado (2014) deflated Sharpe; White (2000) reality check; S&P SPIVA India scorecard; SEBI studies on retail F&O losses. Only titles and abstracts were reviewed for several of these; please check the claims.
