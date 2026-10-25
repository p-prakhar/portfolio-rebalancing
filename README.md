# Portfolio engine (India + US, tax-aware)

A periodically-run decision-support tool. It reads your tax lots, pulls free daily prices
(Yahoo Finance), runs several allocation algorithms, and writes a report saying **what to
trade, when, and why**, with transaction costs and Indian capital-gains tax worked out for
every trade. It never places orders; you make every call.

## Start here

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python main.py            # guided shell with autocomplete (Tab) and Up-arrow history
```

Inside the shell, in this order: `profile` (age, risk appetite, employer stock) → `income` (salary, RSU income, regime, carried-forward losses; sets your real slab rate) → `import-kite` (Zerodha tradebook CSVs) →
`import-etrade` (RSU vests from E*TRADE Benefit History) → `import-mf` (all mutual funds from a CAMS/KFintech/MF Central CAS PDF) → `add-fd` (SBI, IDFC FIRST or any bank) → `add-other` (FD, PPF, EPF, NPS, mutual funds, gold, property; each
question says where to find the number, or type `where`) → `site`, which builds and opens `reports/index.html`.

The page answers one question first: **is rebalancing worth it, yes or no, and why.** Below it: where the money moves (before and
after), every factor considered, a replay of the last 12 months with a dot on each day money moved (click a dot for the reason, the
price chart around it and an optional live TradingView chart), the 10-year evidence, and a tick-off checklist of the exact orders.
It is one offline HTML file. Everything personal stays on your machine and is git-ignored.

`python main.py validate` runs every strategy from a lump sum over 10 years and over rolling 3-year windows, and labels each
"robust edge", "promising, not proven", "cuts drawdown at little cost" or "no reliable edge". Read `reports/validation.md`: most
fancy strategies do not beat buy & hold after Indian tax once you look beyond one year, and the page says so.

## Quick start

```bash
pip install -r requirements.txt
# 1. cp config/holdings.example.yaml config/holdings.yaml, then enter your real lots (the file is git-ignored)
python main.py backtest      # last 1 year, all strategies -> reports/backtest.md (+ .png, .csv)
python main.py run           # today's check -> reports/latest.md
python -m pytest -q tests    # tax engine / stopping rule / planner tests
```

`--demo` on either command uses synthetic prices, only to check the code runs.

## Any custom portfolio

- **From a tradebook:** `python main.py import-tradebook tradebook.csv` builds FIFO tax lots from a
  Zerodha/Groww/IBKR export or any CSV with symbol, date, buy/sell, quantity and price columns
  (USD rows need a `currency` column plus `usd_inr`, or pass `--usd-inr`). The old holdings file is
  kept as `.yaml.bak`.
- **By hand:** list lots in `config/holdings.yaml`. Any symbol not in the universe is added
  automatically as an NSE stock (`SYMBOL.NS`). Override per symbol if needed:

  ```yaml
  assets:
    RELIANCE: {ticker: 500325.BO}                 # BSE ticker instead
    AAPL: {currency: USD}                         # US stock via IBKR: 24-month LT rule, IBKR costs
    SGBAUG28: {tax_class: in_other, venue: nse_nonequity_etf}
  ```
- Run with `--policy custom` to keep what you own and only sell on converging evidence:
  a technical downtrend, a breached trailing stop and weak momentum (at least 2 of the 3);
  trim single stocks above 10%; and cut equity when the market trend overlay turns risk-off.
  Every holding gets a technical and momentum review in the report, whatever the policy.
- `--holdings other.yaml` points any command at a different portfolio file.

## Technical analysis

`pe/technical.py` computes the 200/50-day trend and golden/death cross, 12-1 month momentum,
distance from the 52-week high, a volatility trailing stop, RSI(14), MACD and Bollinger %B. It
weights them by evidence: trend, momentum and 52-week high drive the verdict, while RSI, MACD
and Bollinger only appear as timing hints (see docs/THEORIES.md).

## Every other asset class

`python main.py real-assets` compares ~45 asset classes: equity, global, unlisted, FDs, G-secs,
tax-free bonds, PPF/EPF/NPS, P2P, REITs/InvITs, flats, plots, farmland in Karnataka and
Chhattisgarh, a Dubai flat, gold in every form, silver, crypto and collectibles. Each is a
yearly after-tax cash-flow model with its own costs and tax rule, run under base/bear/bull
scenarios against Nifty, and the result is ranked in `reports/real_assets.md`. Edit
`config/asset_classes.yaml` (generic classes) and `config/real_assets.yaml` (detailed property,
land and gold frameworks). Sources are in `docs/REAL_ASSETS.md`.

`python main.py gold-prices` fetches same-day city gold rates (Bangalore, Raipur, Bilaspur,
metros), logs them for history and compares them with import parity. Schedule it daily alongside
`run`.

## Index reconstitution predictor

`python main.py predict-index nifty200.csv --current mom30.csv` ranks the parent index the way NSE
builds Nifty200 Momentum 30, and lists likely entrants and exits (download the constituent CSVs
from niftyindices.com). Run it in late May and late November.

## What a run does

1. **Holdings and tax status** per lot: long or short term, days until long term, gain, and
   tax if sold today.
2. **Algorithms** (`strategy.policy` in `config/settings.yaml`):
   - `core_satellite` (default): 60% core in NIFTYBEES left alone for tax deferral, rotated to
     gold or cash only when dual momentum flags a downtrend; 40% satellite in the top 3 assets
     by NSE-style cross-sectional momentum.
   - `dual_momentum`: Antonacci rotation among Nifty, gold and cash.
   - `xs_momentum`: top 3 of the India + US + gold universe by 6m/12m volatility-adjusted momentum.
   - `trend_vol`: 10-month trend filter per asset plus portfolio volatility targeting.
   - `risk_parity`: inverse-volatility across Nifty, low-vol, gold, S&P 500, US Treasuries.
   - `daa`: Keller's canary-based defensive asset allocation.
   - `custom`: keep your own holdings; TA + momentum exits, concentration trims, regime cut.
   - `buy_hold`: no rotation (still recommends tax harvesting).
   See `docs/THEORIES.md` for why these, and how they behave in turbulent markets.
3. **Tax-aware planner.** For each sale it picks the cheapest lots (losses, then long term),
   computes the marginal tax with set-off rules and the Rs 1.25 lakh exemption, and values the
   tax as an *economic* cost (tax now minus the present value of the tax you'd pay later anyway).
   Rotations go ahead only if a haircut estimate of the benefit beats costs plus that tax cost;
   risk-off exits skip the hurdle. Every trade lists its itemised costs (STT, exchange, SEBI,
   GST, stamp duty, DP charge, spread; IBKR commission and FX for US assets).
4. **When to act (optimal stopping).** A secretary-rule execution window (observe 4 of 10 days,
   then act on the first better price), and a rule that waits for long-term status when the
   tax saving beats the expected cost of waiting.
5. **Harvesting.** Uses the yearly LTCG exemption and harvests losses only where they actually
   reduce tax.
6. **Report** in `reports/latest.md`, optional Telegram push.

## Running it periodically

- **cron (Linux/macOS)**, weekdays after market close:
  `30 16 * * 1-5 cd /path/to/portfolio-engine && python main.py run >> reports/cron.log 2>&1`
- **Windows**: Task Scheduler running `python main.py run` in this folder.
- **CI:** `.github/workflows/ci.yml` runs only the unit tests on push/PR (cheap on free-tier minutes). Run the
  periodic check locally, since real holdings should never be committed.

When the report says to execute, place the trades, update `config/holdings.yaml` with what you
actually got, and run `python main.py reset-window`.

## Files

```
config/settings.yaml   universe, tax rates, costs, strategy and timing parameters
config/holdings.yaml   your lots (edit this)
pe/data.py             Yahoo download, cache, USD->INR conversion, manual CSV overrides
pe/tax.py              Indian capital-gains engine (111A/112A, slab, foreign 24m, set-off, exemption)
pe/costs.py            itemised cost model per venue
pe/signals.py          NSE momentum ratio, dual momentum, regime
pe/strategy.py         policies -> target weights + explanation
pe/stopping.py         secretary rule, long-term wait rule
pe/technical.py        technical indicators and per-holding verdicts
pe/importer.py         broker tradebook -> FIFO lots
pe/index_predict.py    Nifty200 Momentum 30 reconstitution predictor
pe/assetclasses.py     generic after-tax framework for ~40 asset classes + universe report
pe/realassets.py       detailed frameworks: Dubai flat, farmland by state, physical gold vs ETF
pe/goldprice.py        city-wise gold rate extractor and landed-parity check
pe/engine.py           tax-aware planner -> trades with reasons
pe/backtest.py         walk-forward simulation with lots, FY tax payments, costs
pe/report.py           Markdown reports
docs/THEORIES.md       what works in turbulent markets and why
docs/EDGES.md          small-investor edges and traps
```

## Known limits

- Yahoo data can have gaps for thin ETFs; drop a `data/manual/<SYMBOL>.csv` (Date,Close) to override.
- US prices are converted at Yahoo's USD/INR, not the SBI TT buying rate used for tax.
- The cash sleeve is modelled at a fixed yield (`cash.rate`).
- Taxes in the backtest are paid from the portfolio at the start of each new FY; advance-tax
  timing and interest are ignored. Dividends are in the adjusted prices, and their tax is ignored.
- One-year backtests are one sample. Use them to sanity-check behaviour, not to pick a winner.
