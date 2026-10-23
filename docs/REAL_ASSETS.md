# Asset-class frameworks: how each is modelled and where the numbers come from

`python main.py real-assets` writes `reports/real_assets.md`. It has one ranked table across
about 45 asset classes, each held over the same horizon, with every cost and Indian tax applied,
in base, bear and bull scenarios. `python main.py gold-prices` writes `reports/gold_prices.md`.

Researched 22 Oct 2026. Defaults are editable assumptions; the ones marked (sourced) came from
the linked pages that day. Tax treatment follows the Income-tax Act 2025 as I understand it.
**Confirm anything material with a CA, and with a local advocate for land.**

## One yardstick for everything

Every asset becomes a stream of yearly after-tax INR cash flows:

- **Year 0:** what leaves your bank account. That includes purchase fees, stamp duty, GST,
  making charges, FX spread and TCS (which comes back as a tax credit in year 1).
- **Each year:** income after tax, minus running costs such as locker rent, service charges,
  fund expenses and expected credit losses.
- **Final year:** sale proceeds after selling costs and capital-gains tax.

The IRR of that stream is the comparable number. For the detailed frameworks the report also
shows the growth an asset would need just to match Nifty (the breakeven).

## Generic framework (`config/asset_classes.yaml`)

It covers about 40 classes: Indian equity (index, mid/small, factor, active, direct, SIF,
unlisted/pre-IPO, PMS/AIF), global equity (LRS/IBKR UCITS, Indian FoFs), debt (savings, bank/SFB/
corporate FDs, G-secs via RBI Retail Direct, liquid/arbitrage/target-maturity funds, NCDs,
tax-free bonds, RBI floating-rate bonds, P2P, invoice discounting), small savings and retirement
(PPF, EPF/VPF, NSC, SCSS via parents, NPS, endowment plans), listed and physical real estate
(REITs, InvITs, SM-REITs, flats, plots), commodities (SGB, silver ETF, physical silver),
alternatives (crypto, collectibles), and F&O selling as a cautionary baseline.

Tax rules applied by class:

