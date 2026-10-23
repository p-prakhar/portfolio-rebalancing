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
    "status": "your portfolio, other investments and limits at a glance",
    "profile": "set age, risk appetite, employer stock",
    "import-kite": "load your Zerodha Kite tradebook(s) as tax lots",
    "import-etrade": "load RSU/ESPP vests from an E*TRADE export",
    "add-lot": "type in one purchase by hand",
    "add-other": "add FD, PPF, EPF, NPS, mutual funds, gold, property...",
    "check": "today's plan as text",
    "site": "build and open the visual decision page",
    "backtest": "12-month replay of every strategy",
    "validate": "10-year robustness test (slow first time)",
    "gold": "today's city gold rates",
    "where": "where to find each number you need",
    "help": "list commands",
    "quit": "leave",
}

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
  If the layout is not recognised, use add-lot and type the vests in by hand (date, shares, rupee cost per share)."""

WHERE = """Where to find each number
  Equity/ETFs on Zerodha       console.zerodha.com > Reports > Tradebook (CSV)       -> import-kite
  Employer RSUs (E*TRADE)      At Work > My Account > Benefit History > Download     -> import-etrade
  Mutual funds (any AMC)       mfcentral.com > Consolidated Account Statement (free, emailed) or Coin > Holdings -> add-other
  Fixed deposits, savings      your bank app > Deposits / Accounts                   -> add-other
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


def _ns(**kw):
    base = dict(demo=False, refresh=False, holdings=None, policy=None, asof=None, days=365, open=False)
    base.update(kw)
    return Namespace(**base)


def dispatch(cmd: str) -> bool:
    import main as M
    cmd = cmd.strip().lower()
    if cmd in ("quit", "exit", "q"):
        return False
    if cmd in ("", "help", "?"):
        for c, d in COMMANDS.items():
            print(f"  {c:<14} {d}")
    elif cmd == "profile":
        do_profile()
    elif cmd == "import-kite":
        do_import_kite()
    elif cmd == "import-etrade":
        do_import_etrade()
    elif cmd == "add-lot":
        do_add_lot()
    elif cmd == "add-other":
        do_add_other()
    elif cmd == "status":
        do_status()
    elif cmd == "where":
        print(WHERE)
    elif cmd == "check":
        M.cmd_run(_ns())
    elif cmd == "site":
        import webbrowser
        out = M.cmd_site(_ns())
        webbrowser.open(out.as_uri())
    elif cmd == "backtest":
        M.cmd_backtest(_ns())
    elif cmd == "validate":
        M.cmd_validate(Namespace(years=10, window_years=3, refresh=False))
    elif cmd == "gold":
        sys.argv = ["main.py", "gold-prices"]
        M.main()
    else:
        print(f"  Unknown command '{cmd}'. Type help.")
    return True


def run_shell() -> None:
    print("Portfolio engine. Type a command (Tab completes, Up recalls); `help` lists them.\n")
    if not (ROOT / "config" / "holdings.yaml").exists():
        print("First time? Suggested order: profile -> import-kite -> import-etrade (if you have RSUs) -> add-other -> site\n")
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
            print("\n(cancelled)")
        except Exception as exc:   # keep the shell alive; show the cause
            print(f"  Error: {type(exc).__name__}: {exc}")
