"""JSON bridge between the engine and the Android app (android/).

Every public function takes plain values (a JSON string where the payload is structured) and returns a JSON string:
    {"ok": true, "data": ...}    or    {"ok": false, "kind": "no_holdings", "error": "message a person can read"}
so the app never has to understand Python objects, and the same calls can be tested with pytest on a laptop.

The app sets PE_HOME to its private storage before importing anything from `pe` (see pe/config.py), then calls `init()`,
which copies the shipped config files there. Personal files (holdings, profile, deposits) only ever live in PE_HOME.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path

import yaml

from .config import ROOT, load_holdings, load_settings, register_assets

log = logging.getLogger(__name__)

CONFIG = ROOT / "config"
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
HOLDINGS = CONFIG / "holdings.yaml"
APP_STATE = STATE / "app.json"
LAST = STATE / "mobile_last.json"
PENDING = STATE / "import_pending.json"
SHIPPED = ("settings.yaml", "asset_classes.yaml", "real_assets.yaml", "corporate_actions.yaml", "holdings.example.yaml")
PERSONAL = ("holdings.yaml", "profile.yaml", "other_assets.yaml", "fds.yaml")
EMPTY_REALISED = {"equity_stcg": 0, "equity_ltcg": 0, "other_stcg": 0, "other_ltcg": 0}

POLICIES = [
    {"id": "core_xs", "name": "Core and momentum satellite", "detail": "Keeps most of the money in a Nifty 50 core and rotates the rest into the strongest assets. The engine default."},
    {"id": "buy_hold", "name": "Buy and hold", "detail": "Never rotates. Only tax harvesting and guardrail warnings."},
    {"id": "custom", "name": "Keep what I own", "detail": "Keeps your own picks and sells only when several warning signs agree."},
    {"id": "core_satellite", "name": "Core and trend satellite", "detail": "Nifty 50 core with a trend-following satellite."},
    {"id": "static_mix", "name": "Fixed mix", "detail": "Fixed weights across equity, gold, US and cash, rebalanced when they drift."},
    {"id": "dual_momentum", "name": "Dual momentum", "detail": "All in equity, gold or cash, whichever trend is strongest."},
    {"id": "xs_momentum", "name": "Momentum rotation", "detail": "Holds the top few assets by 6 and 12 month momentum."},
    {"id": "risk_parity", "name": "Risk parity", "detail": "Weights assets so each adds similar risk. No forecasting."},
    {"id": "trend_vol", "name": "Trend with volatility target", "detail": "Holds assets above their trend and scales down when markets get rough."},
    {"id": "daa", "name": "Defensive asset allocation", "detail": "Uses two canary assets to decide when to go defensive."},
]

STARTERS = [
    {"id": "nifty", "title": "Nifty 50 index ETFs", "detail": "Everything in one or two Nifty 50 ETFs.",
     "split": {"NIFTYBEES": 1.0}, "cash": 0.0},
    {"id": "india_mix", "title": "India equity, gold and some cash", "detail": "Nifty 50, Next 50 and a gold ETF, with a tenth in cash.",
     "split": {"NIFTYBEES": 0.60, "JUNIORBEES": 0.15, "GOLDBEES": 0.15}, "cash": 0.10},
    {"id": "global_mix", "title": "India, US and gold", "detail": "Nifty 50, an India-listed Nasdaq 100 ETF and gold.",
     "split": {"NIFTYBEES": 0.55, "MON100": 0.20, "GOLDBEES": 0.15}, "cash": 0.10},
    {"id": "etf_stock", "title": "Index ETFs plus a stock", "detail": "Two Nifty 50 ETFs and one large company. The sample the engine ships with.",
     "split": {"NIFTYBEES": 0.476, "SETFNIF50": 0.476, "TCS": 0.048}, "cash": 0.0},
    {"id": "cash", "title": "Only cash so far", "detail": "Nothing invested yet. The plan shows where the engine would put it.",
     "split": {}, "cash": 1.0},
]


class ApiError(Exception):
    def __init__(self, kind: str, message: str, **extra):
        super().__init__(message)
        self.kind, self.extra = kind, extra


def _clean(o):
    from .site import _clean as c
    return c(o)


def api(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return json.dumps({"ok": True, "data": _clean(fn(*a, **k))}, default=str)
        except ApiError as e:
            return json.dumps({"ok": False, "kind": e.kind, "error": str(e), **e.extra}, default=str)
        except Exception as e:   # anything unexpected still reaches the app as a readable message
            log.exception("%s failed", fn.__name__)
            return json.dumps({"ok": False, "kind": "internal", "error": f"{type(e).__name__}: {e}"})
    return wrapper


def _arg(payload) -> dict:
    if payload is None or payload == "":
        return {}
    return payload if isinstance(payload, dict) else json.loads(str(payload))


def _main():
    import main      # the CLI module holds the orchestration helpers; the app ships it next to the pe package
    return main


# ---------------------------------------------------------------- setup and state
def _ensure_dirs() -> None:
    for d in (CONFIG, STATE, REPORTS, ROOT / "data"):
        d.mkdir(parents=True, exist_ok=True)


def _shipped_dir() -> Path | None:
    try:
        import pe_shipped       # generated by the Android build: a copy of config/*.yaml
        return Path(pe_shipped.__file__).parent
    except Exception:
        return None


@api
def init():
    """Create the folders and refresh the shipped (non-personal) config files. Safe to call on every app start."""
    _ensure_dirs()
    src = _shipped_dir()
    if src is not None:
        for name in SHIPPED:
            if (src / name).exists():
                shutil.copyfile(src / name, CONFIG / name)
    return _status()


def _app_state() -> dict:
    if APP_STATE.exists():
        try:
            return json.loads(APP_STATE.read_text())
        except Exception:
            return {}
    return {}


def _save_app_state(d: dict) -> None:
    _ensure_dirs()
    APP_STATE.write_text(json.dumps(d))


def _settings():
    s = load_settings()
    st = _app_state()
    if st.get("policy"):
        s.strategy["policy"] = st["policy"]
    if "crash_enabled" in st and s.strategy.get("crash") is not None:
        s.strategy["crash"]["enabled"] = bool(st["crash_enabled"])
    if st.get("execution") in ("secretary", "immediate"):
        s.timing["execution"] = st["execution"]
    return s


def _doc() -> dict:
    if HOLDINGS.exists():
        doc = yaml.safe_load(HOLDINGS.read_text()) or {}
    else:
        doc = {}
    doc.setdefault("lots", [])
    doc.setdefault("cash_inr", 0)
    doc.setdefault("realised_this_fy", dict(EMPTY_REALISED))
    doc.setdefault("lrs_remitted_this_fy_inr", 0)
    return doc


def _write_doc(doc: dict) -> None:
    _ensure_dirs()
    if HOLDINGS.exists():
        HOLDINGS.with_suffix(".yaml.bak").write_text(HOLDINGS.read_text())
    for l in doc.get("lots", []):
        l["buy_date"] = str(l["buy_date"])
    HOLDINGS.write_text("# Tax lots (private to this device). One entry per purchase.\n"
                        + yaml.safe_dump(doc, sort_keys=False, default_flow_style=None))


def _status() -> dict:
    from .profile import load_profile
    doc = _doc() if HOLDINGS.exists() else None
    last = None
    if LAST.exists():
        try:
            j = json.loads(LAST.read_text())
            last = {"asof": j.get("asof"), "call": j["verdict"]["call"], "headline": j["verdict"]["headline"], "nav": j.get("nav"),
                    "checked_at": j.get("checked_at")}
        except Exception:
            last = None
    return {"has_holdings": bool(doc and (doc["lots"] or float(doc.get("cash_inr") or 0) > 0)),
            "has_profile": load_profile() is not None,
            "lots": len(doc["lots"]) if doc else 0,
            "symbols": sorted({l["symbol"] for l in doc["lots"]}) if doc else [],
            "last": last, "settings": _settings_view(), "home": str(ROOT)}


@api
def status():
    return _status()


# ---------------------------------------------------------------- the daily check
def _require_holdings() -> None:
    if not HOLDINGS.exists():
        raise ApiError("no_holdings", "Add your holdings first: import a file, pick a starting portfolio, or type them in.")


def _resolve_amounts(h, px, warns: list[str]):
    """Amount-only lots -> units at the close on (or after) the purchase date. Never raises: a symbol without prices keeps its amount."""
    from .config import Lot
    for p in h.pending_amounts:
        series = px[p["symbol"]].dropna() if p["symbol"] in px else None
        if series is None or series.empty:
            warns.append(f"{p['symbol']}: no price history found, so it is shown at the amount you entered. Check the symbol.")
            h.lots.append(Lot(p["symbol"], float(p["amount_inr"]), p["buy_date"], 1.0))
            continue
        after = series[series.index >= str(p["buy_date"])]
        if after.empty:
            price = float(series.iloc[-1])
        else:
            price = float(after.iloc[0])
            if str(series.index[0].date()) > str(p["buy_date"]):
                warns.append(f"{p['symbol']}: bought before the price history starts ({series.index[0].date()}), so the cost per unit is taken "
                             "from the first price available. Edit the lot with your real quantity and price for exact tax numbers.")
        h.lots.append(Lot(p["symbol"], p["amount_inr"] / price, p["buy_date"], price))
    h.pending_amounts = []
    return h


def _materialise(h_lots, px) -> None:
    """Rewrite amount-only lots in holdings.yaml as quantity and price once prices are known, so the lots stay fixed."""
    doc = _doc()
    changed = False
    for l in doc["lots"]:
        if "qty" in l or "amount_inr" not in l:
            continue
        series = px[l["symbol"]].dropna() if l["symbol"] in px else None
        if series is None or series.empty:
            continue
        after = series[series.index >= str(l["buy_date"])]
        price = float(after.iloc[0]) if not after.empty else float(series.iloc[-1])
        l["qty"] = round(float(l.pop("amount_inr")) / price, 6)
        l["price"] = round(price, 4)
        changed = True
    if changed:
        _write_doc(doc)


def _context(demo: bool, refresh: bool):
    from .profile import apply_broker_rules
    m = _main()
    _require_holdings()
    settings = _settings()
    prof, tax_note = m._tax_setup(settings)
    h = load_holdings()
    register_assets(settings, h)
    apply_broker_rules(settings, prof)
    try:
        px, vix, fx, note = m.load_data(settings, demo, refresh)
    except Exception as exc:
        from . import yahoo_lite
        detail = "; ".join(yahoo_lite.last_errors[:2])
        raise ApiError("no_prices", "Could not get market prices. Check the internet connection and try again."
                       + (f" ({detail})" if detail else f" ({type(exc).__name__})"))
    if px.empty or "NIFTYBEES" not in px or px["NIFTYBEES"].dropna().empty:
        raise ApiError("no_prices", "Market prices came back empty. Check the internet connection and try again.")
    warns: list[str] = []
    held = {l.symbol for l in h.lots} | {p["symbol"] for p in h.pending_amounts}
    for s in sorted(held):
        if s != "CASH" and (s not in px or px[s].dropna().empty):
            warns.append(f"{s}: no price found, valued at what you paid. Check the symbol in Portfolio.")
    h = _resolve_amounts(h, px, warns)
    usd = float(fx.dropna().iloc[-1]) if fx is not None and not fx.dropna().empty else None
    return m, settings, prof, tax_note, h, px, vix, fx, note, usd, warns


def _build(demo: bool, refresh: bool, backtest: bool) -> dict:
    from . import fd as F, site
    from .engine import make_plan
    from .profile import OtherAsset, load_other, load_profile
    m, settings, prof, tax_note, h, px, vix, fx, note, usd, warns = _context(demo, refresh)
    realised = m._fy_realised(h, prof)
    mem = m.guard_mem_load()
    plan = make_plan(px.index[-1], h.lots, h.cash_inr, px, vix, settings, realised,
                     lrs_used=h.lrs_remitted_this_fy_inr, usd_inr=usd, guard_mem=mem)
    if not demo:
        m.guard_mem_save(mem)
        _materialise(h.lots, px)
    timing = m.timing_step(plan, px, settings) if not demo else []
    bt = None
    if backtest:
        from .backtest import run_all
        start = px.index[-1] - timedelta(days=365)
        curves, table, logs = run_all(h.lots, px, vix, settings, start, fx)
        bt = (curves, table, logs, start)
    vpath = REPORTS / "validation.json"
    validation = json.loads(vpath.read_text()) if vpath.exists() else None
    fds = F.load()
    others = load_other() + [OtherAsset("fixed_deposit", f.label or f"{f.bank} FD", f.value_on(date.today())) for f in fds]
    data = site.build(plan, settings, timing, px, bt, load_profile(), others, validation, note, usd, None)
    data["tax_note"] = tax_note or ("No income entered, so slab-taxed income is assumed to be at "
                                    f"{settings.tax['slab_rate']:.0%}. Add your income under Profile to make the tax plan exact.")
    data["fds"] = F.summary(fds, settings.tax["slab_rate"], settings.tax["cess"])
    data["fd_banks"] = {k: {"name": v["name"], "where": v["where"], "penalty_note": v["penalty_note"]} for k, v in F.BANKS.items()}
    data["mfs"], data["mf_where"] = [], ""
    if any(l.symbol.startswith("MF") for l in h.lots) and not demo:
        try:
            from . import mf as M
            data["mfs"], data["mf_where"] = M.holdings_report(h.lots, settings), M.WHERE
        except Exception as exc:
            warns.append(f"Mutual fund comparison skipped ({type(exc).__name__}).")
    data["example"] = False
    try:
        data["crash"] = site.crash_block(plan, settings, h, px, vix, usd, realised)
    except Exception as exc:
        data["crash"] = None
        warns.append(f"Crash guard view skipped ({type(exc).__name__}).")
    data["daily_sim"] = data["daily_sim_all"] = data["years"] = None
    data["warnings"] = warns
    data["demo"] = demo
    data["deferred"], data["blocked"] = plan.deferred[:8], plan.blocked[:8]
    data["tax_before"], data["tax_after"] = round(plan.tax_before), round(plan.tax_after)
    data["window_open"] = m.STATE.exists()
    data["checked_at"] = _now()
    # the app's copy should not point at shell commands
    for s_ in data.get("steps", []):
        s_.pop("cmd", None)
        s_["detail"] = _appify(s_["detail"])
    data["timing"] = [_appify(t) for t in data.get("timing", [])]
    for g in data.get("guardrails", []):
        g["detail"] = _appify(g["detail"])
    return data


_APP_COPY = (
    ("Open the shell (`python main.py shell`) and re-import", "Re-import"),
    ("Re-import your tradebook in the shell (or edit config/holdings.yaml with your real fills), then run `python main.py reset-window` to close the execution window.",
     "Mark each trade as done in the Plan tab (or re-import your tradebook), then close the window."),
    ("Run `python main.py reset-window` after placing the trades.", "Close the window in the Plan tab after placing the trades."),
    ("Run `python main.py shell` and choose profile to set age and risk appetite", "Add your age and risk appetite under Profile"),
    ("Run `income` in the shell", "Add your income under Profile"),
)


def _appify(text: str) -> str:
    for a, b in _APP_COPY:
        text = text.replace(a, b)
    return text


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


@api
def check(refresh=False, demo=False):
    """Today's verdict and plan. Fast path: no 12-month replay (see full_report)."""
    data = _build(bool(demo), bool(refresh), backtest=False)
    if not demo:
        _ensure_dirs()
        LAST.write_text(json.dumps(_clean(data), default=str))
    return data


