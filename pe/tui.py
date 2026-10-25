"""Guided interactive shell with autocomplete (prompt_toolkit). Start it with `python main.py`.

Every question explains where to find the answer. Nothing here places orders.
"""
from __future__ import annotations

import glob
import os
import sys
import tempfile
from argparse import Namespace
from datetime import date

import pandas as pd

from .config import ROOT, load_settings
from .profile import (KINDS, OTHER_PATH, PROFILE_PATH, RISK_LEVELS, OtherAsset, Profile, load_other, load_profile,
                      merge_lots, save_other, save_profile)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import FuzzyCompleter, PathCompleter, WordCompleter
    from prompt_toolkit.history import FileHistory
    HAVE_PT = sys.stdin.isatty()
except Exception:   # not installed or not a terminal: plain input() still works
    HAVE_PT = False

COMMANDS = {
    "next": "what should I do now? a short checklist from what is missing",
    "setup": "guided first run: profile, income and imports, step by step",
    "status": "your portfolio, other investments and limits at a glance",
    "profile": "set age, risk appetite, employer stock",
    "income": "salary, RSU income, regime and carried-forward losses for exact tax",
    "import-kite": "load your Zerodha Kite tradebook(s) as tax lots",
    "import-etrade": "load RSU/ESPP vests from an E*TRADE export",
    "add-lot": "type in one purchase by hand",
    "add-fd": "add a fixed deposit (SBI, IDFC FIRST or any bank)",
    "fds": "your FDs: value today, after-tax yield, cost of breaking early",
    "import-mf": "load all your mutual funds from a CAS statement PDF",
    "add-mf": "add one mutual fund purchase by hand",
    "mf": "your mutual funds: regular or direct, and whether switching pays",
    "add-other": "add PPF, EPF, NPS, gold, property and anything else",
    "check": "today's plan as text",
    "crash": "crash guard: early-warning signals and what a fast exit would cost today",
    "crash-test": "replay past falls: drawdown saved vs false-alarm cost (slow first time)",
    "site": "build and open the visual decision page",
    "backtest": "12-month replay of every strategy",
    "validate": "10-year robustness test (slow first time)",
    "gold": "today's city gold rates",
    "silver": "today's city silver rates",
    "compare": "metals, semiconductors, India vs abroad: returns after cost and tax",
    "simulate": "follow every strategy daily for 10, 5 and 2 years (a few minutes)",
    "timing": "compare ways of deciding when to rebalance (slow)",
    "switch": "test an automatic strategy switcher (run simulate first)",
    "forecast": "test valuation and forecast overlays (slow)",
    "where": "where to find each number you need",
    "help": "list commands",
    "quit": "leave",
}

GROUPS = [
    ("Start here", ["next", "setup", "status", "where"]),
    ("About you", ["profile", "income"]),
    ("Load what you own", ["import-kite", "import-etrade", "import-mf", "add-fd", "add-mf", "add-lot", "add-other"]),
    ("See your savings", ["fds", "mf"]),
    ("Decide", ["site", "check", "crash"]),
    ("Research (slower)", ["backtest", "validate", "simulate", "compare", "crash-test", "timing", "switch", "forecast", "gold", "silver"]),
    ("Shell", ["help", "quit"]),
]
EXAMPLES = """Examples
  next          what to do now, based on what is still missing
  setup         a guided first run: profile, income, then your imports, each one skippable
  import-kite   then give a path like ~/Downloads/tradebook-*.csv (Tab completes paths)
  site          builds the decision page and opens it in your browser"""

KITE_GUIDE = """How to export from Zerodha Kite
  1. Open console.zerodha.com and log in (same login as Kite).
  2. Reports > Tradebook. Segment: Equity. Pick a date range (Console allows about one financial year at a time),
     then click the download arrow and choose CSV. Repeat for each earlier year you traded, so every buy is covered.
  3. Save the CSVs anywhere. Next, give me the file path(s); Tab completes the path, and * works (e.g. ~/Downloads/tradebook-*.csv).
  Why the tradebook and not Holdings? Holdings has no purchase dates, so I could not tell long-term from short-term lots.
  Sells are matched against buys first-in-first-out, which is how Indian tax treats demat shares.
  Mutual funds bought on Coin are not in the tradebook: add them with add-other (see `where`)."""

