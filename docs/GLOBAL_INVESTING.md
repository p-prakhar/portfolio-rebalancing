# Buying US and European assets from India (IBKR first)

For a resident individual who can only *sell* in their employer-stock account and needs another route to buy global assets.
The engine never places orders; this is the manual playbook it assumes. Rules were checked in October 2026 (Budget 2026,
Income-tax Act 2025 in force from 1 April 2026). Items marked **[verify]** came from a single secondary source or are
my reading of how a rule applies. Confirm those with a chartered accountant before the first transfer.

## 0. The short version

1. Open an IBKR individual **cash** account (no margin). Sign the W-8BEN.
2. Remit USD from your Indian bank under the Liberalised Remittance Scheme (LRS). Purpose: investment in overseas listed securities.
3. Buy **Irish-domiciled accumulating UCITS ETFs** on the London Stock Exchange (USD lines) for the core. Use US-listed ETFs only for small, tactical positions.
4. Every year: Schedule FA (assets), Schedule FSI/TR (income, tax credit), Form 67 (foreign tax credit), and claim the TCS.

Why UCITS first: a US-domiciled ETF is a US-situs asset. A non-US person's US-situs assets above USD 60,000 are exposed to
US estate tax (18% to 40%). India has no estate-tax treaty with the US. An Irish fund is generally treated as non-US-situs even
when it holds only US companies. Irish accumulating lines also avoid yearly Indian tax on dividends.

## 1. Opening the IBKR account

- **Entity:** Indian residents open an account with Interactive Brokers LLC online. Account type: **Individual, cash**. Margin is not
  available to you under LRS rules, so do not apply for it.
- **Documents:** PAN, passport or Aadhaar, address proof, a bank statement, employment and net-worth details, and your Indian bank
  account for funding. Expect a few days to two weeks.
- **Pricing plan:** pick IBKR Pro (Lite is for US residents). Fixed pricing for US stocks and ETFs is about USD 0.005 per share, minimum
  USD 1, maximum 1% of trade value. This is what `costs.ibkr_us` in `config/settings.yaml` models.
- **W-8BEN:** completed during onboarding. It declares you an Indian tax resident and claims the India-US treaty rate on dividends
  (25% instead of 30%). It expires after three calendar years. IBKR will prompt you to renew; if it lapses, withholding rises to 30%.
- **Trading permissions:** under *Settings > Trading Permissions*, switch on **Stocks/ETFs: United States** and **United Kingdom** (and
  Ireland/Germany if you want other venues). Some UCITS ETFs show as restricted for retail clients. Search by **ISIN**, check the exchange
  and the trading currency, and if IBKR asks for a KID or PRIIPs acknowledgement, accept it. **[verify]** that your specific fund is
  tradable on your account before sending money.
- **Market data:** delayed quotes are free. For a monthly rebalance you do not need real-time data.

## 2. Moving money: LRS

| Item | Rule |
|---|---|
| Annual limit | USD 250,000 per person per financial year (April to March), across all LRS uses |
| Prohibited | Margin trading, margin calls, leveraged forex. Keep to fully paid cash positions |
| TCS (tax collected at source) | **20%** on the part of your yearly LRS remittances **above Rs 10 lakh**, for investments. Rs 10 lakh is cumulative across all purposes. Budget 2026 cut the rate for self-funded education, medical and tour packages (to 2%), but left the rate for investments at 20%. Statutory reference: section 394(1) of the Income-tax Act 2025 (was 206C(1G)) **[verify the section number]** |
| Source of funds | Bank asks for Form A2 and a purpose declaration. Name on the IBKR account must match the remitter |
| Repatriation | Money that comes back from a sale and is not reinvested abroad should be repatriated within 180 days **[verify]**. Staying invested inside IBKR avoids the issue |

**How to send:** in IBKR, *Transfer & Pay > Transfer Funds > Add Deposit* gives you wire instructions and a reference that must appear
on the transfer. In your bank's net banking (outward remittance / forex) choose "LRS, investment in overseas securities" and send **USD**,
not INR-to-EUR. Sending USD keeps one conversion in the bank. If your bank's card rate is poor, ask the relationship manager for a
negotiated rate above a few lakh rupees.

