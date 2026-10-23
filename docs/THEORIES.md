# Which theories hold up in turbulent markets

This is the reasoning behind the policies in the engine, ordered by how much weight I'd put on
them for a ~Rs 17 lakh portfolio heading into a rough patch. The backtest lets you check each
one on real data; one year is a single sample, so lean on the long-run evidence below as much
as on that table.

## 1. Time-series trend following (absolute momentum) — the strongest crash evidence

*Policies: `dual_momentum`, `trend_vol`, the overlay in `core_satellite`.*

Hold an asset only while it trades above its long-term average (or beats cash over 12 months);
otherwise step aside. Evidence: Faber (2007) on the 10-month moving average, Moskowitz, Ooi &
Pedersen (2012) "Time Series Momentum", Hurst, Ooi & Pedersen (2017) "A Century of Evidence on
Trend-Following". Trend rules historically did their best work *during* long bear markets
(2000–02, 2008), which is the "crisis alpha" people talk about.

Weaknesses: whipsaw in choppy, sideways markets (several small losses from in-and-out trades),
and it is always late — it exits after the first leg down and re-enters after the first leg up.
In India every whipsaw can also trigger tax, which is why the engine puts a tax/cost hurdle on
every non-risk trade.

## 2. Volatility targeting — cut exposure when volatility jumps

*Policy: `trend_vol` (scales the whole book to a target volatility).*

Volatility clusters: a volatile week is usually followed by another. Moreira & Muir (2017)
"Volatility-Managed Portfolios" and Harvey et al. (2018) "The Impact of Volatility Targeting"
find that scaling equity exposure down when realised volatility rises reduces the worst
drawdowns more than it reduces return. It reacts faster than a 200-day average, which helps
in a fast crash (March 2020 style).

## 3. Diversify by currency and asset class — gold and USD assets matter for an INR investor

*Policies: `risk_parity`, and the universe of every rotation policy.*

In global risk-off episodes the rupee tends to weaken, so USD assets (via IBKR/LRS) and gold
(priced in USD) cushion an INR portfolio exactly when Indian equities fall. Risk parity
(Asness, Frazzini & Pedersen 2012) weights each asset class by inverse volatility so no single
market dominates the risk, and it needs no forecast. Caveat: 2022 showed bonds and stocks can
fall together when inflation is the shock; gold and cash carried the defence then.

## 4. Cross-sectional momentum — keep it, but small and volatility-scaled

*Policies: `xs_momentum`, the satellite in `core_satellite`.*

Momentum has the largest long-run premium in Indian factor data (the blueprint cites 7–9%/yr
over Nifty 500), but it **crashes in turbulent markets**, especially in sharp rebounds after a
bear market, when last year's losers rip (Daniel & Moskowitz 2016, "Momentum Crashes").
Barroso & Santa-Clara (2015) show that scaling momentum by its own recent volatility removes
most of that crash risk. The engine keeps it to a satellite, applies an absolute-momentum
filter (nothing that trails cash), and uses inverse-volatility weights.

## 5. Breadth "canary" signals — an early warning

*Policy: `daa` (Keller & Keuning 2018, Defensive Asset Allocation).*

Emerging-market equities and bonds often weaken before broad equity sell-offs. DAA moves part
or all of the book to defensive assets when those canaries have negative momentum. It is more
sensitive than a single trend filter (more false alarms, earlier exits).

## 6. Low volatility / quality — smaller drawdowns, slower recovery risk

*`LOWVOLIETF` is in the universes.* The blueprint's table shows Nifty Low Vol 50 falling 44%
in 2008 vs 70% for momentum, and recovering in 7 months instead of 65. It is a sensible
defensive tilt inside the equity sleeve.

## 7. Rebalancing with bands, not calendars — and tax-aware

Rebalance only when drift or a signal is large enough to matter after costs and tax. The
engine's hurdle compares a deliberately haircut estimate of the benefit with trading costs
plus the *economic* cost of tax (tax paid now minus the present value of the tax you'd pay
later anyway). Risk-off exits bypass the hurdle, because their job is to avoid a 30–50%
drawdown rather than earn a few percent.

## 8. The secretary rule — useful discipline, not a source of return

Once a rebalance is approved, the engine can spread execution over a 10-day window: watch the
first 4 days, then act on the first day that beats every price seen. This is optimal for
picking the single best of n independent offers, but prices are closer to a random walk, so
don't expect extra return from it. Its real use is behavioural: a fixed rule for "when"
stops second-guessing. The backtest compares it with immediate and TWAP fills; if it doesn't
help on real data, set `timing.execution: immediate`. Risk-off exits always execute at once.

The second stopping rule (wait for long-term status) is where real money is: if a lot turns
long term in d days, waiting saves (STCG − LTCG) × gain, and the expected cost of waiting is
roughly σ·√(d/252)/√(2π) of the position value. The engine waits only when the saving wins.

## 9. Technical analysis: what deserves weight

The engine's technical layer leans on the indicators with real out-of-sample evidence: the
long-term trend (price vs 200-day average), 12-1 month momentum, and nearness to the 52-week
high (George & Hwang 2004: stocks near their highs keep outperforming because investors anchor
on the high). Oscillators such as RSI, MACD and Bollinger bands have weak and inconsistent
evidence after costs in most markets. The report shows them only as timing hints, e.g. "don't
sell into an RSI-30 washout" or "don't chase an RSI-80 spike", and they never trigger a trade
on their own. The `custom` policy sells a holding only when independent signals agree.

## What to avoid right now

- **Selling options / F&O for income.** Lot sizes are Rs 15–20 lakh; one gap wipes out a
  small book. SEBI data: ~90% of individual F&O traders lose money.
- **Leverage**, including margin against pledged ETFs, in a volatile regime.
- **Pure, unscaled momentum** in a turbulent market (see 4).
- **Frequent rotation of a long-term holding**: your NIFTYBEES lots are long term, so each
  switch realises gains at 12.5% + cess beyond the Rs 1.25 lakh exemption.

## Suggested starting configuration

`core_satellite` with the dual-momentum overlay on the core (the default), or `trend_vol` if
you want one rule that de-risks faster. Choose after running `python main.py backtest` on real
data and comparing drawdown and after-tax liquidation return, not return alone.