ETRADE_GUIDE = """How to export RSUs from E*TRADE (Morgan Stanley at Work)
  1. Log in to etrade.com > At Work > My Account > Benefit History.
  2. Click Download > Download Expanded. Choose the file format (CSV or Excel); either works here.
  3. If you already sold some shares, also tell me how many in total, and I will remove the oldest first.
  The file gives the vest date, shares and value at vest. In India the vest value is taxed as salary, and later gains are measured
  from that same value; shares held over 24 months are long term. I convert dollars to rupees at the market rate on the vest date;
  your payslip uses the SBI rate, so differences of a rupee or two per dollar are possible.
  If the layout is not recognised, use add-lot and type the vests in by hand (date, shares, rupee cost per share).
  The stock-plan account is treated as SELL ONLY: the engine may suggest selling these shares there, never buying.
  Any US purchase it suggests goes through a separate LRS broker (IBKR, INDmoney, Vested), funded from your Indian bank."""

WHERE = """Where to find each number
  Equity/ETFs on Zerodha       console.zerodha.com > Reports > Tradebook (CSV)       -> import-kite
  Employer RSUs (E*TRADE)      At Work > My Account > Benefit History > Download     -> import-etrade
  Mutual funds (any AMC)       CAS PDF from camsonline.com or mfcentral.com (see import-mf) -> import-mf
  Fixed deposits               SBI: YONO > Deposits; IDFC FIRST: app > Deposits; or the FD advice -> add-fd
  Savings balances             your bank app > Accounts                              -> add-other
  EPF                          passbook.epfindia.gov.in or the UMANG app > EPF passbook -> add-other
  PPF                          bank or post office passbook / net banking             -> add-other
  NPS                          enps.nsdl.co.in or your CRA login > Transaction statement -> add-other
  Gold (jewellery/coins)       grams you own x today's rate (run: gold)               -> add-other
  Property                     your estimate of today's resale value minus loan left  -> add-other
  US stocks outside E*TRADE    your broker's Positions page in USD x today's USD/INR  -> add-other
Your age, risk appetite and expenses are asked in `profile`."""