@api
def last_check():
    """The saved result of the last check, for an instant first screen. None if there is none."""
    return json.loads(LAST.read_text()) if LAST.exists() else None


@api
def full_report(refresh=False, demo=False):
    """The engine's full offline HTML page (12-month replay, charts). Slower. Returns {path, verdict}."""
    from . import site
    data = _build(bool(demo), bool(refresh), backtest=True)
    out = site.render(data, REPORTS / "index.html")
    return {"path": str(out), "call": data["verdict"]["call"], "headline": data["verdict"]["headline"]}


@api
def reset_window():
    m = _main()
    m.STATE.unlink(missing_ok=True)
    return True


# ---------------------------------------------------------------- backtest on your own lots, and the replayed waiting window
_BT: dict = {}      # the prepared backtest (prices, lots, start day) kept between calls so each strategy can report as it finishes


def _bt_context(p: dict) -> dict:
    from . import replay
    demo, rng = bool(p.get("demo")), str(p.get("range") or "purchase")
    key = (demo, rng, HOLDINGS.stat().st_mtime if HOLDINGS.exists() else 0, json.dumps(_app_state(), sort_keys=True))
    if _BT.get("key") == key:
        return _BT
    m, settings, prof, tax_note, h, px, vix, fx, note, usd, warns = _context(demo, False)
    lots = [l for l in h.lots if l.symbol in settings.assets and l.qty > 0]
    if not lots:
        raise ApiError("no_holdings", "The backtest needs at least one holding with a purchase date.")
    try:
        ctx = replay.prepare(lots, px, rng)
    except ValueError:
        raise ApiError("no_prices", "There is not enough price history yet to replay your purchases.")
    _BT.clear()
    _BT.update(key=key, ctx=ctx, vix=vix, fx=fx, settings=settings, note=note, warns=warns, cash=float(h.cash_inr or 0))
    return _BT


