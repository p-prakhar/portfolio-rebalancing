"""Portfolio engine CLI.

    python main.py run                # today's check -> reports/latest.md (schedule this daily/weekly)
    python main.py backtest           # last 1 year, all strategy variants -> reports/backtest.md
    python main.py                    # guided shell (autocomplete): profile, imports, check, site
    python main.py site --open        # visual decision page
    python main.py validate           # 10-year rolling-window robustness test
    python main.py reset-window       # after you have placed the trades, clear the execution window
    add --demo to any command to use synthetic prices (code smoke test only)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from pe.config import ROOT, load_holdings, load_settings, register_assets, resolve_amount_lots
from pe.data import build_prices, fetch_closes, synthetic_prices
from pe.engine import make_plan
from pe.stopping import secretary_decision
from pe.render import show_md
from pe.tax import BUCKETS

STATE = ROOT / "state" / "execution.json"


def load_data(settings, demo: bool, refresh: bool = False):
    if demo:
        px, vix = synthetic_prices(settings)
        return px, vix, None, "synthetic random walks"
    closes = fetch_closes(settings, refresh)
    px, vix = build_prices(settings, closes)
    fx_t = settings["data"]["fx_ticker"]
    fx = closes[fx_t].reindex(px.index).ffill() if fx_t in closes else None
    missing = [s for s in settings.assets if s not in px or px[s].dropna().empty]
    note = f"Yahoo Finance closes to {px.index[-1].date()}"
    if missing:
        note += f"; missing: {', '.join(missing)}"
    return px, vix, fx, note


def _fy_realised(h):
    r = h.realised_this_fy
    return {"eq_st": r.get("equity_stcg", 0), "eq_lt": r.get("equity_ltcg", 0),
            "oth_st": r.get("other_stcg", 0), "oth_lt": r.get("other_ltcg", 0), "debt": 0.0}


def timing_step(plan, px, settings) -> list[str]:
    """Live secretary-rule window, persisted between runs."""
    tm = settings.timing
    actionable = [t for t in plan.trades if not t.kind.startswith("harvest")]
    today = str(plan.as_of)
    state = json.loads(STATE.read_text()) if STATE.exists() else None
    legs_now = sorted((t.symbol, t.side, t.kind) for t in actionable)
    if state is not None and sorted((l["symbol"], l["side"], l["kind"]) for l in state["legs"]) != legs_now:
        state = None        # the plan changed (new policy, new signals): an old window no longer applies
        STATE.unlink(missing_ok=True)
    if state is None and actionable:
        if tm["execution"] != "secretary":
            return ["Execution mode is immediate: place the trades at the next session."]
        state = {"opened": today, "n": tm["window_days"],
                 "legs": [{"symbol": t.symbol, "side": t.side, "value": round(t.value), "kind": t.kind, "observed": {}}
                          for t in actionable]}
    if state is None:
        return []
    lines = [f"A rebalance window opened on {state['opened']} ({state['n']} trading days)."]
    for leg in state["legs"]:
        leg["observed"][today] = float(px[leg["symbol"]].iloc[-1])
        obs = [leg["observed"][d] for d in sorted(leg["observed"])]
        if leg["kind"] == "risk_exit" and tm["regime_override_secretary"]:
            lines.append(f"{leg['side'].upper()} {leg['symbol']}: risk-off exit, execute now rather than waiting for a better price.")
            continue
        dec, why = secretary_decision(obs, state["n"], leg["side"])
        lines.append(f"{leg['side'].upper()} {leg['symbol']}: **{'EXECUTE TODAY' if dec == 'execute' else 'wait'}**. {why}")
    lines.append("Run `python main.py reset-window` after placing the trades.")
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))
    return lines


def cmd_run(args):
    from pe.report import live_report, save
    settings = load_settings()
    if args.policy:
        settings.strategy["policy"] = args.policy
    h = load_holdings(args.holdings)
    added = register_assets(settings, h)
    px, vix, fx, note = load_data(settings, args.demo, args.refresh)
    if args.asof:
        px = px.loc[:args.asof]
    if added:
        note += f"; auto-added from your holdings: {', '.join(sorted(added))}"
    h = resolve_amount_lots(h, px)
    usd = float(fx.iloc[-1]) if fx is not None else None
    plan = make_plan(px.index[-1], h.lots, h.cash_inr, px, vix, settings, _fy_realised(h),
                     lrs_used=h.lrs_remitted_this_fy_inr, usd_inr=usd)
    timing = timing_step(plan, px, settings) if not args.demo else []
    text = live_report(plan, settings, timing, args.demo, note)
    p = save(text, settings, "latest.md")
    save(text, settings, f"check_{plan.as_of}.md")
    show_md(text)
    print(f"\nSaved {p}")
    if settings["report"].get("telegram"):
        from pe.notify import telegram
        telegram(text[:3900])


def cmd_backtest(args):
    from pe.backtest import run_all
    from pe.report import backtest_report, save
    settings = load_settings()
    h = load_holdings(args.holdings)
    register_assets(settings, h)
    px, vix, fx, note = load_data(settings, args.demo, args.refresh)
    h = resolve_amount_lots(h, px)
    end = px.index[-1]
    start = end - timedelta(days=args.days)
    curves, table, logs = run_all(h.lots, px, vix, settings, start, fx)
    chart = None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        (curves / curves.iloc[0] * 100).plot(ax=ax, linewidth=1.4)
        ax.set_title("Portfolio value (start = 100), after costs and FY taxes paid")
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
        (ROOT / settings["report"]["out_dir"]).mkdir(exist_ok=True)
        fig.savefig(ROOT / settings["report"]["out_dir"] / "backtest.png", dpi=120, bbox_inches="tight")
        chart = "backtest.png"
    except Exception as exc:
        logging.warning("chart failed: %s", exc)
    desc = "; ".join(f"{l.symbol} {l.qty:,.1f} units bought {l.buy_date} at Rs {l.price:,.2f}" for l in h.lots)
    text = backtest_report(table, curves, logs, start.date(), end.date(), args.demo, chart, desc)
    p = save(text, settings, "backtest.md")
    curves.to_csv(ROOT / settings["report"]["out_dir"] / "backtest_curves.csv")
    table.to_csv(ROOT / settings["report"]["out_dir"] / "backtest_summary.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(table[["return", "after_tax_return_liquidated", "max_drawdown", "taxes_paid", "costs", "turnover_x"]])
    print(f"\nData: {note}\nSaved {p}")


def cmd_site(args):
    """Today's plan + 12-month replay (+ 10-year validation if present) -> reports/index.html."""
    import json as _json
    from pe import site
    from pe.backtest import run_all
    from pe.profile import load_other, load_profile
    settings = load_settings()
    if args.policy:
        settings.strategy["policy"] = args.policy
    example = getattr(args, "example", False)
    h = load_holdings(ROOT / "config" / "holdings.example.yaml" if example else args.holdings)
    register_assets(settings, h)
    px, vix, fx, note = load_data(settings, args.demo, args.refresh)
    h = resolve_amount_lots(h, px)
    usd = float(fx.iloc[-1]) if fx is not None else None
    plan = make_plan(px.index[-1], h.lots, h.cash_inr, px, vix, settings, _fy_realised(h), lrs_used=h.lrs_remitted_this_fy_inr, usd_inr=usd)
    timing = timing_step(plan, px, settings) if not (args.demo or example) else []
    start = px.index[-1] - timedelta(days=args.days)
    curves, table, logs = run_all(h.lots, px, vix, settings, start, fx)
    vpath = ROOT / "reports" / "validation.json"
    validation = _json.loads(vpath.read_text()) if vpath.exists() else None
    universe = None
    if not args.demo:
        try:
            from pe import universe_compare as uc, validate as _v
            ls, lpx, _, _ = _v.load_long(10)
            universe = uc.compare(lpx, ls, usd)
        except Exception as exc:    # the page still works without the wider-universe table
            logging.warning("wider universe skipped: %s", exc)
    data = site.build(plan, settings, timing, px, (curves, table, logs, start), None if example else load_profile(),
                      [] if example else load_other(), validation, note, usd, universe)
    data["example"] = example
    dpath = ROOT / "reports" / "daily_sim.json"
    data["daily_sim"] = _json.loads(dpath.read_text()) if dpath.exists() else None
    apath = ROOT / "reports" / "daily_sim_all.json"
    data["daily_sim_all"] = _json.loads(apath.read_text()) if apath.exists() else None
    out = site.render(data, ROOT / settings["report"]["out_dir"] / ("example.html" if example else "index.html"))
    print(f"Decision: {data['verdict']['call']} - {data['verdict']['headline']}\nSaved {out}")
    return out