def _ask(prompt: str, completer=None, default: str = "", history: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    if HAVE_PT:
        sess = PromptSession(history=FileHistory(str(ROOT / "state" / history)) if history else None)
        (ROOT / "state").mkdir(exist_ok=True)
        ans = sess.prompt(f"{prompt}{suffix}: ", completer=completer, complete_while_typing=True)
    else:
        ans = input(f"{prompt}{suffix}: ")
    ans = ans.strip()
    return ans or default


def _choice(prompt: str, options: list[str], default: str = "") -> str:
    while True:
        a = _ask(f"{prompt} ({'/'.join(options)})", WordCompleter(options, ignore_case=True) if HAVE_PT else None, default).lower()
        if a in options:
            return a
        print(f"  Please pick one of: {', '.join(options)}")


def _number(prompt: str, default: float | None = None, lo: float = 0, hi: float = 1e12) -> float:
    while True:
        a = _ask(prompt, default=("" if default is None else f"{default:g}")).replace(",", "").replace("_", "")
        try:
            v = float(a)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print(f"  Enter a number between {lo:g} and {hi:g}.")


def _date(prompt: str) -> date:
    while True:
        a = _ask(prompt + " (YYYY-MM-DD)")
        try:
            return date.fromisoformat(a)
        except ValueError:
            print("  Use the form 2024-08-14.")


def _paths(prompt: str) -> list[str]:
    a = _ask(prompt, PathCompleter(expanduser=True) if HAVE_PT else None)
    out = []
    for p in a.split():
        out += sorted(glob.glob(os.path.expanduser(p))) or [os.path.expanduser(p)]
    return [p for p in out if os.path.isfile(p)]


def do_profile() -> None:
    cur = load_profile() or Profile()
    print("Your profile never changes the trades; it sets limits the report checks you against.")
    cur.age = int(_number("Age", cur.age, 18, 90))
    cur.risk = _choice("Risk appetite", list(RISK_LEVELS), cur.risk)
    cur.horizon_years = int(_number("Years until you need most of this money", cur.horizon_years, 1, 60))
    cur.monthly_expenses_inr = _number("Monthly expenses in Rs (0 to skip the emergency-fund check)", cur.monthly_expenses_inr)
    if cur.monthly_expenses_inr > 0:
        print("  Backups can make a smaller cash buffer reasonable. Leave any of these at 0 if you are not sure.")
        cur.health_cover_inr = _number("Health insurance cover in Rs (employer group + your own; policy card or HR portal)", cur.health_cover_inr)
        cur.term_cover_inr = _number("Term life cover in Rs (policy document)", cur.term_cover_inr)
        cur.credit_card_limit_inr = _number("Total credit card limit in Rs (card app or statement)", cur.credit_card_limit_inr)
        if cur.health_cover_inr or cur.credit_card_limit_inr:
            from .profile import emergency_months
            cur.count_backups = False
            print("  " + emergency_months(cur)[1])
            cur.count_backups = _choice("Count these backups and keep a smaller cash buffer?", ["no", "yes"], "no") == "yes"
            m, why = emergency_months(cur)
            print(f"  Cash buffer target: {m} months of expenses. {why if cur.count_backups else ''}")
    cur.has_rsu = _choice("Do you get RSUs/ESPP from a US-listed employer?", ["yes", "no"], "yes" if cur.has_rsu else "no") == "yes"
    if cur.has_rsu:
        cur.employer_ticker = _ask("Employer stock ticker (e.g. MSFT)", default=cur.employer_ticker).upper()
        cur.employer_broker = "etrade"
    save_profile(cur)
    print(f"Saved {PROFILE_PATH.name}. Equity guide for you: {cur.equity_cap():.0%} of everything you own.")
    if cur.has_rsu:
        print("Next: run import-etrade to load your vests.")


def do_import_kite() -> None:
    print(KITE_GUIDE)
    files = _paths("Tradebook CSV path(s)")
    if not files:
        print("No readable files found.")
        return
    from .importer import lots_from_tradebook
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    dup = [c for c in df.columns if c.lower() in ("trade_id", "order_id")]
    if "trade_id" in df.columns:
        df = df.drop_duplicates(subset=["trade_id"])
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as t:
        df.to_csv(t.name, index=False)
    lots, warns = lots_from_tradebook(t.name)
    os.unlink(t.name)
    for w in warns:
        print("  note:", w)
    if not lots:
        print("No open lots found (everything was sold?).")
        return
    merge_lots(lots)
    print(f"Imported {len(lots)} open lot(s) across {len({l['symbol'] for l in lots})} symbol(s); old lots for those symbols were replaced. Run `status` to review.")


def do_import_etrade() -> None:
    print(ETRADE_GUIDE)
    prof = load_profile()
    ticker = _ask("Employer ticker", default=(prof.employer_ticker if prof else "")).upper()
    files = _paths("Benefit History file (.csv or .xlsx)")
    if not ticker or not files:
        print("Need a ticker and a readable file.")
        return
    sold = _number("Shares already sold in total (0 if none)", 0)
    from .etrade import fx_lookup, lots_from_etrade
    print("Fetching USD/INR history...")
    try:
        fx = fx_lookup()
    except Exception as exc:
        rate = _number(f"Could not fetch rates ({exc}). USD/INR to use for all vests", 85, 50, 200)
        fx = lambda d: rate
    try:
        lots, meta, warns = lots_from_etrade(files[0], ticker, fx, sold)
    except ValueError as exc:
        print("  ", exc)
        return
    for w in warns:
        print("  note:", w)
    if lots:
        merge_lots(lots, meta, replace_symbols={ticker})
        print(f"Imported {len(lots)} lot(s) of {ticker}, {sum(l['qty'] for l in lots):,.2f} shares in total.")
        if prof is None or prof.employer_ticker != ticker:
            p = prof or Profile()
            p.employer_ticker, p.has_rsu, p.employer_broker = ticker, True, "etrade"
            save_profile(p)


def do_add_lot() -> None:
    syms = sorted(load_settings().assets)
    sym = _ask("Symbol (Tab to see known ones; any NSE symbol works)", WordCompleter(syms, ignore_case=True) if HAVE_PT else None).upper()
    if not sym:
        return
    d = _date("Purchase date")
    qty = _number("Quantity", None, 1e-6)
    price = _number("Cost per unit in Rs (for US shares: dollars x USD/INR on that day)", None, 1e-6)
    merge_lots([{"symbol": sym, "qty": qty, "buy_date": str(d), "price": price}], replace_symbols=set())
    print(f"Added {qty:g} {sym}.")


def do_add_other() -> None:
    kinds = list(KINDS)
    k = _choice("Kind", kinds)
    cls, where, liquid = KINDS[k]
    print(f"  Where to find it: {where}")
    name = _ask("Short name (e.g. 'HDFC FD', 'EPF')", default=k.replace("_", " "))
    val = _number("Current value in Rs", None, 0)
    items = [o for o in load_other() if o.name != name] + [OtherAsset(k, name, val)]
    save_other(items)
    print(f"Saved. Counted as {cls}{' (liquid)' if liquid else ''}.")


def do_income() -> None:
    from .profile import INCOME_WHERE, marginal_slab
    print(INCOME_WHERE)
    p = load_profile() or Profile()
    p.tax_regime = _choice("Tax regime", ["new", "old"], p.tax_regime)
    p.gross_salary_inr = _number("Gross salary this financial year, Rs (without RSUs)", p.gross_salary_inr)
    p.rsu_perquisite_inr = _number("RSU/ESPP income taxed as salary this year, Rs", p.rsu_perquisite_inr)
    p.other_income_inr = _number("Other income: interest, dividends, rent, Rs", p.other_income_inr)
    if p.tax_regime == "old":
        p.deductions_inr = _number("Deductions (80C, 80D, HRA, home loan), Rs", p.deductions_inr)
    p.carried_st_loss_inr = _number("Short-term capital loss carried forward, Rs (ITR Schedule CFL; 0 if none)", p.carried_st_loss_inr)
    p.carried_lt_loss_inr = _number("Long-term capital loss carried forward, Rs", p.carried_lt_loss_inr)
    save_profile(p)
    print("Saved. " + marginal_slab(p)[2])


def do_add_fd() -> None:
    from . import fd as F
    bank = _choice("Bank", list(F.BANKS), "sbi")
    print(f"  Where to find the details: {F.BANKS[bank]['where']}")
    principal = _number("Amount deposited (Rs)", None, 1)
    rate = _number("Interest rate in % a year (as on the FD advice)", None, 0.1, 20) / 100
    start = _date("Start date")
    months = int(_number("Tenure in months (e.g. 12, 24, 60)", 12, 1, 240))
    payout = _choice("Interest paid", ["cumulative", "quarterly", "monthly"], "cumulative")
    senior = _choice("Senior citizen deposit?", ["no", "yes"], "no") == "yes"
    label = _ask("Short name", default=f"{F.BANKS[bank]['name']} {months}m")
    items = [x for x in F.load() if x.label != label] + [F.FD(bank, principal, rate, start, months, payout, label, None, senior)]
    F.save(items)
    print(f"Saved. Matures on {items[-1].maturity}. {F.BANKS[bank]['penalty_note']}")


def do_fds() -> None:
    from . import fd as F
    rows = F.summary(F.load(), load_settings().tax["slab_rate"])
    if not rows:
        print("No FDs yet. Run add-fd.")
        return
    for r in rows:
        print(f"  {r['label']:<22} Rs {r['value_today']:>11,.0f} today, {r['rate']:.2%} booked ({r['after_tax_yield']:.2%} after tax), matures {r['maturity']} "
              f"({r['days_left']} days). Breaking today: Rs {r['break_value_today']:,.0f}." + (" TDS likely this year." if r["tds_likely"] else ""))


def do_import_mf() -> None:
    from . import mf as M
    print(M.WHERE)
    files = _paths("CAS PDF path")
    if not files:
        print("No readable file found.")
        return
    import getpass
    pw = getpass.getpass("CAS password (the one you set when requesting it; not shown, not saved): ")
    try:
        cas = M.read_cas(files[0], pw)
    except Exception as exc:
        print(f"  Could not read the PDF ({type(exc).__name__}: {exc}). Check the password, or use add-mf.")
        return
    lots, meta, warns = M.lots_from_cas(cas)
    for w in warns:
        print("  note:", w)
    if not lots:
        print("No open mutual fund holdings found in the statement.")
        return
    merge_lots(lots, meta, replace_symbols=set(meta))
    print(f"Imported {len(lots)} lot(s) in {len(meta)} fund(s). Run `mf` to see regular vs direct costs.")


def do_add_mf() -> None:
    from . import mf as M
    q = _ask("Fund name to search (e.g. 'axis bluechip')")
    if not q:
        return
    try:
        hits = M.search(q)[:12]
    except Exception as exc:
        print(f"  Search failed ({exc}).")
        return
    if not hits:
        print("  No match. Try fewer words.")
        return
    for i, h in enumerate(hits, 1):
        print(f"  {i:>2}. {h['schemeName']}")
    k = int(_number("Pick the exact plan you hold (number)", 1, 1, len(hits))) - 1
    h = hits[k]
    d = _date("Purchase date")
    nav = M.nav_series(h["schemeCode"])
    px = float(nav[:str(d)].iloc[-1]) if len(nav[:str(d)]) else float(nav.iloc[0])
    amt = _number(f"Amount invested in Rs (NAV that day about {px:,.2f})", None, 1)
    cat = M.scheme_meta(h["schemeCode"]).get("scheme_category", "")
    sym = M.symbol_for(h["schemeCode"])
    merge_lots([{"symbol": sym, "qty": round(amt / px, 4), "buy_date": str(d), "price": round(px, 4)}],
               {sym: M.asset_meta(h["schemeCode"], h["schemeName"], cat, d)}, replace_symbols=set())
    print(f"Added {amt / px:,.3f} units of {h['schemeName']}." + (" This is a REGULAR plan; run `mf` to see what it costs you." if M.is_regular(h["schemeName"]) else ""))


def do_mf() -> None:
    from . import mf as M
    from .config import load_holdings
    rows = M.holdings_report(load_holdings().lots, load_settings())
    if not rows:
        print("No mutual funds yet. Run import-mf or add-mf.")
        return
    for r in rows:
        line = f"  {r['name'][:60]:<60} Rs {r['value']:>11,.0f}"
        if r["regular"] and r.get("gap") is not None:
            line += (f"\n    Regular plan: gave up {r['gap']:.2%} a year against the direct plan (about Rs {r['yearly_cost']:,.0f} a year at today's value)."
                     f"\n    Switching now costs about Rs {r['switch_tax']:,.0f} tax" + (f" plus about Rs {r['exit_load_est']:,.0f} exit load" if r['exit_load_est'] else "")
                     + (f"; pays back in {r['breakeven_years']:.1f} years." if r.get('breakeven_years') else "."))
        elif r["regular"]:
            line += "\n    Regular plan; no direct twin found to compare."
        else:
            line += "  (direct plan)"
        print(line)


def do_status() -> None:
    from .config import load_holdings
    h = load_holdings()
    others, prof = load_other(), load_profile()
    print("\nProfile:", f"age {prof.age}, {prof.risk}, equity guide {prof.equity_cap():.0%}" if prof else "not set (run: profile)")
    print("Lots:")
    if not h.lots and not h.pending_amounts:
        print("  none yet (run: import-kite, import-etrade or add-lot)")
    for l in h.lots:
        print(f"  {l.symbol:<12} {l.qty:>12,.2f} units  bought {l.buy_date}  cost Rs {l.cost:>12,.0f}")
    for p in h.pending_amounts:
        print(f"  {p['symbol']:<12} Rs {p['amount_inr']:>12,.0f} on {p['buy_date']} (units derived from that day's close)")
    if others:
        print("Other investments:")
        for o in others:
            print(f"  {o.name:<20} {o.kind:<20} Rs {o.value_inr:>12,.0f}")
    if not (ROOT / "config" / "holdings.yaml").exists():
        print("\n(Showing the example holdings. Import yours to replace them.)")


def _say(text: str, style: str = "") -> None:
    try:
        from rich.console import Console
        Console().print(text, style=style or None, highlight=False)
    except Exception:
        print(text)


def do_help() -> None:
    for title, cmds in GROUPS:
        _say(f"\n{title}", "bold")
        for c in cmds:
            if c in COMMANDS:
                print(f"  {c:<14} {COMMANDS[c]}")
    print("\n" + EXAMPLES)


def todo() -> list[tuple[str, str]]:
    """(command, reason) for each thing still missing, most useful first."""
    from . import fd as F
    items = []
    prof = load_profile()
    if prof is None:
        items.append(("profile", "set your age and risk appetite so the report can check your limits"))
    elif not (prof.gross_salary_inr or prof.rsu_perquisite_inr or prof.other_income_inr):
        items.append(("income", "add your salary so tax is worked out at your real slab, not a guessed 30%"))
    if not (ROOT / "config" / "holdings.yaml").exists():
        items.append(("import-kite", "load your shares and ETFs with real purchase dates (the page shows example numbers until then)"))
    if prof and prof.has_rsu:
        from .config import load_holdings
        if prof.employer_ticker and not any(l.symbol == prof.employer_ticker.upper() for l in load_holdings().lots):
            items.append(("import-etrade", f"load your {prof.employer_ticker} RSU vests"))
    try:
        from .config import load_holdings
        has_mf = any(l.symbol.startswith("MF") for l in load_holdings().lots)
    except Exception:
        has_mf = False
    if not has_mf:
        items.append(("import-mf", "load the mutual funds your advisor bought, from a CAS statement"))
    if not F.load():
        items.append(("add-fd", "add your SBI and IDFC FIRST fixed deposits"))
    if prof and prof.monthly_expenses_inr and not (prof.health_cover_inr or prof.credit_card_limit_inr):
        items.append(("profile", "optional: add insurance and card limits; they can justify a smaller cash buffer"))
    page = ROOT / "reports" / "index.html"
    import time
    if not page.exists() or time.time() - page.stat().st_mtime > 7 * 86400:
        items.append(("site", "build this week's decision page"))
    return items


def do_next() -> None:
    items = todo()
    if not items:
        _say("Everything is loaded. Run `site` for today's decision, or `check` for the text version.", "green")
        return
    _say("Next steps, most useful first:", "bold")
    for i, (c, why) in enumerate(items, 1):
        print(f"  {i}. {c:<13} {why}")


def do_setup() -> None:
    print("Guided setup. Each step can be skipped by answering 'skip'. Ctrl+C stops at any point; what you entered so far is saved.\n")
    steps = [("profile", do_profile, "Age, risk appetite, expenses, insurance and employer stock"),
             ("income", do_income, "Salary, RSU income and tax regime, for exact tax"),
             ("import-kite", do_import_kite, "Your Zerodha holdings with purchase dates"),
             ("import-etrade", do_import_etrade, "Your RSU vests from E*TRADE"),
             ("import-mf", do_import_mf, "Mutual funds from a CAS PDF"),
             ("add-fd", do_add_fd, "Fixed deposits")]
    for name, fn, what in steps:
        a = _choice(f"{what}: do it now?", ["yes", "skip"], "yes")
        if a == "yes":
            fn()
            print()
    do_next()


def _ns(**kw):
    base = dict(demo=False, refresh=False, holdings=None, policy=None, asof=None, days=365, open=False)
    base.update(kw)
    return Namespace(**base)


def dispatch(cmd: str) -> bool:
    import main as M
    cmd = cmd.strip().lower()
    if cmd in ("quit", "exit", "q"):
        return False
    if cmd in ("help", "?"):
        do_help()
    elif cmd == "":
        pass
    elif cmd == "next":
        do_next()
    elif cmd == "setup":
        do_setup()
    elif cmd == "profile":
        do_profile()
    elif cmd == "income":
        do_income()
    elif cmd == "import-kite":
        do_import_kite()
    elif cmd == "import-etrade":
        do_import_etrade()
    elif cmd == "add-lot":
        do_add_lot()
    elif cmd == "add-other":
        do_add_other()
    elif cmd == "add-fd":
        do_add_fd()
    elif cmd == "fds":
        do_fds()
    elif cmd == "import-mf":
        do_import_mf()
    elif cmd == "add-mf":
        do_add_mf()
    elif cmd == "mf":
        do_mf()
    elif cmd == "status":
        do_status()
    elif cmd == "where":
        print(WHERE)
    elif cmd == "check":
        M.cmd_run(_ns())
    elif cmd == "crash":
        M.cmd_crash(_ns())
    elif cmd == "crash-test":
        M.cmd_crash_test(Namespace(years=10, refresh=False, demo=False, scenario="bubble_burst"))
    elif cmd == "site":
        import webbrowser
        out = M.cmd_site(_ns())
        webbrowser.open(out.as_uri())
    elif cmd == "backtest":
        M.cmd_backtest(_ns())
    elif cmd == "validate":
        M.cmd_validate(Namespace(years=10, window_years=3, refresh=False))
    elif cmd == "compare":
        M.cmd_compare(None)
    elif cmd in ("simulate", "timing", "switch", "forecast"):
        sys.argv = ["main.py"] + ({"simulate": ["simulate-daily", "--all-strategies"]}.get(cmd) or [cmd])
        M.main()
    elif cmd == "silver":
        sys.argv = ["main.py", "gold-prices", "--metal", "silver"]
        M.main()
    elif cmd == "gold":
        sys.argv = ["main.py", "gold-prices"]
        M.main()
    else:
        import difflib
        near = difflib.get_close_matches(cmd, list(COMMANDS), n=2, cutoff=0.5)
        print(f"  '{cmd}' is not a command." + (f" Did you mean {' or '.join(near)}?" if near else "") + " Type help for the list.")
    return True


def run_shell() -> None:
    _say("Portfolio engine", "bold")
    print("Type a command and press Enter. Tab completes, Up recalls, `help` lists everything.\n")
    if load_profile() is None and not (ROOT / "config" / "holdings.yaml").exists():
        print("Looks like a first run. Type `setup` for a guided start, or `next` any time to see what is missing.\n")
    else:
        do_next()
        print()
    comp = FuzzyCompleter(WordCompleter(list(COMMANDS), meta_dict=COMMANDS, ignore_case=True)) if HAVE_PT else None
    (ROOT / "state").mkdir(exist_ok=True)
    sess = PromptSession(history=FileHistory(str(ROOT / "state" / "history")), completer=comp, complete_while_typing=True) if HAVE_PT else None
    while True:
        try:
            line = sess.prompt("pe> ") if sess else input("pe> ")
        except (EOFError, KeyboardInterrupt):
            break
        try:
            if not dispatch(line):
                break
        except KeyboardInterrupt:
            print("\n(cancelled; nothing after this point was saved)")
        except SystemExit as exc:
            print(f"  {exc}")
        except FileNotFoundError as exc:
            print(f"  Could not find {exc.filename}. Check the path; Tab completes it.")
        except Exception as exc:   # keep the shell alive; say what failed in one line, details go to state/shell_errors.log
            import traceback
            (ROOT / "state").mkdir(exist_ok=True)
            with open(ROOT / "state" / "shell_errors.log", "a") as f:
                f.write(traceback.format_exc() + "\n")
            msg = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
            hint = " Check your internet connection." if "connect" in msg.lower() or "timed out" in msg.lower() else ""
            print(f"  That did not work: {msg}.{hint} Details are in state/shell_errors.log.")