**Cost of getting money in:**
- Bank INR to USD markup: typically 0.5% to 1.2%, so negotiate. The engine assumes 0.35% one way (`costs.ibkr_us.fx_one_way`).
- Bank wire fee: a flat charge, often Rs 500 to 1,500 plus GST, and the intermediary may take USD 10 to 25.
- IBKR itself takes no deposit fee. Converting USD inside IBKR to another currency (for example GBP) costs about 0.2 basis points
  with a USD 2 minimum, so buy a **USD line** where one exists and avoid conversions altogether.

**How to keep the TCS from hurting:** TCS is advance tax, not a fee.
1. Stay at or below Rs 10 lakh of total LRS in a financial year when you can (including family travel and tuition paid via LRS).
2. If you must go above, check the TCS in **Form 26AS / AIS (Part VI of 26AS)** after the bank deposits it.
3. Claim it in the ITR under taxes paid. It reduces your tax bill; any excess is refunded with the return.
4. If you are salaried, you can ask the employer to reduce TDS on salary for the expected TCS (declaration under the TDS rules).
   This recovers the cash during the year rather than waiting for the refund.
5. Plan cash flow, not tax: the cost of 20% TCS is the lock-up until your refund, not 20% of the money.

The engine tracks this: `lrs_remitted_this_fy_inr` in `holdings.yaml` is read, and any rebalance that would push you over the
threshold shows the TCS lock-up in its cost line.

**RSU proceeds [verify]:** your employer-stock account only lets you sell. The sale proceeds are money already outside India. Ask your CA
whether you may wire them directly from that account to IBKR (abroad to abroad) without an LRS remittance or TCS, and what Form 15CB/FEMA
conditions apply. I could not verify this from a primary source, so treat it as a question for the CA, not as a plan.

## 3. What to buy: US-domiciled ETF vs Irish UCITS

| | US-domiciled (SPY, QQQ, EWJ) | Irish UCITS Acc (CSPX, CNDX, SWDA, VWRA, EIMI) |
|---|---|---|
| Listed | NYSE Arca / Nasdaq, USD | London Stock Exchange, USD line (pick the USD line to avoid FX) |
| Dividends | Paid out. US withholds 25% (with W-8BEN). India taxes the dividend at slab; Form 67 credit is capped at the Indian tax, so total is about the slab rate | Reinvested inside the fund. The fund pays 15% treaty withholding on US dividends internally (already in the price). India taxes nothing until you sell |
| US estate tax | **Exposed** above USD 60,000 of US-situs holdings (Form 706-NA threshold; rates 18% to 40%) | Generally not US-situs (Irish company or fund) |
| Capital gains in India | Foreign asset: long term after **24 months**, 12.5% without indexation; short term at slab | Same |
| Cost | USD 1 minimum commission, spread near 0.02% | About 0.05% commission, USD 3 minimum **[verify]**, spread 0.03% to 0.1% |
| Fund fee (TER) | 0.03% to 0.20% | 0.07% to 0.25% |

The engine puts its numbers in `config/settings.yaml`: the venue `ibkr_ucits`, the `dividends` block, and the `domicile`, `div_yield` and
`accumulating` flags on each asset. For a UCITS ETF not in the universe, add it in `holdings.yaml`:

```yaml
assets:
  VUAA: {ticker: VUAA.L, currency: USD, venue: ibkr_ucits, domicile: IE, accumulating: true}
```

Check the quote currency in Yahoo. An LSE line quoted in GBP or pence would be treated as dollars, which breaks every number.

## 4. Taxes, line by line

All figures for a resident individual. Capital gains are in **rupees**: convert the purchase and sale values at the SBI
telegraphic transfer buying rate on each transaction date (Rule 115), so a falling rupee adds to your gain.