@api
def backtest_setup(payload=None):
    """Prepare a replay of the investor's own purchases. payload: {range: purchase | 1y | 6m, demo?}.
    Returns the dates, the money put in over time and the list of strategies; call backtest_run(id) for each."""
    from . import replay
    bt = _bt_context(_arg(payload))
    out = replay.setup_view(bt["ctx"])
    out.update(data_note=bt["note"], warnings=bt["warns"], cash_left_out=round(bt["cash"]), current_policy=_settings().strategy["policy"])
    return out


@api
def backtest_run(strategy_id, payload=None):
    """One strategy over the prepared replay: value curve, after-tax result, where the money sat and how much moved each month."""
    from . import replay
    bt = _bt_context(_arg(payload))
    try:
        return replay.run_strategy(bt["ctx"], str(strategy_id), bt["vix"], bt["settings"], bt["fx"])
    except ValueError as exc:
        raise ApiError("invalid", str(exc))


def _replay(demo: bool) -> dict:
    from . import replay
    from .engine import make_plan
    m, settings, prof, tax_note, h, px, vix, fx, note, usd, warns = _context(demo, False)
    tm = settings.timing
    n = int(tm["window_days"])
    realised = m._fy_realised(h, prof)
    mem = dict(m.guard_mem_load())
    plan = make_plan(px.index[-1], h.lots, h.cash_inr, px, vix, settings, realised, lrs_used=h.lrs_remitted_this_fy_inr, usd_inr=usd, guard_mem=dict(mem))
    legs = [t for t in plan.trades if not t.kind.startswith("harvest") and t.symbol != "CASH" and t.symbol in px]
    out = {"asof": str(px.index[-1].date()), "n": n, "cutoff": replay.secretary_cutoff(n), "execution": tm.get("execution", "secretary"),
           "legs": [], "data_note": note, "window_open": m.STATE.exists()}
    if not legs:
        out.update(decision="none", headline="Nothing is waiting", detail="Today's plan has no trade that would use a waiting window.")
        return out
    days = px.index[-n:]
    on_plan: dict[tuple, list[bool]] = {(t.symbol, t.side): [] for t in legs}
    for ts in days[:-1]:        # what the daily check would have said on each earlier day, with the lots owned and data known that day
        try:
            lots_then = [l for l in h.lots if l.buy_date <= ts.date()]
            fxv = float(fx.loc[:ts].dropna().iloc[-1]) if fx is not None and not fx.loc[:ts].dropna().empty else usd
            pl = make_plan(ts, lots_then, h.cash_inr, px.loc[:ts], vix.loc[:ts] if vix is not None else None, settings, realised,
                           lrs_used=h.lrs_remitted_this_fy_inr, usd_inr=fxv, guard_mem=dict(mem))
            asked = {(t.symbol, t.side) for t in pl.trades if not t.kind.startswith("harvest")}
        except Exception:
            asked = set()
        for k in on_plan:
            on_plan[k].append(k in asked)
    for t in legs:
        series = px[t.symbol].ffill().loc[days]
        if series.isna().any():
            continue
        r = replay.replay_leg([str(d.date()) for d in days], [float(v) for v in series], on_plan[(t.symbol, t.side)] + [True], n, t.side)
        r.update(symbol=t.symbol, value=round(t.value), kind=t.kind, qty=t.qty,
                 never_waits=bool(t.kind == "risk_exit" and tm["regime_override_secretary"]))
        if r["never_waits"]:
            r["now"].update(decision="execute", reason="risk_exit", why="This trade cuts risk, so it never waits for a better price.")
        out["legs"].append(r)
    acts = [l for l in out["legs"] if l["now"]["decision"] == "execute"]
    waits = [l for l in out["legs"] if l["now"]["decision"] != "execute"]
    if not out["legs"]:
        out.update(decision="none", headline="Nothing is waiting", detail="The trades on today's plan have no recent prices to replay.")
    elif not waits:
        out.update(decision="execute", headline="No need to wait: place the trades today",
                   detail="Replayed over the days already gone, every waiting window has reached its trading day.")
    elif not acts:
        left = max(l["now"]["left"] for l in waits)
        out.update(decision="observe", headline=f"Keep watching: {left} trading day{'s' if left != 1 else ''} left at most",
                   detail="The plan only began asking for these trades recently, so the days already gone do not complete the window. "
                          "You can still count the full window from past prices below.")
    else:
        out.update(decision="mixed", headline=f"Place {len(acts)} of {len(out['legs'])} today, keep watching the rest",
                   detail="Sells and buys are judged one by one. Buys that depend on a sale should wait for that sale.")
    return out


@api
def secretary_replay(payload=None):
    """Where the waiting window would stand today had the check been run every day. payload: {demo?}. Changes nothing."""
    return _replay(bool(_arg(payload).get("demo")))


@api
def backdate_window(payload=None):
    """Open (or replace) the waiting window as if it had started in the past, with the closes since then filled in.
    payload: {mode: now | full, demo?}. `now` starts each trade's window on the day the plan first asked for it; `full`
    counts the whole window from the last n closes. The next check then reads the window like any other."""
    p = _arg(payload)
    full = str(p.get("mode") or "now") == "full"
    r = _replay(bool(p.get("demo")))
    if not r["legs"]:
        raise ApiError("invalid", "Today's plan has no trade that is waiting.")
    m = _main()
    legs, opened = [], r["asof"]
    for l in r["legs"]:
        w = l["full"] if full else l["now"]
        first = l["dates"].index(w["opened"])
        opened = min(opened, w["opened"])
        leg = {"symbol": l["symbol"], "side": l["side"], "value": l["value"], "kind": l["kind"],
               "observed": {d: pr for d, pr in zip(l["dates"][first:], l["prices"][first:])}}
        if w["decision"] == "execute" and w.get("fired"):
            leg["fired"] = w["fired"]
        legs.append(leg)
    _ensure_dirs()
    m.STATE.write_text(json.dumps({"opened": opened, "n": r["n"], "legs": legs, "replayed": True}, indent=1))
    LAST.unlink(missing_ok=True)
    return {"opened": opened, "legs": len(legs), "mode": "full" if full else "now"}


