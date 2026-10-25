# Which foreign markets are in the universe, and which are not

Rule used: a market goes in only if (1) the tax for an Indian resident is documented in a way the engine can model, and (2) a resident
can actually buy it through IBKR under LRS with a USD-quoted instrument. Anything that fails either test is left out and listed below
with the reason. Procedures are in `docs/GLOBAL_INVESTING.md`.

All included instruments are tagged `tax_class: foreign` (24 months to long term, 12.5% LTCG, slab on short term), `rotate: false`,
and a `domicile` (US or IE). Validate before changing `rotate`, using `python main.py validate`.

## Included

| Exposure | Instrument | Domicile | Why it passes | Cost venue | Notes |
|---|---|---|---|---|---|
| US large cap | SPY, CSPX (S&P 500) | US, IE | Capital gains: no US tax; India 12.5% after 24 months. Dividends: 25% US withholding with W-8BEN, India slab with Form 67 credit | `ibkr_us`, `ibkr_ucits` | CSPX is the estate-tax-safe version. `equivalent_of` links the pair for harvesting |
| US Nasdaq 100 | QQQ, CNDX | US, IE | Same | `ibkr_us`, `ibkr_ucits` | India also has MON100 on NSE (no LRS, but premium risk) |
| Developed world | IWDA, EFA | IE, US | Same. IWDA is about 70% US, so it overlaps the S&P | `ibkr_ucits`, `ibkr_us` | |
| All-world | VWRA | IE | One fund, accumulating, includes emerging markets | `ibkr_ucits` | Simplest single global holding |
| Europe | via IWDA / VWRA | IE | Direct European stocks fail the tests below; broad exposure comes inside the world funds | | No European-only fund in the list on purpose |
| Japan | EWJ | US | US-listed, USD, standard US treatment. Japan withholding is handled inside the fund | `ibkr_us` | US-domiciled, so it counts toward the USD 60,000 estate-tax threshold |
| Emerging markets | EIMI, EEM | IE, US | Taiwan, Korea, China, India exposure inside the fund; the fund absorbs foreign withholding | `ibkr_ucits`, `ibkr_us` | EIMI includes India, which overlaps your domestic holdings |
| Gold | IGLN, GLD | IE, US | Physical-gold ETC; gain taxed as foreign asset (no dividend) | `ibkr_ucits`, `ibkr_us` | Compare with GOLDBEES (12 months to long term, no LRS) |
| Bonds | TLT | US | US Treasuries; dividends are interest, taxed at slab | `ibkr_us` | Dollar-duration bet; rupee has weakened against USD over time |
| Thematic (metals, semis) | existing US ETFs | US | As before | `ibkr_us` | Kept `rotate: false` |

Dividend yields are approximate (`div_yield`). The engine subtracts the yearly dividend tax from US-domiciled funds. Irish accumulating
lines carry no extra drag because the NAV is already net of what the fund paid.

## Excluded, with reasons

| Market or product | Why excluded |
|---|---|
| Direct stocks in Europe (Germany, France, Netherlands, Switzerland, Italy, Nordics) | Dividend withholding of 15% to 35% differs by country. Treaty relief and reclaim paperwork are country-specific and slow. Financial-transaction taxes in France and Italy. Prices in EUR, CHF, SEK. Broad exposure is available through the world funds instead |
| UK direct stocks | 0.5% stamp duty on purchase of shares; GBP quotes (pence on Yahoo). The UCITS ETFs trading in London are fine because ETFs are exempt |
| Japan direct stocks | JPY quotes, withholding of about 15% reduced to 10% under treaty only with forms, odd lot sizes. Use EWJ |
| Hong Kong and China | Mainland A-shares are not reachable through a standard India IBKR account, and China withholds 10% on dividends. Hong Kong shares are tax-simple (no capital gains, no dividend withholding) but quoted in HKD, with 0.1% stamp duty on stocks. India already lists HNGSNGBEES |
| Singapore, Canada, Australia direct | Each has its own withholding (Canada 25%, treaty 15%), franking credits in Australia, local currency. Not worth the extra rules for a small portfolio |
| Gulf markets (UAE, Saudi) | Access for an Indian resident via IBKR is limited and I could not verify it. Dubai property is handled in the real-assets framework |
| Russia and Belarus | Sanctioned, no practical access |
| Crypto | Different regime: 30% flat tax, 1% TDS, no loss set-off. Out of scope for this engine |
| Options, futures, CFDs, leveraged and inverse ETFs, margin | LRS bars margin and leveraged forex trading. Treatment of derivatives gains is unsettled for this use. The engine is a long-only fund allocator |
| Non-USD lines (GBP, EUR, JPY, CHF quotes) | The engine has one FX series (USD/INR). A GBP-quoted fund would be priced wrongly. Pick the USD line of the same fund |

## How to add a market later

1. Write down the tax: capital gains class and holding period, dividend withholding at source, treaty rate, Indian credit mechanism.
2. Write down the cost: commission, stamp duty or transaction tax, FX line.
3. Put the instrument in `config/settings.yaml` with `domicile`, `div_yield`, `rotate: false`, and add an entry to `INFO` in `pe/universe_compare.py`.
4. Add a test next to `tests/test_global.py`. The existing test fails if a USD asset has no domicile or an unknown cost venue.
5. Run `python main.py validate`. Do not turn `rotate` on based on a single year.