def cmd_compare(args):
    from pe import universe_compare as uc, validate
    from pe.report import save
    s, px, vix, closes = validate.load_long(10)
    fx = closes[s["data"]["fx_ticker"]].dropna().iloc[-1] if s["data"]["fx_ticker"] in closes else None
    rows = uc.compare(px, s, float(fx) if fx is not None else None)
    text = uc.report(rows)
    p = save(text, s, "universe.md")
    show_md(text)
    print(f"\nSaved {p}")


def cmd_validate(args):
    from pe import validate
    res = validate.validate(years=args.years, window_years=args.window_years, refresh=args.refresh)
    validate.save(res)
    print(validate.report(res, validate.VARIANTS[0][0]))
    print("\nSaved reports/validation.md and validation.json")


def cmd_forecast(args):
    from pe import forecast_study
    forecast_study.run(years=args.years, refresh=args.refresh)
    print((ROOT / "reports" / "forecast_study.md").read_text())


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if len(__import__("sys").argv) == 1:
        __import__("sys").argv.append("shell")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "backtest"):
        sp = sub.add_parser(name)
        sp.add_argument("--demo", action="store_true", help="synthetic prices (testing only)")
        sp.add_argument("--refresh", action="store_true", help="ignore the price cache")
        sp.add_argument("--holdings", help="holdings file (default config/holdings.yaml)")
        if name == "run":
            sp.add_argument("--policy", choices=["buy_hold", "custom", "dual_momentum", "xs_momentum", "core_satellite", "core_xs", "static_mix", "rp_blend", "trend_vol", "risk_parity", "daa"])
            sp.add_argument("--asof", help="pretend today is this date (YYYY-MM-DD)")
        else:
            sp.add_argument("--days", type=int, default=365)
    sp = sub.add_parser("site", help="build reports/index.html: the visual decision page")
    sp.add_argument("--demo", action="store_true"); sp.add_argument("--refresh", action="store_true")
    sp.add_argument("--holdings"); sp.add_argument("--policy"); sp.add_argument("--days", type=int, default=365)
    sp.add_argument("--open", action="store_true", help="open the page in your browser")
    sp.add_argument("--example", action="store_true", help="build reports/example.html from the made-up example holdings (safe to share)")
    vp = sub.add_parser("validate", help="10-year rolling-window robustness test of every strategy (slow the first time)")
    vp.add_argument("--years", type=int, default=10); vp.add_argument("--window-years", type=int, default=3); vp.add_argument("--refresh", action="store_true")
    dp = sub.add_parser("simulate-daily", help="follow the engine every day for the last 10, 5 and 2 years, from a Nifty ETF start (slow)")
    dp.add_argument("--years", default="10,5,2"); dp.add_argument("--workers", type=int, default=6)
    dp.add_argument("--all-strategies", action="store_true", help="run every strategy daily on the core universe")
    fp = sub.add_parser("forecast", help="test valuation (P/E, earnings yield vs bonds) and forecast overlays against the strategies (slow, needs network)")
    fp.add_argument("--years", type=int, default=10)
    fp.add_argument("--refresh", action="store_true")
    sub.add_parser("compare", help="compare metals, semiconductors and other assets in India and abroad, after cost and tax")
    sub.add_parser("shell", help="guided interactive shell with autocomplete: profile, imports, check, site")
    sub.add_parser("reset-window")
    ip = sub.add_parser("import-tradebook", help="build holdings lots from a broker tradebook CSV (FIFO)")
    ip.add_argument("csv")
    ip.add_argument("--out", default=str(ROOT / "config" / "holdings.yaml"))
    ip.add_argument("--usd-inr", type=float, help="FX for USD rows without their own rate")
    ra = sub.add_parser("real-assets", help="compare every asset class (equity, global, debt, small savings, REITs, property, farmland, gold, crypto...) after all costs and tax")
    ra.add_argument("--city-premium", type=float, default=0.0, help="gold price premium of your buying city vs reference, e.g. 0.01")
    gp = sub.add_parser("gold-prices", help="fetch city-wise gold rates (Bangalore, Raipur, ...)")
    gp.add_argument("--manual", help="e.g. bangalore=14800,raipur=14213 if scraping fails")
    gp.add_argument("--home", default="bangalore")
    gp.add_argument("--metal", choices=["gold", "silver"], default="gold")
    pp = sub.add_parser("predict-index", help="predict Nifty200 Momentum 30 adds/drops from a constituents CSV")
    pp.add_argument("universe_csv", help="CSV with a Symbol column: the parent index (e.g. Nifty 200)")
    pp.add_argument("--current", help="CSV with a Symbol column: current index members")
    pp.add_argument("--size", type=int, default=30)
    pp.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    if args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "backtest":
        cmd_backtest(args)
    elif args.cmd == "site":
        out = cmd_site(args)
        if args.open:
            import webbrowser
            webbrowser.open(out.as_uri())
    elif args.cmd == "validate":
        cmd_validate(args)
    elif args.cmd == "simulate-daily":
        from pe import daily_sim
        yrs = tuple(int(x) for x in args.years.split(","))
        if args.all_strategies:
            daily_sim.simulate_all(yrs, workers=args.workers)
            show_md((ROOT / "reports" / "daily_sim_all.md").read_text())
            print("\nSaved reports/daily_sim_all.md")
        else:
            out = daily_sim.simulate(yrs, workers=args.workers)
            show_md(daily_sim.report(out))
            print("\nSaved reports/daily_sim.md")
    elif args.cmd == "forecast":
        cmd_forecast(args)
    elif args.cmd == "compare":
        cmd_compare(args)
    elif args.cmd == "shell":
        from pe.tui import run_shell
        run_shell()
    elif args.cmd == "import-tradebook":
        from pe.importer import lots_from_tradebook, write_holdings
        out = Path(args.out)
        if out.exists():
            out.rename(out.with_suffix(".yaml.bak"))
            print(f"Previous holdings saved to {out.with_suffix('.yaml.bak')}")
        lots, warns = lots_from_tradebook(args.csv, args.usd_inr)
        write_holdings(lots, str(out))
        for w in warns:
            print("WARNING:", w)
        print(f"Wrote {len(lots)} open lots to {out}")
    elif args.cmd == "real-assets":
        from pe import assetclasses
        from pe.report import save
        text = assetclasses.universe_report(assetclasses.universe(city_premium=args.city_premium))
        p = save(text, load_settings(), "real_assets.md")
        show_md(text)
        print(f"\nSaved {p}")
    elif args.cmd == "gold-prices":
        from pe import goldprice, realassets
        from pe.report import save
        cfg = realassets.load()
        if args.metal == "silver":
            cities = [c for c in cfg["gold_prices"]["cities"]]
            df, errors = goldprice.silver_snapshot(cities)
            text = goldprice.silver_report(df, errors, cfg["gold_prices"]["import_duty_pct"], args.home)
            p = save(text, load_settings(), "silver_prices.md")
            show_md(text)
            print(f"\nSaved {p}")
            return
        manual = dict((k, float(v)) for k, v in (x.split("=") for x in args.manual.split(","))) if args.manual else None
        df, errors = goldprice.snapshot(cfg, manual)
        text = goldprice.report(cfg, df, errors, args.home)
        p = save(text, load_settings(), "gold_prices.md")
        show_md(text)
        print(f"\nSaved {p}")
    elif args.cmd == "predict-index":
        from pe.index_predict import predict
        print(predict(args.universe_csv, args.current, args.size, args.demo))
    else:
        STATE.unlink(missing_ok=True)
        print("Execution window cleared. Update config/holdings.yaml with what you actually traded.")


if __name__ == "__main__":
    main()