# ---------------------------------------------------------------- holdings
def _asset_names() -> dict:
    s = load_settings()
    names = {k: a.name for k, a in s.assets.items()}
    for sym, m in (_doc().get("assets") or {}).items():
        if m and m.get("name"):
            names[sym] = m["name"]
    return names


def _holdings_view() -> dict:
    doc = _doc()
    names = _asset_names()
    lots = []
    for i, l in enumerate(doc["lots"]):
        row = {"index": i, "symbol": l["symbol"], "name": names.get(l["symbol"], l["symbol"]), "buy_date": str(l["buy_date"]),
               "qty": l.get("qty"), "price": l.get("price"), "amount_inr": l.get("amount_inr"),
               "cost": (float(l["qty"]) * float(l["price"])) if "qty" in l else float(l.get("amount_inr") or 0)}
        lots.append(row)
    return {"lots": lots, "cash_inr": float(doc.get("cash_inr") or 0), "realised_this_fy": doc.get("realised_this_fy") or dict(EMPTY_REALISED),
            "lrs_remitted_this_fy_inr": float(doc.get("lrs_remitted_this_fy_inr") or 0), "assets": doc.get("assets") or {},
            "exists": HOLDINGS.exists()}


@api
def holdings():
    return _holdings_view()


def _fx_on(d: date, given: float | None = None) -> float:
    if given:
        return float(given)
    try:
        from .etrade import fx_lookup
        return fx_lookup()(d)
    except Exception:
        raise ApiError("need_usd_inr", "Could not look up the USD/INR rate. Enter the rate to use.", needs=["usd_inr"])


def _lot_from(p: dict) -> tuple[dict, dict]:
    """Validate one manual lot. Returns (lot, asset meta for the symbol or {})."""
    from .anyimport import clean_symbol
    sym = clean_symbol(p.get("symbol", ""))
    if not sym:
        raise ApiError("invalid", "Enter a symbol.")
    try:
        d = date.fromisoformat(str(p.get("buy_date") or date.today())[:10])
    except ValueError:
        raise ApiError("invalid", "Use a date like 2024-08-14.")
    if d > date.today():
        raise ApiError("invalid", "The purchase date is in the future.")
    meta: dict = {}
    usd = str(p.get("currency") or "").upper() == "USD"
    if p.get("mf_code"):
        from . import mf as M
        code = str(p["mf_code"])
        sym = M.symbol_for(code)
        name = p.get("name") or sym
        try:
            cat = M.scheme_meta(code).get("scheme_category", "")
        except Exception:
            cat = ""
        meta = M.asset_meta(code, name, cat, d)
        if not p.get("qty"):
            amt = float(p.get("amount_inr") or 0)
            if amt <= 0:
                raise ApiError("invalid", "Enter the amount invested, or units and NAV.")
            try:
                nav = M.nav_series(code)
            except Exception:
                raise ApiError("no_prices", "Could not fetch the fund's NAV history. Check the connection, or enter units and NAV.")
            px = float(nav[:str(d)].iloc[-1]) if len(nav[:str(d)]) else float(nav.iloc[0])
            return {"symbol": sym, "qty": round(amt / px, 4), "buy_date": str(d), "price": round(px, 4)}, {sym: meta}
    else:
        for k in ("ticker", "name", "tax_class", "venue", "sleeve"):
            if p.get(k):
                meta[k] = p[k]
        if usd:
            meta["currency"] = "USD"
    qty, price, amt = p.get("qty"), p.get("price"), p.get("amount_inr")
    if qty not in (None, "") and price not in (None, ""):
        qty, price = float(qty), float(price)
        if qty <= 0 or price <= 0:
            raise ApiError("invalid", "Quantity and price must be above zero.")
        if usd and str(p.get("price_currency") or "USD").upper() == "USD":
            price *= _fx_on(d, p.get("usd_inr"))
        lot = {"symbol": sym, "qty": round(qty, 6), "buy_date": str(d), "price": round(price, 4)}
    elif amt not in (None, ""):
        amt = float(amt)
        if amt <= 0:
            raise ApiError("invalid", "The amount must be above zero.")
        lot = {"symbol": sym, "buy_date": str(d), "amount_inr": amt}
    else:
        raise ApiError("invalid", "Enter quantity and price, or the amount invested.")
    return lot, ({sym: meta} if meta else {})


@api
def add_lot(payload):
    """payload: {symbol, buy_date, qty+price | amount_inr, currency?, usd_inr?, mf_code?, name?, ticker?}"""
    lot, meta = _lot_from(_arg(payload))
    doc = _doc()
    doc["lots"].append(lot)
    if meta:
        doc.setdefault("assets", {}).update(meta)
    _write_doc(doc)
    return _holdings_view()


@api
def update_lot(index, payload):
    doc = _doc()
    i = int(index)
    if not 0 <= i < len(doc["lots"]):
        raise ApiError("invalid", "That lot no longer exists.")
    p = _arg(payload)
    p.setdefault("price_currency", "INR")     # an existing lot's price is already in rupees
    lot, meta = _lot_from(p)
    doc["lots"][i] = lot
    if meta:
        doc.setdefault("assets", {}).update(meta)
    _write_doc(doc)
    return _holdings_view()


@api
def delete_lot(index):
    doc = _doc()
    i = int(index)
    if not 0 <= i < len(doc["lots"]):
        raise ApiError("invalid", "That lot no longer exists.")
    doc["lots"].pop(i)
    _write_doc(doc)
    return _holdings_view()


@api
def delete_symbol(symbol):
    doc = _doc()
    doc["lots"] = [l for l in doc["lots"] if l["symbol"] != symbol]
    (doc.get("assets") or {}).pop(symbol, None)
    _write_doc(doc)
    return _holdings_view()


@api
def set_account(payload):
    """payload: any of {cash_inr, lrs_remitted_this_fy_inr, realised_this_fy: {equity_stcg, equity_ltcg, other_stcg, other_ltcg}}"""
    p = _arg(payload)
    doc = _doc()
    if "cash_inr" in p:
        doc["cash_inr"] = max(0.0, float(p["cash_inr"]))
    if "lrs_remitted_this_fy_inr" in p:
        doc["lrs_remitted_this_fy_inr"] = max(0.0, float(p["lrs_remitted_this_fy_inr"]))
    if "realised_this_fy" in p:
        doc["realised_this_fy"] = {k: float((p["realised_this_fy"] or {}).get(k, 0) or 0) for k in EMPTY_REALISED}
    _write_doc(doc)
    return _holdings_view()


@api
def clear_holdings():
    """Start over: removes every lot (a .bak copy is kept), keeps the profile."""
    if HOLDINGS.exists():
        HOLDINGS.with_suffix(".yaml.bak").write_text(HOLDINGS.read_text())
        HOLDINGS.unlink()
    LAST.unlink(missing_ok=True)
    _main().STATE.unlink(missing_ok=True)
    return _status()


@api
def starters():
    return STARTERS


@api
def apply_starter(payload):
    """payload: {id, amount_inr, buy_date}. Replaces the holdings with amount-only lots; units are worked out at the first check."""
    p = _arg(payload)
    st = next((s for s in STARTERS if s["id"] == p.get("id")), None)
    if st is None:
        raise ApiError("invalid", "Unknown starting portfolio.")
    amount = float(p.get("amount_inr") or 0)
    if amount <= 0:
        raise ApiError("invalid", "Enter roughly how much the portfolio is worth.")
    d = date.fromisoformat(str(p.get("buy_date") or (date.today() - timedelta(days=400)))[:10])
    if d > date.today():
        raise ApiError("invalid", "The purchase date is in the future.")
    doc = {"lots": [{"symbol": s, "buy_date": str(d), "amount_inr": round(amount * w, 2)} for s, w in st["split"].items()],
           "cash_inr": round(amount * st["cash"], 2), "realised_this_fy": dict(EMPTY_REALISED), "lrs_remitted_this_fy_inr": 0}
    _write_doc(doc)
    LAST.unlink(missing_ok=True)
    return _status()


