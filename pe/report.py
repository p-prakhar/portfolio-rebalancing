"""Markdown reports for the live recommendation run and the backtest."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .config import Settings
from .engine import Plan
from .tax import compute_tax, fy_end

DISCLAIMER = ("Decision support only, not investment or tax advice. Tax rules are modelled from the "
              "Finance (No. 2) Act 2024 / Finance Act 2025 as understood when this was written; confirm with a CA "
              "before acting, and you make the final call on every trade.")

SYNTH_BANNER = ("> **SYNTHETIC DATA. These numbers come from random-walk prices used to test the code. "
                "They say nothing about markets. Re-run without `--demo` for real data.**\n")


def rs(x: float) -> str:
    return f"Rs {x:,.0f}"


def _md_table(df: pd.DataFrame, floatfmt: dict | None = None) -> str:
    floatfmt = floatfmt or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            f = floatfmt.get(c)
            cells.append(f.format(v) if f and isinstance(v, (int, float)) and pd.notna(v) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def live_report(plan: Plan, settings: Settings, timing_lines: list[str], demo: bool, data_note: str) -> str:
    t = plan.target
    out = [f"# Portfolio check: {plan.as_of}", ""]
    if demo:
        out.append(SYNTH_BANNER)
    out.append(f"_Policy: **{settings.strategy['policy']}**. Data: {data_note}._\n")

    actions = [x for x in plan.trades if not x.why or "Re-buy leg" not in x.why[0]]
    out.append("## Bottom line\n")
    if not plan.trades:
        out.append("**No trades recommended.** " + ("Some moves were considered and held back; see below." if plan.blocked or plan.deferred else "The portfolio already matches the model."))
    else:
        for x in actions:
            out.append(f"- **{x.side.upper()} {x.symbol}** about {rs(x.value)} ({x.qty:,.2f} units) — {x.kind.replace('_', ' ')}; cost {rs(x.cost)}")
        out.append(f"\nTotal transaction costs for this plan: **{rs(sum(x.cost for x in plan.trades))}**"
                   f" ({sum(x.cost for x in plan.trades) / plan.nav:.2%} of the portfolio).")
    if timing_lines:
        out.append("\n**Execution timing:** " + " ".join(timing_lines))
    out.append("")

    out.append("## Your holdings\n")
    if not plan.positions.empty:
        p = plan.positions.copy()
        p["status"] = p.apply(lambda r: "long term" if r.long_term else f"short term ({r.days_to_lt}d to LT)", axis=1)
        p["gain_pct"] = p.gain / p.cost
        show = p[["symbol", "buy_date", "qty", "cost", "value", "gain", "gain_pct", "status"]]
        out.append(_md_table(show, {"qty": "{:,.2f}", "cost": "{:,.0f}", "value": "{:,.0f}", "gain": "{:,.0f}", "gain_pct": "{:+.1%}"}))
        res = compute_tax({**{b: 0.0 for b in plan.fy_realised}, **plan.positions.groupby("bucket").gain.sum().to_dict()}, settings)
        out.append(f"\nTotal value **{rs(plan.nav)}**. If you sold everything today (and had no other gains this FY), "
                   f"tax would be about **{rs(res.tax)}**, after using {rs(res.exemption_used)} of the LTCG exemption.\n")

    out.append("## Technical and momentum review of each holding\n")
    held_syms = list(dict.fromkeys(plan.positions.symbol)) if not plan.positions.empty else []
    rows = []
    for sym in held_syms:
        ta = plan.ta.get(sym)
        rv = t.review.get(sym, {})
        if ta is None:
            rows.append({"symbol": sym, "verdict": rv.get("verdict", "-"), "trend": "no data", "score": float("nan"),
                         "12-1m mom": float("nan"), "vs 52w high": float("nan"), "RSI": float("nan"), "stop": "-"})
            continue
        m = ta.metrics
        rows.append({"symbol": sym, "verdict": rv.get("verdict", "-"), "trend": ta.verdict, "score": ta.score,
                     "12-1m mom": m["mom_12_1"], "vs 52w high": m["price"] / m["high_52w"] - 1, "RSI": m["rsi14"],
                     "stop": f"{ta.stop:,.2f}" + (" BREACHED" if ta.stop_breached else "")})
    if rows:
        out.append(_md_table(pd.DataFrame(rows), {"score": "{:+.1f}", "12-1m mom": "{:+.1%}", "vs 52w high": "{:+.1%}", "RSI": "{:.0f}"}))
        out.append("\n_verdict is filled in by the `custom` policy; trend/score come from the technical layer "
                   "(200-day trend, momentum and 52-week-high carry the weight; RSI/MACD/Bollinger are timing hints only)._\n")
        for sym in held_syms:
            src = t.review.get(sym, {}).get("why") or (plan.ta[sym].why if sym in plan.ta else [])
            if src:
                out.append(f"<details><summary>{sym}: why</summary>\n")
                out += [f"- {w}" for w in src]
                out.append("\n</details>\n")
    out.append("## What the algorithms see\n")
    for w in t.why:
        out.append(f"- {w}")
    if t.dual and t.dual.get("choice"):
        out.append(f"- Dual momentum alone would hold: **{t.dual['choice']}**.")
    if t.scores is not None and not t.scores.empty:
        s = t.scores.reset_index().rename(columns={"index": "symbol"})
        s["name"] = s.symbol.map(lambda x: settings.assets[x].name)
        cols = ["rank", "symbol", "name", "score", "ret_126", "ret_252", "vol_6m", "excess_vs_cash"]
        out.append("\nCross-sectional momentum ranking (NSE momentum-ratio method, last month skipped):\n")
        out.append(_md_table(s[cols].head(12), {"score": "{:+.2f}", "ret_126": "{:+.1%}", "ret_252": "{:+.1%}",
                                                "vol_6m": "{:.0%}", "excess_vs_cash": "{:+.1%}"}))
    if t.weights:
        out.append("\nTarget weights: " + ", ".join(f"{k} {v:.0%}" for k, v in sorted(t.weights.items(), key=lambda x: -x[1]) if v > 0.005))
    out.append("")

    out.append("## Recommendations and why\n")
    if not plan.trades:
        out.append("None this run.\n")
    for x in plan.trades:
        out.append(f"### {x.side.upper()} {x.symbol} — {rs(x.value)} ({x.kind.replace('_', ' ')})\n")
        for w in x.why:
            out.append(f"- {w}")
        from .costs import describe
        a = settings.assets[x.symbol]
        out.append(f"- {describe(settings, a, x.side, x.value, x.price, plan.usd_inr)}"
                   + (" Plus FX conversion if the money moves between INR and USD." if a.currency == "USD" and not x.kind.startswith("harvest") else ""))
        if x.side == "sell":
            out.append(f"- Extra tax this FY: {rs(x.tax_now)}.")
        out.append("")
    if plan.blocked:
        out.append("### Considered and held back\n")
        out += [f"- {b}" for b in plan.blocked]
        out.append("")
    if plan.deferred:
        out.append("### Waiting for long-term status\n")
        out += [f"- {d}" for d in plan.deferred]
        out.append("")

    out.append("## Tax position this financial year\n")
    fr = plan.fy_realised
    out.append(f"- FY ends {fy_end(plan.as_of)}. Realised so far incl. these trades: equity STCG {rs(fr['eq_st'])}, "
               f"equity LTCG {rs(fr['eq_lt'])}, other LT {rs(fr['oth_lt'])}, slab-rate {rs(fr['oth_st'] + fr['debt'])}.")
    out.append(f"- Tax on that: {rs(plan.tax_before)} before this plan, {rs(plan.tax_after)} after.")
    rem = max(0.0, settings.tax["ltcg_exemption"] - max(0.0, fr["eq_lt"]))
    out.append(f"- Unused LTCG exemption: {rs(rem)}.")
    out.append("")
    if plan.notes:
        out.append("## Notes\n")
        out += [f"- {n}" for n in plan.notes]
        out.append("")
    out.append("For edges a small investor can use (and traps to avoid), see `docs/EDGES.md`.\n")
    out.append(f"---\n_{DISCLAIMER}_\n")
    return "\n".join(out)


def backtest_report(table: pd.DataFrame, curves: pd.DataFrame, logs: dict, start, end, demo: bool,
                    chart: str | None, init_desc: str) -> str:
    out = [f"# Backtest: {start} to {end}", ""]
    if demo:
        out.append(SYNTH_BANNER)
    out.append(f"Starting point: {init_desc}. Every variant starts from the same lots with their real cost basis, "
               "so selling them realises real (mostly long-term) gains. Same planner code as the live run; "
               "signals use only data up to each check day.\n")
    t = table.copy()
    show = t[["end_value", "return", "after_tax_return_keep", "after_tax_return_liquidated", "max_drawdown",
              "volatility", "sharpe", "taxes_paid", "tax_accrued", "costs", "turnover_x"]].reset_index()
    out.append(_md_table(show, {"end_value": "{:,.0f}", "return": "{:+.2%}", "after_tax_return_keep": "{:+.2%}",
                                "after_tax_return_liquidated": "{:+.2%}", "max_drawdown": "{:.1%}", "volatility": "{:.1%}",
                                "sharpe": "{:.2f}", "taxes_paid": "{:,.0f}", "tax_accrued": "{:,.0f}", "costs": "{:,.0f}",
                                "turnover_x": "{:.2f}"}))
    out.append("\n_return: pre-tax change in portfolio value (taxes already paid at FY end are deducted). "
               "after_tax_return_keep: also deducts tax owed on gains realised in the current FY. "
               "after_tax_return_liquidated: as if everything were sold on the last day — the fairest comparison "
               "between strategies that realise gains and ones that defer them._\n")
    best = t["after_tax_return_liquidated"].idxmax()
    calm = t["max_drawdown"].idxmax()
    bh = t.index[0]
    out.append("## Reading it\n")
    out.append(f"- Best after-tax, liquidation basis: **{best}** ({t.loc[best, 'after_tax_return_liquidated']:+.2%}) vs your buy & hold "
               f"({t.loc[bh, 'after_tax_return_liquidated']:+.2%}).")
    out.append(f"- Shallowest drawdown: **{calm}** ({t.loc[calm, 'max_drawdown']:.1%}) vs buy & hold {t.loc[bh, 'max_drawdown']:.1%}.")
    if len(t) > 1:
        out.append(f"- Tax-gain harvesting alone changed after-tax liquidation return by "
                   f"{(t.iloc[1]['after_tax_return_liquidated'] - t.iloc[0]['after_tax_return_liquidated']) * 100:+.2f} percentage points.")
    out.append("- One year is a single sample. Treat differences under ~2 percentage points as noise, and look at drawdown "
               "and tax drag as much as return.\n")
    if chart:
        out.append(f"![equity curves]({chart})\n")
    out.append("## Decision log (last 25 entries per strategy)\n")
    for name, log in logs.items():
        out.append(f"<details><summary>{name}</summary>\n")
        for d, kind, msg in log[-25:]:
            out.append(f"- {d} **{kind}** {msg}")
        out.append("\n</details>\n")
    out.append(f"---\n_{DISCLAIMER}_\n")
    return "\n".join(out)


def save(text: str, settings: Settings, name: str) -> Path:
    from .config import ROOT
    d = ROOT / settings["report"]["out_dir"]
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text)
    return p


def real_assets_report(cmp: dict, cfg: dict, city_note: str = "") -> str:
    n = cfg["common"]["horizon_years"]
    sc = cmp["scenarios"]
    out = [f"# Real assets vs equity, {n}-year view", "",
           "All figures are after every purchase cost, carrying cost, Indian tax and selling cost, as yearly INR cash flows. "
           "IRR is the annual return on your money; growth assumptions per scenario are in `config/real_assets.yaml`.", ""]
    if city_note:
        out += [city_note, ""]
    names = [r.name for r in sc["base"]]
    out += ["| asset | IRR base | IRR bear | IRR bull | wealth multiple (base) | lost on day one | year-1 cash yield | liquidity |",
            "|---|---|---|---|---|---|---|---|"]
    for i, nm in enumerate(names):
        b, br, bu = sc["base"][i], sc["bear"][i], sc["bull"][i]
        out.append(f"| {nm} | {b.irr:+.1%} | {br.irr:+.1%} | {bu.irr:+.1%} | {b.multiple:.2f}x | {b.upfront_friction:.1%} | "
                   f"{b.year1_cash_yield:+.1%} | {b.liquidity} |")
    out += ["", f"## What each would need to match Nifty ({cmp['equity_irr']:.1%} IRR in the base case)", ""]
    for k, v in cmp["breakeven"].items():
        out.append(f"- {k}: **{v:+.1%}/yr**" if v == v else f"- {k}: can't match within -20% to +40%/yr")
    out += ["", "## Asset by asset", ""]
    for r in sc["base"]:
        out.append(f"### {r.name}\n")
        for w in r.warnings:
            out.append(f"- **Warning:** {w}")
        for nline in r.notes:
            out.append(f"- {nline}")
        out.append("")
    out += ["## In turbulent markets", "",
            "- **Gold** is the only one here that has reliably risen in Indian equity crashes and rupee slides. Hold it as an ETF "
            "for the hedge; physical gold costs 7-20% more on a round trip, plus the locker.",
            "- **A Dubai flat** diversifies away from the rupee (AED is pegged to USD), but Dubai property is cyclical. Prices fell "
            "about 50% after 2008 and about 30% over 2014-2020, and it is the least liquid of the listed options when you might need cash.",
            "- **Farmland** has no mark-to-market, which feels safe but only hides the volatility. It can't be sold quickly in a "
            "crisis, and title risk is the main risk.",
            "", f"---\n_{DISCLAIMER}_\n"]
    return "\n".join(out)