| rule | used for | treatment |
|---|---|---|
| `equity` | equity funds/ETFs, stocks, REIT/InvIT units, arbitrage funds | 20% within 12 months; 12.5% after (the Rs 1.25L exemption is left out so all assets compare like for like) |
| `listed_12m` | gold/silver ETFs, listed bonds, SGBs bought on exchange | slab within 12 months; 12.5% after |
| `unlisted_24m` | foreign shares, FoFs, unlisted shares, property, land, physical gold/silver, collectibles | slab within 24 months; 12.5% after, no indexation |
| `slab` | debt/liquid funds (bought after Apr 2023), F&O | always your slab rate |
| `crypto` | VDAs | 30% + cess, no loss set-off, 1% TDS. Retained in Budget 2026 ([Decrypt](https://decrypt.co/356601/no-relief-for-crypto-investors-as-india-retains-current-crypto-tax-in-budget-2026)) |
| income | FD/NSC interest, rent, bond coupons | slab each year, even when it accrues rather than being paid (cumulative FD, NSC); PPF/EPF/tax-free bonds exempt; REIT/InvIT distributions modelled as part-exempt |

Yields checked on 22 Oct 2026 (sourced):

- Small savings rates are unchanged for Oct–Dec 2026: PPF 7.1%, SCSS and SSY 8.2%, NSC 7.7%, KVP
  7.5%, POMIS 7.4% ([Business Today](https://www.businesstoday.in/personal-finance/story/small-savings-scheme-interest-rates-unchanged-for-q3-fy27-check-ppf-scss-ssy-rates-558892-2026-09-30)).
- The 10-year G-sec yield is about 7.38%, a 2-year high; SBI Research sees risk of 7.6% as RBI
  tightens to defend the rupee ([Business Today](https://www.businesstoday.in/latest/economy/story/indias-10-year-bond-yield-may-rise-to-7-6-as-us-treasury-yields-remain-elevated-sbi-research-562097-2026-10-16)).
- Tax-free PSU bonds yield 4.5–6.5% tax-free in the secondary market; none have been issued since
  FY16 ([GoldenPi](https://goldenpi.com/blog/bond-news/tax-free-bonds-in-india-2026/)).
- P2P: RBI's 2024 rules banned pooling and assured returns, and capped lenders at Rs 50 lakh across
  platforms. Sector bad loans rose from ~Rs 14 cr (FY19) to ~Rs 1,163 cr ([Finshots](https://finshots.in/archive/is-peer-to-peer-lending-p2p-set-for-a-crash/)).
- SIFs launched with a Rs 10 lakh minimum ([Business Standard](https://www.business-standard.com/amp/finance/personal-finance/sebi-rolls-out-specialised-investment-fund-for-hnis-with-rs-10-lakh-minimum-124121800227_1.html)).

## Dubai flat (`config/real_assets.yaml → dubai_flat`)

- **Purchase** (sourced, [Bayut 2026](https://www.bayut.com/mybayut/cost-buying-property-dubai/)):
  DLD transfer fee 4%, trustee about AED 4,200, title deed about AED 250, admin about AED 580, agent 2% + 5%
  VAT, conveyancing AED 5–10k. Altogether that's roughly 7–10% of the price in fees.
- **Yield** (sourced, [FAM Properties 2026](https://famproperties.com/blog/best-rental-yield-areas-dubai-2026)):
  gross resale apartment yields are JVC 7.25%, Dubai Marina 5.9%, Dubai Hills 5.7%, Emaar
  Beachfront 4.6%. The model then subtracts vacancy, service charges (an assumption: AED 15/sq ft),
  5% management, maintenance and insurance.
- **Indian tax:** the UAE doesn't tax rent, so as a resident you pay Indian slab tax on rent after
  the 30% standard deduction. The sale is LTCG at 12.5% after 24 months on the INR gain, which
  includes the currency gain. The flat must be reported in Schedule FA every year.
- **Money out:** LRS is USD 250k per person per year, and TCS is 20% above Rs 10 lakh (refundable
  credit). Resident Indians generally can't borrow abroad for it, so a default AED 950k flat
  needs co-buyers in the family or two financial years. The model flags this.
- **Currency:** AED is pegged to USD. A falling rupee raises your INR return, and that gain is taxed.

## Agricultural land (`agricultural_land.karnataka / .chhattisgarh`)

- **Karnataka:** any Indian citizen can buy farmland, because Sections 79A–79C were repealed in
  2020. Ceiling limits still apply (54 acres dry / 10 acres irrigated per family unit). Check
  for SC/ST grant history under PTCL, which has no time limit since 2023. Budget about 5% stamp
  duty + 1% registration
  ([1acre.in](https://1acre.in/guides/karnataka/can-i-buy-land-in-karnataka)).
- **Chhattisgarh:** reported to be restricted by occupation. Non-agriculturists need the
  Collector's permission under s.165, and transfers of tribal land in Fifth Schedule districts
  also need Gram Sabha approval
  ([1acre.in](https://1acre.in/guides/chhattisgarh/can-i-buy-land-in-chhattisgarh)). Stamp duty is 5% (4% for women) plus
  4% registration ([HomeFirst](https://homefirstindia.com/blog/article/stamp-duty-registration-charges-in-chhattisgarh/)).
  **I'm not certain of the non-tribal rule, so verify it locally before spending anything.**
- **Tax:** rural agricultural land isn't a capital asset, so the sale is tax-free. "Rural" means
  outside these aerial distances from a municipality: 2 km for a population of 10k–1 lakh, 6 km
  for 1–10 lakh, 8 km above 10 lakh
  ([TaxHeal](https://taxheal.com/income-tax-on-sale-of-agriculture-land-analysis.html)). Within
  those limits, it's LTCG at 12.5% after 24 months. Agricultural income such as lease rent is
  exempt.
- **Liquidity:** selling takes 9–12 months, and the model discounts proceeds for the wait.

## Physical gold and the city price extractor

- **Purchase:** GST is 3% on the metal plus 5% on making charges ([IIFL](https://www.iifl.com/blogs/gold-loan/gst-on-gold-in-india-2026-complete-guide-for-buyers-and-sellers)).
  Making charges are assumed at coins 4%, bars 1% and jewellery 12%; buyback haircuts at 3%, 1.5%
  and 6%, with the making charge lost on jewellery.
- **Locker** (sourced, [Angel One 2026](https://oga-prod.angelone.in/news/personal-finance/sbi-vs-hdfc-bank-locker-charges-in-2026-compared-across-metro-urban-and-rural-branches)):
  HDFC metro rents are small Rs 5,000, medium Rs 10,000 and large Rs 15,000 a year (from 1 Apr 2026).
  SBI urban rents are small Rs 2,000, medium Rs 4,000 and large Rs 8,000. Add 18% GST. Banks don't
  insure locker contents.
- **Tax:** physical gold is long term after 24 months (12.5%). Gold ETFs are long term after 12
  months. SGBs bought on the exchange lost tax-free redemption in April 2026.
- **Bringing gold from Dubai:** the 2026 baggage rules allow 20 g (men) and 40 g (women) of
  jewellery duty-free, but only after more than a year abroad. Short-trip residents don't
  qualify ([Khaleej Times](https://www.khaleejtimes.com/uae/how-much-gold-jewellery-can-nris-uae-take-to-india)).
- **City prices:** `python main.py gold-prices` scrapes same-day 24K/22K rates for Bangalore,
  Raipur, Bilaspur and the metros from [pricehistoryapp.com](https://pricehistoryapp.com/gold/raipur).
  It logs them to `data/gold_city_prices.csv` and compares them with landed import parity (COMEX
  spot × USD/INR + duty). If the site changes, pass `--manual bangalore=..,raipur=..`. Only
  compare cities on the same day. Pages I checked showed Raipur on 22 Oct and Bangalore on 18 Oct,
  and gold had moved about 2% in that week, so no city spread can be read from them.