@api
def apply_trade(payload):
    """Record a trade you actually placed. payload: {symbol, side: buy|sell, qty, price (INR per unit), date?}.
    Sells remove the oldest lots first (FIFO) and add the gain to this year's realised totals; cash moves with the trade."""
    from .config import Lot
    from .tax import bucket_for, is_long_term
    p = _arg(payload)
    sym, side = str(p.get("symbol", "")).upper(), str(p.get("side", "")).lower()
    qty, price = float(p.get("qty") or 0), float(p.get("price") or 0)
    d = date.fromisoformat(str(p.get("date") or date.today())[:10])
    if side not in ("buy", "sell") or qty <= 0 or price <= 0:
        raise ApiError("invalid", "Enter the quantity and the price you got.")
    doc = _doc()
    if sym == "CASH":
        return _holdings_view()       # parking money in the cash sleeve changes nothing in the lots
    if any(l["symbol"] == sym and "qty" not in l for l in doc["lots"]):
        raise ApiError("invalid", f"{sym} still has an amount-only lot. Run a check first so its units are known.")
    if side == "buy":
        doc["lots"].append({"symbol": sym, "qty": round(qty, 6), "buy_date": str(d), "price": round(price, 4)})
        doc["cash_inr"] = max(0.0, float(doc.get("cash_inr") or 0) - qty * price)
    else:
        settings = _settings()
        register_assets(settings, load_holdings())
        tax_class = settings.assets[sym].tax_class if sym in settings.assets else "in_equity"
        own = sorted((l for l in doc["lots"] if l["symbol"] == sym), key=lambda l: str(l["buy_date"]))
        have = sum(float(l["qty"]) for l in own)
        if qty > have + 1e-6:
            raise ApiError("invalid", f"You hold {have:g} {sym}, which is less than {qty:g}.")
        left, realised = qty, doc.get("realised_this_fy") or dict(EMPTY_REALISED)
        for l in own:
            if left <= 1e-9:
                break
            take = min(float(l["qty"]), left)
            lot = Lot(sym, take, date.fromisoformat(str(l["buy_date"])[:10]), float(l["price"]))
            b = bucket_for(tax_class, is_long_term(lot, tax_class, d, settings))
            key = {"eq_st": "equity_stcg", "eq_lt": "equity_ltcg", "oth_lt": "other_ltcg"}.get(b, "other_stcg")
            realised[key] = round(float(realised.get(key, 0) or 0) + take * (price - float(l["price"])), 2)
            l["qty"] = round(float(l["qty"]) - take, 6)
            left -= take
        doc["lots"] = [l for l in doc["lots"] if "qty" not in l or float(l["qty"]) > 1e-9]
        doc["realised_this_fy"] = realised
        doc["cash_inr"] = float(doc.get("cash_inr") or 0) + qty * price
    _write_doc(doc)
    return _holdings_view()


# ---------------------------------------------------------------- search
@api
def search_symbols(q):
    """Known universe first, then an online lookup. [{symbol, name, where, currency, ticker}]"""
    q = str(q or "").strip()
    out, seen = [], set()
    if not q:
        return out
    s = load_settings()
    ql = q.lower()
    for sym, a in s.assets.items():
        if sym != "CASH" and (ql in sym.lower() or ql in a.name.lower()):
            out.append({"symbol": sym, "name": a.name, "where": "India" if a.currency == "INR" else "US / global", "currency": a.currency, "ticker": a.ticker})
            seen.add(sym)
    try:
        from . import yahoo_lite
        for r in yahoo_lite.search(q):
            t = r["ticker"]
            if t.endswith(".NS"):
                row = {"symbol": t[:-3], "name": r["name"], "where": "NSE", "currency": "INR", "ticker": t}
            elif t.endswith(".BO"):
                row = {"symbol": t[:-3], "name": r["name"], "where": "BSE", "currency": "INR", "ticker": t}
            elif "." not in t and "=" not in t and "^" not in t:
                row = {"symbol": t, "name": r["name"], "where": r["exchange"] or "US", "currency": "USD", "ticker": t}
            else:
                continue
            if row["symbol"] not in seen:
                seen.add(row["symbol"])
                out.append(row)
    except Exception:
        pass        # offline: the universe matches are still useful, and any NSE symbol can be typed as is
    return out[:20]


@api
def search_funds(q):
    from . import mf as M
    try:
        hits = M.search(str(q))[:20]
    except Exception as exc:
        raise ApiError("no_prices", f"Fund search needs the internet ({type(exc).__name__}).")
    return [{"code": str(h["schemeCode"]), "name": h["schemeName"], "regular": M.is_regular(h["schemeName"])} for h in hits]


# ---------------------------------------------------------------- imports
def _summarise(lots: list[dict], names: dict) -> list[dict]:
    by: dict[str, dict] = {}
    for l in lots:
        r = by.setdefault(l["symbol"], {"symbol": l["symbol"], "name": names.get(l["symbol"], l["symbol"]), "qty": 0.0, "cost": 0.0, "lots": 0,
                                        "first": str(l["buy_date"]), "last": str(l["buy_date"])})
        r["lots"] += 1
        if "qty" in l:
            r["qty"] += float(l["qty"])
            r["cost"] += float(l["qty"]) * float(l["price"])
        else:
            r["cost"] += float(l["amount_inr"])
        r["first"], r["last"] = min(r["first"], str(l["buy_date"])), max(r["last"], str(l["buy_date"]))
    return sorted(by.values(), key=lambda r: -r["cost"])


def _preview(kind: str, lots: list[dict], meta: dict, warns: list[str], replace: list[str] | None = None, doc: dict | None = None,
             profile_ticker: str = "") -> dict:
    names = _asset_names()
    names.update({s: m["name"] for s, m in (meta or {}).items() if m.get("name")})
    pend = {"kind": kind, "lots": lots, "meta": meta or {}, "replace_symbols": replace if replace is not None else sorted({l["symbol"] for l in lots}),
            "doc": doc, "profile_ticker": profile_ticker}
    _ensure_dirs()
    PENDING.write_text(json.dumps(pend, default=str))
    existing = {l["symbol"] for l in _doc()["lots"]}
    return {"kind": kind, "needs": [], "warnings": warns, "by_symbol": _summarise(lots, names), "lots": len(lots),
            "total_cost": sum(r["cost"] for r in _summarise(lots, names)),
            "replaces": sorted(existing & set(pend["replace_symbols"])), "replace_all": doc is not None}


def _needs(kind: str, needs: list[str], message: str) -> dict:
    return {"kind": kind, "needs": needs, "message": message, "warnings": [], "by_symbol": [], "lots": 0, "total_cost": 0, "replaces": [], "replace_all": False}


KIND_LABELS = {"tradebook": "Trade history", "snapshot": "Holdings list", "etrade": "E*TRADE stock plan", "cas": "Mutual fund statement (CAS)",
               "holdings_yaml": "Engine holdings file", "backup": "App backup", "text": "Typed lots",
               "locked": "Protected file"}