| Event | Treatment |
|---|---|
| Sell after more than 24 months | Long-term capital gain, 12.5%, no indexation, plus 4% cess (and surcharge if it applies). No Rs 1.25 lakh exemption: that is for Indian listed equity only |
| Sell within 24 months | Short-term, added to income, taxed at slab |
| Loss | Short-term loss sets off any gain; long-term loss sets off long-term gain only; both carry forward 8 years if the return is filed on time |
| US dividends | 25% US withholding, then taxed in India at slab. Claim credit with **Form 67** |
| Interest on IBKR cash | Taxable in India at slab. US source interest is generally not withheld for non-residents of the US. Report it in Schedule FSI |
| Capital gains in the US | None for a non-resident alien from a country like India, so no US tax and no credit to claim |
| Wash sales | India has no wash-sale rule, so you can sell a loser and buy a near-identical fund. The engine uses this for harvesting, with `equivalent_of` pairs (SPY and CSPX) |
| Switching from a US ETF to an Irish equivalent | That is a sale, with tax. Do it while the position is small or at a loss |

### Reporting every year (ITR-2 or ITR-3)

- **Schedule FA** (foreign assets): lists every foreign account and holding you had **at any time in the calendar year** (January to
  December), not the financial year. The brokerage account goes in the *foreign custodial account* table, and the securities in the
  *foreign equity and debt interest* table. Do this even if the account made a loss or had a nil balance at year end.
- **Schedule FSI / TR:** foreign income and the tax relief claimed.
- **Form 67:** file on the e-filing portal **before** you claim foreign tax credit. Attach the broker's tax statement (1042-S). The credit
  is the lower of foreign tax paid and Indian tax on that income. As I read the amended Rule 128, it can be filed up to the end of the
  assessment year when the return is filed on time **[verify]**. File it at the same time as the ITR to be safe.
- **Schedule CG:** foreign capital gains go in the usual capital gains schedule, with the conversion rates documented.
- **Keep:** IBKR activity statements (the annual one), 1042-S, FX rates used, and bank A2 forms.

### Black Money Act and FAST-DS 2026

- Not reporting a foreign asset in Schedule FA can attract a penalty of Rs 10 lakh under the Black Money Act, even if the tax is paid.
- Since 1 October 2024, non-disclosure of foreign assets other than immovable property with total value up to **Rs 20 lakh** is
  excluded from penalty. Finance Act 2026 applied the same threshold to prosecution (retrospectively from 1 October 2024).
  The duty to report in Schedule FA and to pay tax on income remains. Do not treat the Rs 20 lakh as permission to skip reporting.
- **FAST-DS 2026**, a one-time disclosure scheme for small foreign assets, runs from 16 August to **31 December 2026**. It matters only if you
  already held foreign assets and left them out of past returns. In particular, unvested or vested employer shares that were not in
  Schedule FA belong in this conversation. Talk to a CA before the window closes.

## 5. Costs, in one place

| Cost | Where it comes from | Engine setting |
|---|---|---|
| Bank FX markup, one way | 0.5% to 1.2% typical, negotiable | `costs.ibkr_us.fx_one_way` 0.35% |
| TCS lock-up | 20% above Rs 10 lakh a year, refundable via ITR | `tax.lrs_tcs_threshold`, `tax.lrs_tcs_rate` |
| IBKR commission, US | USD 0.005/share, min USD 1 | `costs.ibkr_us` |
| IBKR commission, LSE UCITS | about 0.05%, min about USD 3 **[verify]** | `costs.ibkr_ucits` |
| Spread | Wide for thinly traded UCITS lines: use limit orders | `half_spread` |
| Dividend leakage, US ETFs | 25% withholding, slab in India | `dividends.us_wht`, applied as a yearly drag in prices |
| Fund fee (TER) | Already inside the price | none |
| Capital gains tax | 12.5% long term after 24 months | `tax.holding_months.foreign`, `tax.other_ltcg_rate` |

Practical effect for a small investor: below about Rs 3 lakh a trade, the USD 3 commission floor is a visible cost. Trade rarely, in
larger lots, and use limit orders during the London session (about 13:30 to 22:00 India time).

