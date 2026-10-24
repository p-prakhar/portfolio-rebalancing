# Portfolio engine: notes for contributors and coding agents

Decision support for an Indian resident's taxable portfolio (India and US assets). It never places orders.

## Commands
- `python main.py` guided shell; `site` builds `reports/index.html`; `validate` runs the 10-year rolling-window test; `compare` ranks metals, semiconductors and others.
- `python -m pytest -q tests` must pass before any commit. CI runs only this (keep it cheap: no network, no schedule).

## Privacy rules (the repo is published)
- Never commit `config/holdings.yaml`, `config/profile.yaml`, `config/other_assets.yaml`, `reports/`, `state/`, or logged prices. They are git-ignored; keep it that way.
- Example data uses made-up numbers. No names, amounts, employers or locations from real use in code, tests or docs.

## Engine conventions
- Tax rules live in `config/settings.yaml` and `pe/tax.py`; costs in `pe/costs.py`. Change numbers there, not inline.
- A new strategy needs a `VARIANTS` entry in `pe/backtest.py` and must be judged by `python main.py validate`, not by a single year. Do not tune parameters on the windows you report.
- New instruments go in `config/settings.yaml`; set `rotate: false` unless validation shows rotation into them helps.
- Yahoo data has glitches; `pe/data.py` drops isolated bad prints. Wrap yfinance calls in `pe.quiet()`.

## Report UI (`pe/site_template.html`, one offline HTML file; data embedded as JSON by `pe/site.py`)
- Order: regime bar, decision, order blotter with theta slider, factor matrix, then supporting sections.
- Tokens: light canvas #f8fafc, dark #09090b; borders #e2e8f0 / #27272a, 1px; BUY #059669, SELL #e11d48, primary #0f172a. Geist for copy, Geist Mono for numbers, tabular figures everywhere. Padding 8 to 12px, dense tables, divide-y rows.
- Not allowed: gradients, glows, blur, heavy shadows, nested cards, rounded-2xl wrappers, hero or marketing copy, em-dashes in UI copy, status dots, raw JSON. Minimal motion.
- Formulas render with KaTeX from a CDN when online and fall back to monospace text offline.
- Check at 1440px and 768px widths after any layout change.