@api
def import_preview(payload):
    """Work out what the files are and what they would add. Nothing is saved until import_commit.
    payload: {paths: [..], kind?: auto, password?, ticker?, usd_inr?, approx_date?, sold_qty?, text?}
    If something is missing the result has needs: ["password" | "ticker" | "usd_inr" | "approx_date"] and a message."""
    import pandas as pd
    from . import anyimport as A
    p = _arg(payload)
    paths = [str(x) for x in (p.get("paths") or [])]
    approx = date.fromisoformat(str(p["approx_date"])[:10]) if p.get("approx_date") else None
    usd_inr = float(p["usd_inr"]) if p.get("usd_inr") else None
    if p.get("text"):
        lots, warns = A.parse_text(str(p["text"]), approx or date.today())
        if not lots:
            raise ApiError("empty", warns[0] if warns else "Nothing to import. Write one holding per line, for example: TCS 12 3900 2024-09-16")
        meta = {}
        for l in lots:
            if l.pop("currency", None) == "USD":
                meta[l["symbol"]] = {"currency": "USD"}
                if "qty" in l:
                    l["price"] = round(l["price"] * _fx_on(date.fromisoformat(l["buy_date"]), usd_inr), 4)
        return _preview("text", lots, meta, warns, replace=[])
    if not paths:
        raise ApiError("invalid", "Pick at least one file.")
    if any(A.is_locked_excel(x) for x in paths):
        ask = "This Excel file is password protected. Brokers usually use your PAN in capital letters. It is used once and not saved."
        if not p.get("password"):
            return _needs("locked", ["password"], ask)
        try:
            paths = [A.unlock_excel(x, str(p["password"]).strip()) if A.is_locked_excel(x) else x for x in paths]
        except ImportError:
            raise ApiError("unsupported", "Password-protected Excel files cannot be opened in this build. Open the file in a spreadsheet app, "
                                          "save a copy without the password, and import that.")
        except ValueError:
            return _needs("locked", ["password"], "That password did not open the file. " + ask)
    kinds = [p.get("kind") or A.detect(x) for x in paths]
    kind = kinds[0]
    if any(k != kind for k in kinds):
        raise ApiError("mixed", "These files are of different kinds (" + ", ".join(sorted({KIND_LABELS.get(k, k) for k in kinds}))
                       + "). Import one kind at a time.")
    if kind == "unknown":
        cols = []
        try:
            cols = [str(c) for c in A.read_table(paths[0]).columns][:12]
        except Exception:
            pass
        raise ApiError("unknown_file", "Could not tell what this file is. It needs columns for symbol and quantity, plus either "
                       "buy/sell with date and price (a trade history) or an average price (a holdings list)."
                       + (f" Columns found: {', '.join(cols)}." if cols else ""))
    if kind == "tradebook":
        frames, warns = [], []
        for x in paths:
            df, w = A.normalise_trades(A.read_table(x))
            frames.append(df)
            warns += w
        df = pd.concat(frames, ignore_index=True)
        if "trade_id" in df.columns and df["trade_id"].notna().all():
            df = df.drop_duplicates(subset=["trade_id"])
        else:
            df = df.drop_duplicates()
        if "currency" in df.columns and (df["currency"].astype(str).str.upper() == "USD").any() and "usd_inr" not in df.columns and not usd_inr:
            return _needs(kind, ["usd_inr"], "This file has trades in dollars. Enter the USD/INR rate to convert the cost.")
        from .importer import lots_from_tradebook
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as t:
            df.to_csv(t.name, index=False)
        try:
            lots, w = lots_from_tradebook(t.name, usd_inr)
        finally:
            os.unlink(t.name)
        warns += w
        if not lots:
            raise ApiError("empty", "No open holdings found in this trade history (everything bought was sold).")
        from .corporate_actions import resulting_asset_metadata
        rm = resulting_asset_metadata()
        meta = {l["symbol"]: dict(rm[l["symbol"]]) for l in lots if l["symbol"] in rm}
        for l in lots:
            if l.pop("currency", None) == "USD":
                meta.setdefault(l["symbol"], {})["currency"] = "USD"
        return _preview(kind, lots, meta, warns)
    if kind == "snapshot":
        if approx is None:
            return _needs(kind, ["approx_date"], "This is a holdings list without purchase dates. Roughly when did you buy most of it? "
                                                 "It only decides long-term versus short-term tax.")
        lots, warns = [], []
        for x in paths:
            try:
                l, w = A.lots_from_snapshot(A.read_table(x), approx, usd_inr)
            except ValueError as exc:
                if str(exc) == "need_usd_inr":
                    return _needs(kind, ["approx_date", "usd_inr"], "Some holdings are in dollars. Enter the USD/INR rate to convert the cost.")
                raise ApiError("unknown_file", str(exc))
            lots += l
            warns += w
        if not lots:
            raise ApiError("empty", "No holdings with a quantity and a cost were found in this file.")
        meta = {}
        for l in lots:
            if l.pop("currency", None) == "USD":
                meta[l["symbol"]] = {"currency": "USD"}
        return _preview(kind, lots, meta, warns)
    if kind == "etrade":
        from .etrade import lots_from_etrade
        from .profile import load_profile
        prof = load_profile()
        ticker = str(p.get("ticker") or (prof.employer_ticker if prof else "") or "").upper()
        if not ticker:
            return _needs(kind, ["ticker"], "This is an E*TRADE stock plan file. Which stock is it, for example MSFT?")
        if usd_inr:
            fx = lambda d: usd_inr
        else:
            try:
                from .etrade import fx_lookup
                fx = fx_lookup()
            except Exception:
                return _needs(kind, ["ticker", "usd_inr"], "Could not fetch USD/INR history. Enter one rate to use for every vest, or try again online.")
        try:
            lots, meta, warns = lots_from_etrade(paths[0], ticker, fx, float(p.get("sold_qty") or 0))
        except ValueError as exc:
            raise ApiError("unknown_file", str(exc).replace("Use the shell's manual entry instead.", "Add the vests by hand instead."))
        warns = [w.replace("add it with add-lot", "add it by hand").replace("with add-lot", "by hand") for w in warns]
        if not lots:
            raise ApiError("empty", "No delivered vests or purchases were found. Check it is the 'Download Expanded' Benefit History file.")
        return _preview(kind, lots, meta, warns, replace=[ticker], profile_ticker=ticker)
    if kind == "cas":
        if not p.get("password"):
            return _needs(kind, ["password"], "This is a mutual fund statement. Enter the password you set when you requested it. It is used once and not saved.")
        from . import mf as M
        try:
            cas = M.read_cas(paths[0], str(p["password"]))
        except ImportError:
            raise ApiError("unsupported", "Reading CAS PDFs is not available in this build. Add the funds by hand under Portfolio.")
        except Exception as exc:
            return _needs(kind, ["password"], f"Could not open the PDF ({type(exc).__name__}). Check the password and try again.")
        lots, meta, warns = M.lots_from_cas(cas)
        warns = [w.replace("with add-mf", "under Portfolio") for w in warns]
        if not lots:
            raise ApiError("empty", "No open mutual fund holdings were found in the statement.")
        return _preview(kind, lots, meta, warns, replace=sorted(meta))
    if kind == "holdings_yaml":
        try:
            doc = yaml.safe_load(Path(paths[0]).read_text()) or {}
            h = load_holdings(paths[0], apply_actions=False)
        except Exception as exc:
            raise ApiError("unknown_file", f"This YAML file is not an engine holdings file ({type(exc).__name__}: {exc}).")
        lots = [l for l in doc.get("lots", [])]
        if not lots and not h.cash_inr:
            raise ApiError("empty", "The holdings file has no lots.")
        return _preview(kind, lots, doc.get("assets") or {}, [], doc=doc)
    if kind == "backup":
        with zipfile.ZipFile(paths[0]) as z:
            names = [n for n in z.namelist() if Path(n).name in PERSONAL + ("app.json",)]
            if not names:
                raise ApiError("unknown_file", "This zip is not a backup made by the app.")
            doc = None
            for n in names:
                if Path(n).name == "holdings.yaml":
                    doc = yaml.safe_load(z.read(n)) or {}
        _ensure_dirs()
        keep = STATE / "restore.zip"
        shutil.copyfile(paths[0], keep)
        res = _preview(kind, (doc or {}).get("lots", []), (doc or {}).get("assets") or {}, ["Restoring replaces your holdings, profile, deposits and other assets with the backup's."],
                       doc=doc or {})
        res["restore_files"] = sorted(Path(n).name for n in names)
        return res
    raise ApiError("unknown_file", f"Cannot import a file of kind '{kind}'.")