## 6. Alternatives, briefly

| Route | Good for | Watch out for |
|---|---|---|
| **IBKR** | Widest choice (UCITS, many countries), low commission, one account for everything | Self-service reporting; you handle LRS, FX and Schedule FA |
| **INDmoney / Vested** | Rupee funding inside the app, US stocks and ETFs, fractional shares; INDmoney lists a limited set of accumulating USD UCITS lines. INDmoney quotes 0.05% brokerage capped at USD 25 | Smaller product list, platform and custodian risk, bank FX markup on withdrawal, still LRS and TCS; same Schedule FA duty **[verify current fees]** |
| **GIFT City (IFSC) brokers** | US stocks through an Indian-regulated entity; some route funding within the Indian financial system | Still treated as LRS for the remittance **[verify]**; product range and fees differ by broker; I have not verified tax treatment beyond "foreign asset" |
| **Indian international FoFs and NSE-listed ETFs** (for example Nasdaq 100 or Hang Seng ETFs) | No LRS, no TCS, no Schedule FA. Held in the demat account | Premium to NAV, overseas investment limits on AMCs (some are closed to fresh money), listed international ETFs: 12 months to long term, fund FoFs: 24 months (see `tax.holding_months`) |

For a first pass at global exposure with no paperwork, the NSE-listed ETFs already in the universe (MON100, MAFANG, HNGSNGBEES) are the
easy part. Move to IBKR once the amount, or the need for broader choice, justifies the filing work.

## 7. Where the engine stops

- It computes trades, costs, TCS lock-up and tax. It never connects to a broker.
- Dividend drag for US ETFs uses rough yields. Edit `div_yield` per asset.
- Only USD-quoted lines are supported. EUR, GBP, JPY lines would need their own FX series.
- No derivatives, no margin, no leveraged or inverse products.

## Sources

- TCS on LRS from 1 April 2026: [taxupdate.in](https://taxupdate.in/income-tax/681/tcs-on-foreign-remittances-slashed-to-2-from-april-1-2026-what-the-new-lrs-rates-mean-for-you/), [Casurana](https://casurana.com/blogs/tcs-foreign-remittance-lrs-guide.html), [Patron Accounting](https://www.patronaccounting.com/blog/tcs-rate-changes-april-2026-overseas-travel-lrs-education-liquor)
- UCITS routes, IBKR onboarding, LRS limits, FX markup, 180-day rule: [INDmoney](https://www.indmoney.com/learn/ucits/how-to-invest-in-ucits-etfs-from-india)
- US estate tax and fund domicile: [INDmoney](https://www.indmoney.com/learn/ucits/us-estate-tax-on-etfs-for-indian-investors), [Paasa](https://paasa.com/blog/how-us-estate-tax-works-for-indians-and-nris)
- Form 67: [Paasa](https://paasa.com/blog/form-67-guide-for-indian-investors), [MBG on the Rule 128 time limit](https://www.mbgcorp.com/in/insights/relaxation-in-time-limit-to-file-form-67-for-claiming-foreign-tax-credit/)
- Black Money Act threshold and FAST-DS 2026: [CA Sanjay](https://askcasanjay.com/blog/fast-ds-2026-foreign-assets-disclosure-scheme), [TaxGuru](https://taxguru.in/income-tax/prosecution-relief-granted-small-foreign-asset-non-disclosure.html)
- Dividend and capital gains on US stocks: [Winvesta](https://www.winvesta.in/blog/investors/dividend-tax-on-us-stocks-understanding-the-25-withholding), [INDmoney](https://www.indmoney.com/learn/us-stocks/tax-on-us-stocks)
- CSPX facts: [Paasa](https://paasa.com/etfs/cspx-l)

All of these are secondary sources (advisers, brokers, tax blogs). None replaces the Act, the Rules or your CA. The IBKR commission
schedule changes often: read it on IBKR's pricing page before relying on the figures here.
