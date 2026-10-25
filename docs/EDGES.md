# Edges a small personal investor can actually use

_Last researched 25 Oct 2026. Includes Budget 2026 changes, which took effect 1 Apr 2026._

Large funds can't use most of these. They are held back by mandates, tracking error, capacity,
or simply by being a different kind of taxpayer. Each item lists what it is worth, what it
needs, and the catch. **Tax points are my reading of public sources, not advice; confirm with a
CA.** From 1 Apr 2026 the Income-tax Act 2025 replaced the 1961 Act. Sec 111A is now s.196 and
Sec 112A is now s.198, and "previous year"/"assessment year" became a single "tax year"
([mapping](https://taxgarden.in/blog/old-vs-new-income-tax-sections-2026-mapping-table)). Rates
did not change: STCG 20%, LTCG 12.5% above Rs 1.25 lakh
([Business Standard](https://www.business-standard.com/budget/news/budget-2026-ltcg-tax-rates-unchanged-for-fy27-fm-sitharaman-126020100424_1.html)).

The engine automates the items marked ⚙.

## Is running our own engine better than buying a good fund?

Short answer: for the core of the equity book, no. A low-cost index fund or ETF is the right default, and
this engine's validation (`reports/validation.md`) shows its rotation strategies do not reliably beat holding
one after Indian tax. Our own setup earns its place in the places below, and loses to a fund in the places after that.

**The odds on "a good active fund".** In S&P's SPIVA India scorecard for year-end 2025, 76% of large-cap funds,
79% of mid/small-cap funds and 83% of ELSS funds trailed their benchmark over 10 years; over 5 years it was 84%
for large-cap. About 27% of funds across categories did not survive the 10 years
([SPIVA India year-end 2025](https://www.spglobal.com/spdji/en/spiva/article/spiva-india-year-end-2025/)).
Single years can flatter active funds (only 12% of mid/small-cap funds lagged in 2025), and the large-cap benchmark
is a large-mid index, not Nifty 50, so read it as a rough guide. A fund that "has been good" is picked with
hindsight; roughly one in four of them beats the index over a decade, and nobody can tell which in advance. So the
real contest is our engine against an index fund, not against the best fund.

**Where a small corpus gives us a structural edge**

1. **Tax timing is ours.** Funds pass gains straight through; we choose when to realise them: the yearly LTCG
   exemption harvest (A1), loss harvesting with no wash-sale rule (A4), waiting for long-term status (A5),
   spending new money before selling (A6), and gifting units to family (A2). Validation: buy and hold plus
   harvesting gave about 0.4 points a year over plain holding (10.9% vs 10.4% after tax), the only edge that
   repeated across windows (and it has not yet been tested for significance on this data).
2. **No capacity limit and no mandate.** Funds hold a benchmark and a style; we can sit in cash, gold or
   US assets when trend breaks (D1). Small-cap funds have closed to lump sums because there are too few
   liquid small caps for their size, so impact cost is real for them and not for Rs 50k positions
   ([Finnovate](https://www.finnovate.in/learn/blog/why-are-mutual-funds-shutting-inflows-into-small-cap-funds), 2023).
3. **Global access funds cannot give.** Indian funds are capped at USD 7 billion of overseas investment in total,
   reached in January 2022; each fund house is frozen at its early-2022 headroom. By July 2026, 54 of 66
   international funds no longer took fresh money, and India-listed global ETFs trade at premiums
   ([Value Research](https://www.valueresearchonline.com/stories/228977/most-international-funds-have-shut-12-still-take-your-sip/)).
   The LRS route (C-section) is open to an individual, at the cost of 20% TCS above Rs 10 lakh a year.
4. **Event edges that need small size**: tender buyback small-shareholder quota (B1) and index
   reconstitution (B2).
5. **One book across every asset class.** Funds optimise one slice. The engine weighs equity, gold, US,
   cash and the real-asset comparison against each other, with your actual tax lots and slab.

**Where a fund wins, and we should use it**

1. **Fund-level churn is not taxed.** A mutual fund is a pass-through: buying and selling inside it triggers no
   tax for you ([Value Research](https://www.valueresearchonline.com/stories/27590/mutual-funds-don-t-pay-taxes/)).
   Every rotation we run realises gains in our own name at 20% (short term) or 12.5% (long term). That is why the
   10-year validation shows cross-sectional momentum paying about Rs 2.3 lakh of tax and Rs 0.5 lakh of costs on a
   Rs 10 lakh start. For factor exposure, a Nifty200 Momentum 30 index fund (offered by several AMCs) gets the same
   rule-based tilt with tax-free internal churn. Prefer it to our own `xs_momentum` unless validation shows the DIY
   version with a bootstrap range above zero. Switching between funds is still a taxable redemption.
2. **Costs are falling and small.** SEBI's 2026 regulations split the expense ratio into a base ratio, brokerage
   and statutory levies, lowered the base cap by about 10 to 15 basis points, and cut the cash-market brokerage cap
   from 8.5 to 6 basis points; one expert expects equity fund expense ratios to fall by roughly 5 to 7 basis points
   ([Outlook Money](https://www.outlookmoney.com/invest/mutual-funds/sebi-2026-mutual-fund-regulations-bring-clearer-costs-not-cheaper-funds)).
   Direct Nifty 50 index funds charged about 0.1% in 2020; tracking difference ran 0.3% to 0.8% a year and did not
   follow the expense ratio ([freefincal](https://freefincal.com/which-nifty-index-fund-has-the-lowest-tracking-error/), 2020 data).
   Our own ETF trades add spread, STT and DP charges on every sale, which `pe/costs.py` itemises.
3. **Small caps, debt and anything illiquid or fiddly**: use a fund. Single stocks at our size carry 0.1% STT each way
   and wide spreads, and the engine's validation does not support DIY stock picking.
4. **Discipline.** A fund does not tempt you to act on a bad week. The engine only advises; the cost of overriding
   it is yours.

**Bottom line.** Hold the core in a low-cost Nifty index ETF or fund, which is what the engine's default does. Use
the engine for the things a fund cannot do for you: harvesting, lot-aware timing, gold/cash/US allocation, a
risk-off rule, LRS and event trades. Expect a few tenths of a point a year from tax work and a shallower drawdown
from simple diversification (in validation the static mix and risk parity cut the worst fall from about -36% to
about -15% to -23% at little cost), not outperformance from stock selection or rotation. Buy factor tilts through
a fund, not through our own rotation, unless the validator says otherwise.

**Lot selection is FIFO, not a free choice.** Depositories and the tax filing treat a sale as consuming the oldest
units of an ISIN first, per demat account or folio, for shares and fund units alike
([5paisa](https://www.5paisa.com/stock-market-guide/tax/fifo-in-demat), [Outlook Money](https://www.outlookmoney.com/tax/tax-saving-tips-why-having-only-one-demat-account-can-make-you-lose-profit-from-your-equities);
these are secondary sources, so confirm with a CA). The engine used to pick the cheapest lot; it now defaults to
`tax.lot_method: fifo` and harvests only the oldest lot of each holding. Holding lots in separate demat accounts is
the way to regain choice, and `lot_method: specific` models that case. Earlier validation numbers assumed free lot
choice and should be re-run.


## A. Tax edges: the largest and most reliable

| # | Edge | Rough value for you | Notes |
|---|---|---|---|
| A1 ⚙ | **Harvest the Rs 1.25 lakh LTCG exemption every year.** Sell NIFTYBEES and buy SETFNIF50 the same day (or the reverse) | ~Rs 16k of future tax saved per year | Same index from a different AMC, so the trade is real. Buying back the *same* ETF the same day nets off as intraday and books nothing. The new units start a fresh 12-month clock. |
| A2 | **Use every family member's exemption.** Gift units to parents or adult children (no clubbing); they realise gains in their own name | Rs 1.25 lakh more tax-free gain per person per year | Gifts to a spouse are clubbed back to you. A resident with low income can also set unused basic exemption against s.196/198 gains, but the 87A rebate does not apply to them ([Tata MF](https://www.tatamutualfund.com/blogs/post-budget-2026-new-tax-map-equity-investors)). Document gifts. |
| A3 ⚙ | **Hold cash in an arbitrage fund, not a liquid fund** | ~0.5–1.5%/yr after tax on cash at a 30% slab | Arbitrage funds are taxed as equity (20%, or 12.5% after a year), while liquid funds are taxed at your slab. Hold ~6 months or more; returns can dip when futures premiums vanish (e.g. March 2020) ([PrimeInvestor](https://primeinvestor.in/reports/arbitrage-funds-vs-liquid-funds-which-to-invest/)). The engine's CASH sleeve assumes this. |
| A4 ⚙ | **Tax-loss harvesting with no wash-sale rule** | Varies | Only where the loss offsets gains you have actually realised. Booking a long-term loss with nothing to set it against is a trap, and the engine refuses it. |
| A5 ⚙ | **Wait for long-term status when it's close** | 7.8% of the gain (20.8% vs 13%) | Optimal-stopping rule in `pe/stopping.py`. |
| A6 ⚙ | **Rebalance with new money first** | Avoids realising gains at all | Put monthly savings in `cash_inr`; the planner spends it before selling anything. |
| A7 | **Salary-side: employer NPS (up to 14% of basic, deductible in the new regime) and VPF** | At 30% slab, the largest risk-free return on the list | VPF/EPF interest stays tax-free on contributions up to Rs 2.5 lakh/yr. Both lock money up. Check your employer's policy and the current limits. |

## B. Event arbitrage (needs attention, short holding periods)

| # | Edge | Why it works for small investors | Catch |
|---|---|---|---|
| B1 | **Tender-offer buybacks, small-shareholder quota.** 15% of every tender buyback is reserved for holders worth ≤ Rs 2 lakh on the record date, and that quota's acceptance ratio is usually far higher than the general one. | **Back since 1 Apr 2026:** proceeds are taxed again as capital gains on the profit only, not as dividend at slab ([Tata MF](https://www.tatamutualfund.com/blogs/post-budget-2026-new-tax-map-equity-investors)). Example: Wipro (record date 5 Jun 2026), buyback price 23% above market, estimated retail acceptance 45–80%, realistic return 8–18% over 2–3 months ([INDmoney](https://www.indmoney.com/blog/wipro-buyback-record-date)). | Shares that aren't accepted come back to you at market price, which often falls after the buyback. Stay under Rs 2 lakh *at the record-date price*, with a buffer. Bought shortly before the record date, the accepted portion is STCG at 20%. This also applies to your TCS: TCS runs buybacks regularly. |
| B2 | **Front-running momentum-index reconstitution.** Nifty200 Momentum 30 is rebuilt each June and December from public prices; passive funds then buy the entrants and sell the exits. Dec 2025 flows were about Rs 16,000 crore round trip, larger than a day's volume in 27 stocks ([Business Standard](https://www.business-standard.com/amp/markets/news/nifty200-momentum30-a-flip-of-index-switch-jolts-16k-cr-across-the-grid-125121400388_1.html)). | The score is replicable. Run `python main.py predict-index nifty200.csv --current mom30.csv` in May/November, before the announcement. A Rs 50k position has no market impact. | Eligibility filters aren't modelled, crowded trades get priced in early, and gains are STCG. Keep it small. |
| B3 | **Index inclusion (Nifty 50/Next 50, MSCI)** | Same passive-flow logic ([DSIJ](https://insights.dsij.in/dsijarticledetail/index-inclusion-and-exclusion-why-getting-added-to-nifty-moves-a-stock-more-than-its-quarterly-numbers-id010-56121)) | Widely watched now, so most of the move happens between announcement and effective date. |
| B4 | **Open offers / delisting offers** | Small holders can tender at the offer price | Delisting uses reverse book-building, so the final price is uncertain and the deal can fail. Treat it as event risk, not arbitrage. |
| B5 | **IPO retail quota using multiple family PANs** | Allotment is a lottery per application, so more PANs mean more chances | Average listing gains hide many flat or negative listings. STCG 20%. Money is blocked during the IPO, not debited. |

## C. Global investing edges (via IBKR / LRS / GIFT City)

| # | Edge | Notes |
|---|---|---|
| C1 | **Prefer Ireland-domiciled UCITS ETFs (on the LSE) to US-listed ones** | 15% US dividend withholding inside the fund instead of 25%. Accumulating share classes avoid annual dividend tax in India. Not US-situs, so no US estate-tax exposure (which applies to non-residents above USD 60k). The engine uses US tickers only because their price history is free. |
| C2 | **Never buy NSE-listed international ETFs at a premium; sell them into one** | MON100/MAFANG-type ETFs have traded at large premiums to iNAV when overseas limits stopped new units, and the BSE has warned investors about it ([1 Finance](https://1finance.co.in/blog/why-are-international-etfs-trading-at-a-premium-understand-the-concept-of-inav/), [Times of Oman/BSE](https://timesofoman.com/article/177355-bse-warns-investors-against-buying-international-etfs-at-inflated-prices)). If you hold one at a fat premium, selling it and buying the same exposure via LRS captures the gap. |
| C3 ⚙ | **Manage the Rs 10 lakh LRS TCS threshold** | 20% TCS on remittances above Rs 10 lakh per year for investment. It's adjustable against tax, but your cash is locked until you file. GIFT City routes count toward the same LRS limit and TCS ([Finnovate](https://www.finnovate.in/learn/blog/gift-city-vs-lrs-global-investing-india)). The planner warns when a plan crosses the threshold. |
| C4 | **GIFT City (IFSC) funds** | Low minimums (e.g. PPFAS's GIFT fund at USD 500) and possibly simpler reporting, since some structures may not need Schedule FA. Same LRS/TCS treatment. Confirm tax treatment per product. |
| C5 | **Keep FX costs low** | Bank INR→USD spreads can be 0.5–1%. Convert once and rotate inside IBKR; the engine charges FX only on money actually moving between currencies. |

## D. Market-structure and flexibility edges

| # | Edge | Notes |
|---|---|---|
| D1 ⚙ | **Go to cash or gold when the trend breaks** | A large-cap fund can't. This is the core flexibility edge, and what every overlay in the engine uses. |
| D2 | **Buy ETFs with limit orders near iNAV during panics** | ETF quotes widen in fast markets. A fund can't wait for a better price; you can. |
| D3 | **Momentum/mid-cap names with no market impact** | Your size doesn't move prices. The catch is momentum crash risk (THEORIES.md section 4). |
| D4 | **REITs/InvITs as a diversifier** | Interest components are taxed at slab. The Taxation Laws (Amendment) Bill 2026, passed by the Lok Sabha in Aug 2026, would keep dividend components exempt even when SPVs move to the new corporate regime; it is not law until assented ([Business Today](https://businesstoday.in/personal-finance/tax/story/reit-invit-payouts-wont-become-fully-tax-free-which-components-will-still-be-taxed-548618-2026-08-11)). |

## Changed in 2026: edges that weakened or reversed

- **Sovereign Gold Bonds bought on the exchange lost tax-free redemption from 1 Apr 2026.** Only
  original subscribers who hold to maturity keep it; secondary buyers now pay LTCG on the gain
  ([Business Today](https://www.businesstoday.in/amp/personal-finance/investment/story/secondary-market-for-sgbs-is-no-longer-a-tax-haven-ca-flags-important-rule-shift-from-april-1-518131-2026-02-26),
  [Value Research](https://www.valueresearchonline.com/stories/228715/sgb-tax-change-budget-maturity-exemption-secondary-market/)).
  Secondary SGBs are now only worth it if the discount to gold more than covers that tax.
  Otherwise a gold ETF is simpler.
- **Buyback tendering is back on**, as covered in B1. The old advice to avoid buybacks applied
  only to Oct 2024 – Mar 2026.
- **F&O got more expensive again:** STT on futures went from 0.02% to 0.05%, and on options from
  0.10% to 0.15% of premium, from 1 Apr 2026 ([Tata MF](https://www.tatamutualfund.com/blogs/post-budget-2026-new-tax-map-equity-investors)).

## Looks like an edge, isn't (at this portfolio size)

- **Option selling or covered calls on NIFTYBEES.** One Nifty lot is about Rs 15–20 lakh of
  exposure, roughly your whole portfolio, and costs went up in 2026.
- **Cash–futures arbitrage done yourself.** It earns about the risk-free rate and is taxed as
  business income at your slab. An arbitrage fund does it cheaper and with equity taxation.
- **NSE vs BSE price gaps, intraday scalping, HFT.** Latency and costs make these negative for
  retail traders.
- **Dividend or bonus stripping.** Blocked by anti-avoidance rules.