@api
def import_commit(mode="replace_symbols"):
    """Save the last preview. mode: replace_symbols (default: re-importing a symbol does not double count) | append | replace_all"""
    from .profile import Profile, load_profile, merge_lots, save_profile
    if not PENDING.exists():
        raise ApiError("invalid", "Nothing to import. Pick the file again.")
    pend = json.loads(PENDING.read_text())
    kind = pend["kind"]
    if kind == "backup":
        keep = STATE / "restore.zip"
        with zipfile.ZipFile(keep) as z:
            for n in z.namelist():
                base = Path(n).name
                if base in PERSONAL:
                    (CONFIG / base).write_bytes(z.read(n))
                elif base == "app.json":
                    APP_STATE.write_bytes(z.read(n))
        keep.unlink(missing_ok=True)
    elif pend.get("doc") is not None or mode == "replace_all":
        doc = pend.get("doc") or {"lots": pend["lots"], "cash_inr": _doc().get("cash_inr", 0), "realised_this_fy": _doc().get("realised_this_fy"),
                                  "lrs_remitted_this_fy_inr": _doc().get("lrs_remitted_this_fy_inr", 0)}
        if pend.get("meta") and "assets" not in doc:
            doc["assets"] = pend["meta"]
        _write_doc({**_doc_defaults(), **doc})
    else:
        _ensure_dirs()
        merge_lots(pend["lots"], pend["meta"] or None, replace_symbols=set() if mode == "append" else set(pend["replace_symbols"]))
    if pend.get("profile_ticker"):
        prof = load_profile() or Profile()
        if prof.employer_ticker != pend["profile_ticker"]:
            prof.employer_ticker, prof.has_rsu, prof.employer_broker = pend["profile_ticker"], True, "etrade"
            save_profile(prof)
    PENDING.unlink(missing_ok=True)
    LAST.unlink(missing_ok=True)
    return _status()


def _doc_defaults() -> dict:
    return {"lots": [], "cash_inr": 0, "realised_this_fy": dict(EMPTY_REALISED), "lrs_remitted_this_fy_inr": 0}


@api
def export_backup(dest):
    """Zip of the personal files (holdings, profile, other assets, deposits, app settings). Returns the path."""
    dest = Path(str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name in PERSONAL:
            if (CONFIG / name).exists():
                z.write(CONFIG / name, f"config/{name}")
        if APP_STATE.exists():
            z.write(APP_STATE, "state/app.json")
    return str(dest)


# ---------------------------------------------------------------- profile, other assets, deposits
def _profile_view() -> dict:
    from .profile import INCOME_WHERE, INCOME_WHERE_ITEMS, RISK_LEVELS, Profile, emergency_months, load_profile, marginal_slab
    p = load_profile()
    cur = p or Profile()
    has_income = (cur.gross_salary_inr + cur.rsu_perquisite_inr + cur.other_income_inr) > 0
    months, why = emergency_months(cur)
    return {"exists": p is not None, "profile": dict(cur.__dict__), "equity_cap": cur.equity_cap(), "risk_levels": list(RISK_LEVELS),
            "tax_note": marginal_slab(cur)[2] if has_income else None, "emergency_months": months,
            "emergency_note": why.replace(" in the shell's profile command", "").replace("say yes to 'count backups'", "switch on 'Count my backups'"),
            "income_where": INCOME_WHERE, "income_where_items": [{"label": k, "lines": v} for k, v in INCOME_WHERE_ITEMS]}


@api
def profile():
    return _profile_view()


@api
def save_profile(payload):
    from .profile import RISK_LEVELS, Profile, load_profile, save_profile as _save
    p = _arg(payload)
    cur = load_profile() or Profile()
    for k, v in p.items():
        if k not in Profile.__dataclass_fields__ or v is None:
            continue
        default = Profile.__dataclass_fields__[k].default
        if isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, int):
            v = int(float(v))
        elif isinstance(default, float):
            v = max(0.0, float(v))
        else:
            v = str(v).strip()
        setattr(cur, k, v)
    cur.age = max(18, min(100, cur.age))
    cur.horizon_years = max(1, min(60, cur.horizon_years))
    if cur.risk not in RISK_LEVELS:
        cur.risk = "moderate"
    if cur.tax_regime not in ("new", "old"):
        cur.tax_regime = "new"
    cur.employer_ticker = cur.employer_ticker.upper()
    if cur.has_rsu and cur.employer_ticker and not cur.employer_broker:
        cur.employer_broker = "etrade"
    _ensure_dirs()
    _save(cur)
    return _profile_view()


_KIND_LABELS = {"epf": "EPF", "ppf": "PPF", "nps": "NPS", "sgb": "Sovereign Gold Bonds", "us_stock_other": "US stocks at another broker",
                "gold_physical": "Physical gold", "cash_savings": "Savings balance"}


def _others_view() -> dict:
    from .profile import KINDS, load_other
    return {"items": [{"index": i, **o.__dict__, "cls": o.asset_class, "liquid": o.liquid,
                       "kind_label": _KIND_LABELS.get(o.kind, o.kind.replace("_", " ").capitalize())} for i, o in enumerate(load_other())],
            "kinds": [{"id": k, "label": _KIND_LABELS.get(k, k.replace("_", " ").capitalize()), "cls": v[0],
                       "where": v[1].replace(" (run: python main.py gold-prices)", ""), "liquid": v[2]} for k, v in KINDS.items()]}


@api
def others():
    return _others_view()


@api
def save_other(payload):
    """payload: {index?: replace this one, kind, name, value_inr, note?}; {index, delete: true} removes."""
    from .profile import KINDS, OtherAsset, load_other, save_other as _save
    p = _arg(payload)
    items = load_other()
    idx = p.get("index")
    if p.get("delete"):
        if idx is not None and 0 <= int(idx) < len(items):
            items.pop(int(idx))
    else:
        kind = p.get("kind") if p.get("kind") in KINDS else "other"
        name = str(p.get("name") or kind.replace("_", " ")).strip()
        val = float(p.get("value_inr") or 0)
        if val < 0:
            raise ApiError("invalid", "The value cannot be negative.")
        item = OtherAsset(kind, name, val, str(p.get("note") or ""))
        if idx is not None and 0 <= int(idx) < len(items):
            items[int(idx)] = item
        else:
            items.append(item)
    _ensure_dirs()
    _save(items)
    return _others_view()


def _fds_view() -> dict:
    from . import fd as F
    s = _settings()
    try:
        from .profile import apply_tax_profile, load_profile
        apply_tax_profile(s, load_profile())
    except Exception:
        pass
    fds = F.load()
    rows = F.summary(fds, s.tax["slab_rate"], s.tax["cess"])
    for i, (f, r) in enumerate(zip(fds, rows)):
        r.update({"index": i, "bank_id": f.bank, "months": f.months, "payout": f.payout, "senior": f.senior})
    return {"items": rows, "banks": [{"id": k, "name": v["name"], "where": v["where"], "penalty_note": v["penalty_note"]} for k, v in F.BANKS.items()],
            "slab_rate": s.tax["slab_rate"]}


@api
def fds():
    return _fds_view()


@api
def save_fd(payload):
    """payload: {index?, bank, principal, rate (percent a year), start, months, payout?, label?, senior?}; {index, delete: true} removes."""
    from . import fd as F
    p = _arg(payload)
    items = F.load()
    idx = p.get("index")
    if p.get("delete"):
        if idx is not None and 0 <= int(idx) < len(items):
            items.pop(int(idx))
    else:
        bank = p.get("bank") if p.get("bank") in F.BANKS else "other"
        principal, rate, months = float(p.get("principal") or 0), float(p.get("rate") or 0), int(float(p.get("months") or 0))
        if principal <= 0 or not 0 < rate <= 20 or not 1 <= months <= 240:
            raise ApiError("invalid", "Enter the amount, a yearly rate in percent (for example 7.25) and the tenure in months.")
        start = date.fromisoformat(str(p.get("start") or date.today())[:10])
        payout = p.get("payout") if p.get("payout") in ("cumulative", "quarterly", "monthly") else "cumulative"
        label = str(p.get("label") or f"{F.BANKS[bank]['name']} {months}m").strip()
        item = F.FD(bank, principal, rate / 100.0, start, months, payout, label, None, bool(p.get("senior")))
        if idx is not None and 0 <= int(idx) < len(items):
            items[int(idx)] = item
        else:
            items.append(item)
    _ensure_dirs()
    F.save(items)
    return _fds_view()


# ---------------------------------------------------------------- settings
def _settings_view() -> dict:
    st = _app_state()
    try:
        s = _settings()
        policy, crash, execution = s.strategy["policy"], bool((s.strategy.get("crash") or {}).get("enabled")), s.timing.get("execution", "secretary")
        window = s.timing.get("window_days")
    except Exception:       # before init() has copied settings.yaml
        policy, crash, execution, window = st.get("policy", "core_xs"), bool(st.get("crash_enabled")), st.get("execution", "secretary"), None
    return {"policy": policy, "crash_enabled": crash, "execution": execution, "window_days": window, "policies": POLICIES}


@api
def settings():
    return _settings_view()


@api
def save_settings(payload):
    p = _arg(payload)
    st = _app_state()
    if p.get("policy") in {x["id"] for x in POLICIES}:
        st["policy"] = p["policy"]
    if "crash_enabled" in p:
        st["crash_enabled"] = bool(p["crash_enabled"])
    if p.get("execution") in ("secretary", "immediate"):
        st["execution"] = p["execution"]
    _save_app_state(st)
    LAST.unlink(missing_ok=True)
    return _settings_view()


# ---------------------------------------------------------------- reports as pages
_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e3e1da;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--mut:#a3a29c;--line:#33322f;--card:#1d1d1b}}
body{background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif;margin:0;padding:16px;overflow-wrap:anywhere}
h1{font-size:22px;line-height:1.25}h2{font-size:18px;margin-top:28px}h3{font-size:16px;margin-top:22px}
.tw{overflow-x:auto;margin:12px 0;border:1px solid var(--line);border-radius:12px;background:var(--card)}
table{border-collapse:collapse;font-size:14px;min-width:100%}th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:normal}td:first-child{min-width:9em}
th{color:var(--mut);font-weight:600;white-space:nowrap}tr:last-child td{border-bottom:0}code{font-size:.9em}li{margin:4px 0}
blockquote{margin:12px 0;padding:4px 14px;border-left:3px solid var(--line);color:var(--mut)}
</style></head><body>__BODY__</body></html>"""


def md_to_html(md: str) -> str:
    """The small Markdown subset the engine's reports use: headings, tables, lists, bold, code, quotes."""
    import html
    import re

    def inline(t: str) -> str:
        t = html.escape(t, quote=False)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<i>\1</i>", t)
        t = re.sub(r"(?<![_\w])_([^\n]+?)_(?![_\w])", r"<i>\1</i>", t)
        return re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', t)

    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|?\s*$", lines[i + 1]):
            cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            out.append('<div class="tw"><table><tr>' + "".join(f"<th>{inline(c)}</th>" for c in cells(ln)) + "</tr>")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(lines[i])) + "</tr>")
                i += 1
            out.append("</table></div>")
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
        elif re.match(r"^\s*([-*]|\d+\.)\s+", ln):
            tag = "ol" if re.match(r"^\s*\d+\.", ln) else "ul"
            out.append(f"<{tag}>")
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                out.append("<li>" + inline(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i])) + "</li>")
                i += 1
            out.append(f"</{tag}>")
            continue
        elif ln.startswith(">"):
            out.append(f"<blockquote>{inline(ln.lstrip('> '))}</blockquote>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    return "\n".join(out)


def _page(name: str, title: str, md: str) -> dict:
    import html
    _ensure_dirs()
    out = REPORTS / f"{name}.html"
    out.write_text(_PAGE.replace("__TITLE__", html.escape(title)).replace("__BODY__", md_to_html(md)))
    return {"path": str(out), "title": title}


REPORT_KINDS = [
    {"id": "asset_classes", "title": "Every asset class compared", "detail": "Equity, debt, small savings, REITs, property, farmland, gold and more, after costs and tax.", "online": False},
    {"id": "check", "title": "Today's check in full", "detail": "The long written version of today's plan with every reason.", "online": True},
    {"id": "crash", "title": "Crash guard and exit drill", "detail": "Early-warning signals and what a fast exit would cost today.", "online": True},
    {"id": "gold", "title": "Gold prices by city", "detail": "City rates compared with the landed import price.", "online": True},
    {"id": "silver", "title": "Silver prices by city", "detail": "City rates compared with the landed import price.", "online": True},
]


@api
def report_kinds():
    return REPORT_KINDS


@api
def report(kind, demo=False):
    """Build one written report as a small HTML page. Returns {path, title}."""
    kind = str(kind)
    if kind == "asset_classes":
        from . import assetclasses
        return _page(kind, "Every asset class compared", assetclasses.universe_report(assetclasses.universe()))
    if kind in ("gold", "silver"):
        from . import goldprice, realassets
        cfg = realassets.load()
        if kind == "silver":
            df, errors = goldprice.silver_snapshot(list(cfg["gold_prices"]["cities"]))
            return _page(kind, "Silver prices by city", goldprice.silver_report(df, errors, cfg["gold_prices"]["import_duty_pct"]))
        df, errors = goldprice.snapshot(cfg, None)
        return _page(kind, "Gold prices by city", goldprice.report(cfg, df, errors))
    if kind == "check":
        from .engine import make_plan
        from .report import live_report
        m, settings, prof, tax_note, h, px, vix, fx, note, usd, warns = _context(bool(demo), False)
        plan = make_plan(px.index[-1], h.lots, h.cash_inr, px, vix, settings, m._fy_realised(h, prof),
                         lrs_used=h.lrs_remitted_this_fy_inr, usd_inr=usd, guard_mem=dict(m.guard_mem_load()))
        return _page(kind, "Today's check in full", live_report(plan, settings, [], bool(demo), note, px))
    if kind == "crash":
        from . import crash
        m, settings, prof, tax_note, h, px, vix, fx, note, usd, warns = _context(bool(demo), False)
        a = crash.assess(px, vix, settings)
        md = [f"# Crash guard: level {a['level']} ({a['label']})", "", f"As of {px.index[-1].date()}, since {a['since']}.", ""]
        md += [f"- {w}" for w in a["why"]]
        md += ["", "## Signals", ""] + [f"- **{'ON' if f['points'] > 0 else 'off'}** {f['name']}: {f['detail']}" for f in a["families"]]
        for lvl in (2, 3):
            md += ["", f"## Drill: level {lvl} ({crash.LEVELS[lvl]})", ""]
            md += [l for l in crash.drill_text(crash.drill(h.lots, h.cash_inr, px, vix, settings, m._fy_realised(h, prof), usd, lvl)).splitlines()]
        return _page(kind, "Crash guard and exit drill", "\n".join(md))
    raise ApiError("invalid", f"Unknown report '{kind}'.")
