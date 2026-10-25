"""Crash guard: early-warning signals for a bubble burst or crash, and a fast, tax-aware exit into a shelter.

Not about any one bubble. It watches what every large fall has in common and does not try to name the cause:

  damage     the market proxy is below its 200-day average and/or 10% (18%) below its 52-week high; these move together,
             so they count as one family, worth up to 2 points
  speed      it fell 5% in 5 days or 8% in 10 days
  stress     volatility jumped (own volatility vs its year, or India VIX spike)
  breadth    most of the risk universe is below its own 200-day average
  credit     high-yield bonds are losing to treasuries (needs HYG and IEF prices; skipped if absent)
  leaders    two of the three biggest 12-month winners have broken their 50-day average and fallen 10%+ (a bubble cracking)

Each family scores points, and the upper levels also need several families to agree, because a single price drop shows up
in damage and breadth at once and would otherwise stack into a false alarm. Extension ("froth": the market was unusually far above its trend in the last 4 months) lowers
the bar by one point, because the same signals mean more after a run-up. Points map to a level:

  0 calm       nothing changes
  1 watch      no new money into risk assets
  2 elevated   3+ points from 3+ families, at least one a stress signal (speed, volatility, credit): keep `keep[2]` of the risk assets, the rest to the shelter
  3 crisis     5+ points from 4+ families: keep `keep[3]`, no waiting for long-term tax status

Whipsaw defence: a level rises at once but falls one step only after `exit_days` consecutive days of lower readings. The level is replayed from the start of the price history
on every call, so live runs and backtests give the same answer with no stored state.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LEVELS = {0: "calm", 1: "watch", 2: "elevated", 3: "crisis"}
SAFE_SLEEVES = {"gold", "bonds", "cash"}
FAMILIES = [("damage", 2, "Price damage"), ("speed", 1, "Speed of fall"), ("stress", 1, "Volatility"),
            ("breadth", 1, "Breadth"), ("credit", 1, "Credit"), ("leaders", 1, "Leaders cracking")]


def cfg(settings) -> dict:
    return settings.strategy["crash"]


def _proxy(px: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    cols = [s for s in weights if s in px and px[s].notna().sum() > 260]
    if not cols:
        return pd.Series(dtype=float)
    w = pd.Series({s: weights[s] for s in cols})
    r = px[cols].pct_change(fill_method=None)
    ww = r.notna().mul(w, axis=1)
    ret = (r.fillna(0.0) * ww).sum(axis=1) / ww.sum(axis=1).replace(0, np.nan)
    return (1 + ret.fillna(0.0)).cumprod() * 100


def _risk_cols(px: pd.DataFrame, settings, sleeves) -> list[str]:
    return [s for s, a in settings.assets.items() if s in px and a.sleeve in sleeves and not a.equivalent_of and s != "CASH"]


def signal_frame(px: pd.DataFrame, vix: pd.Series | None, settings) -> pd.DataFrame:
    """Daily points per family, the score, the froth flag and the raw (pre-hysteresis) level. Every column is causal."""
    c = cfg(settings)
    comp = _proxy(px, c["proxy"])
    out = pd.DataFrame(index=px.index)
    if comp.empty:
        return out.assign(score=0.0, froth=False, raw=0, **{k: 0.0 for k, *_ in FAMILIES})
    r = comp.pct_change()
    sma200 = comp.rolling(200).mean()
    dd = comp / comp.rolling(252, min_periods=120).max() - 1
    out["damage"] = (comp < sma200).astype(float).add(((dd <= -c["dd_watch"]) | (dd <= -c["dd_deep"])).astype(float)).clip(upper=2.0) \
        .where(sma200.notna(), 0.0)
    out["speed"] = ((comp / comp.shift(5) - 1 <= -c["fast_5d"]) | (comp / comp.shift(10) - 1 <= -c["fast_10d"])).astype(float)
    vol20 = r.rolling(20).std() * np.sqrt(252)
    vol252 = r.rolling(252, min_periods=120).std() * np.sqrt(252)
    stress = (vol20 > c["vol_ratio"] * vol252) & (vol20 > c["vol_floor"])
    if vix is not None and vix.dropna().size:
        v = vix.reindex(px.index).ffill()
        stress = stress | ((v > c["vix_ratio"] * v.rolling(60, min_periods=30).mean()) & (v > c["vix_floor"]))
    out["stress"] = stress.astype(float)

    b = _risk_cols(px, settings, c["breadth_sleeves"])
    if len(b) >= 4:
        s200 = px[b].rolling(200).mean()
        valid = s200.notna()
        out["breadth"] = ((((px[b] < s200) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)) >= c["breadth_share"]).astype(float)
    else:
        out["breadth"] = 0.0
    if "HYG" in px and "IEF" in px and px["HYG"].notna().sum() > 150:
        ratio = px["HYG"] / px["IEF"]
        out["credit"] = (ratio < ratio.rolling(100).mean() * (1 - c["credit_gap"])).astype(float)
    else:
        out["credit"] = 0.0
    lead = _risk_cols(px, settings, c["leader_sleeves"])
    if len(lead) >= 5:
        ret252 = px[lead] / px[lead].shift(252) - 1
        top = ret252.rank(axis=1, ascending=False) <= 3
        broken = (px[lead] < px[lead].rolling(50).mean()) & (px[lead] / px[lead].rolling(252, min_periods=120).max() - 1 <= -c["leader_dd"])
        out["leaders"] = ((broken & top).sum(axis=1) >= 2).astype(float)
    else:
        out["leaders"] = 0.0

    stretch = comp / sma200 - 1
    q = stretch.rolling(750, min_periods=500).quantile(0.95)
    froth = ((stretch >= q) & (stretch > c["froth_min"])).astype(float).rolling(90, min_periods=1).max().astype(bool)
    out["froth"] = froth.reindex(px.index).fillna(False)
    out["score"] = out[[k for k, *_ in FAMILIES]].sum(axis=1)
    adj = out["froth"].astype(int)
    families = out[[k for k, *_ in FAMILIES]].gt(0).sum(axis=1)
    confirmed = out[["speed", "stress", "credit"]].gt(0).any(axis=1)      # a price drop alone is not enough: markets must also show stress
    raw = np.where((out["score"] >= c["crisis_at"] - adj) & (families >= c["crisis_families"]) & confirmed, 3,
                   np.where((out["score"] >= c["elevated_at"] - adj) & (families >= c["elevated_families"]) & confirmed, 2,
                            np.where(out["score"] >= c["watch_at"] - adj, 1, 0)))
    out["raw"] = raw
    return out


def levels(frame: pd.DataFrame, exit_days: int) -> pd.Series:
    """Hysteresis: up at once, down one step after `exit_days` consecutive lower readings."""
    raw = frame["raw"].to_numpy()
    out = np.zeros(len(raw), dtype=int)
    cur = calm = 0
    for i, x in enumerate(raw):
        if x > cur:
            cur, calm = int(x), 0
        elif x < cur:
            calm += 1
            if calm >= exit_days:
                cur, calm = cur - 1, 0
        else:
            calm = 0
        out[i] = cur
    return pd.Series(out, index=frame.index, name="level")


def level_series(px: pd.DataFrame, vix: pd.Series | None, settings) -> pd.DataFrame:
    f = signal_frame(px, vix, settings)
    f["level"] = levels(f, cfg(settings)["exit_days"])
    return f


def assess(px: pd.DataFrame, vix: pd.Series | None, settings, force_level: int | None = None) -> dict:
    """Where the guard stands as of the last row, with a plain-English line per signal."""
    c = cfg(settings)
    f = level_series(px, vix, settings)
    row = f.iloc[-1]
    level = int(row["level"]) if force_level is None else int(force_level)
    changed = f.index[f["level"].ne(f["level"].shift()).to_numpy()]
    since = changed[-1] if len(changed) else f.index[0]
    comp = _proxy(px, c["proxy"])
    fams = []
    for key, mx, name in FAMILIES:
        fams.append({"key": key, "name": name, "points": float(row[key]), "max": mx, "detail": _detail(key, px, vix, settings, comp, row)})
    why = [f"Crash guard level {level} ({LEVELS[level]}): {row['score']:.0f} of {sum(m for _, m, _ in FAMILIES)} warning points"
           f"{', with a recent run-up lowering the bar by one' if row['froth'] else ''}."]
    live = [fm["name"] for fm in fams if fm["points"] > 0]
    why.append("Signals on: " + (", ".join(live) if live else "none") + ".")
    if int(row["raw"]) != level and force_level is None:
        why.append(f"Today's raw reading is {LEVELS[int(row['raw'])]}, but the level only steps down after {c['exit_days']} straight days of lower readings (anti-whipsaw).")
    return {"level": level, "label": LEVELS[level], "raw_level": int(row["raw"]), "score": float(row["score"]), "froth": bool(row["froth"]),
            "since": str(since.date()), "days": int((f.index[-1] - since).days), "families": fams, "why": why, "forced": force_level is not None,
            "credit_available": "HYG" in px and "IEF" in px and px["HYG"].notna().sum() > 150,
            "keep": c["keep"], "history": {"dates": [str(d.date()) for d in f.index[-260:]], "level": [int(x) for x in f["level"].iloc[-260:]]}}


def _detail(key, px, vix, settings, comp, row) -> str:
    c = cfg(settings)
    if comp.empty:
        return "not enough history"
    last = comp.iloc[-1]
    if key == "damage":
        return (f"Market proxy is {last / comp.iloc[-200:].mean() - 1:+.1%} vs its 200-day average and {last / comp.iloc[-252:].max() - 1:+.1%} "
                f"from its 52-week high (flags below the average, and at -{c['dd_watch']:.0%}).")
    if key == "speed":
        return f"{last / comp.iloc[-6] - 1:+.1%} over 5 days, {last / comp.iloc[-11] - 1:+.1%} over 10 (flags at -{c['fast_5d']:.0%} / -{c['fast_10d']:.0%})."
    if key == "stress":
        r = comp.pct_change()
        v = f"; India VIX {float(vix.dropna().iloc[-1]):.1f}" if vix is not None and vix.dropna().size else ""
        return f"20-day volatility {r.iloc[-20:].std() * np.sqrt(252):.0%} vs {r.iloc[-252:].std() * np.sqrt(252):.0%} over a year{v}."
    if key == "breadth":
        b = _risk_cols(px, settings, c["breadth_sleeves"])
        if len(b) < 4:
            return "too few instruments with history."
        below = sum(px[s].iloc[-1] < px[s].iloc[-200:].mean() for s in b if px[s].iloc[-200:].notna().all())
        n = sum(px[s].iloc[-200:].notna().all() for s in b)
        return f"{below} of {n} equity instruments are below their 200-day average (flags at {c['breadth_share']:.0%})."
    if key == "credit":
        if "HYG" not in px or "IEF" not in px:
            return "needs HYG and IEF prices; not scored."
        ratio = px["HYG"] / px["IEF"]
        return f"High-yield vs treasuries is {ratio.iloc[-1] / ratio.iloc[-100:].mean() - 1:+.1%} vs its 100-day average (flags at -{c['credit_gap']:.0%})."
    if key == "leaders":
        lead = _risk_cols(px, settings, c["leader_sleeves"])
        if len(lead) < 5:
            return "too few instruments with history."
        r252 = (px[lead].iloc[-1] / px[lead].iloc[-253] - 1).dropna().sort_values(ascending=False).head(3)
        parts = []
        for s in r252.index:
            below50 = px[s].iloc[-1] < px[s].iloc[-50:].mean()
            ddn = px[s].iloc[-1] / px[s].iloc[-252:].max() - 1
            parts.append(f"{s} {r252[s]:+.0%} ({'broken' if below50 and ddn <= -c['leader_dd'] else 'intact'}, {ddn:+.0%} from high)")
        return "12-month leaders: " + ", ".join(parts) + "."
    return ""


def apply_guard(target, a: dict, px: pd.DataFrame, settings, held: dict[str, float], mem: dict | None = None):
    """Scale risk assets down per the level and move the excess to the shelter. Returns the (modified) target.

    `mem` remembers the pre-cut weights of a buy & hold book (which has no target of its own) so the all-clear can restore
    them; policies that compute a target every time (momentum, risk parity...) need no memory.
    """
    c = cfg(settings)
    level = a["level"]
    mem = {} if mem is None else mem
    target.guard = a
    if target.weights is None:
        base = mem.get("base") or dict(held)
        if level >= 2 and not mem.get("base"):
            mem["base"] = dict(held)
        if level == 0:
            if mem.pop("base", None):
                target.weights = dict(base)
                target.why.append("Crash guard is back to calm: restoring the weights you had before the exit.")
            return target
        w = dict(base)
    else:
        mem.pop("base", None)
        if level == 0:
            return target
        w = dict(target.weights)
    if not w:
        return target
    risk = [s for s in w if s in settings.assets and settings.assets[s].sleeve not in SAFE_SLEEVES]
    tot = sum(w.values())
    if tot < 1 - 1e-9:
        w["CASH"] = w.get("CASH", 0.0) + 1 - tot
    if level == 1:
        freed = 0.0
        for s in risk:
            cap = held.get(s, 0.0)
            if w[s] > cap + 1e-9:
                freed += w[s] - cap
                w[s] = cap
        if freed > 1e-9:
            w["CASH"] = w.get("CASH", 0.0) + freed
            target.why.append(f"Crash guard is on watch: no new money into risk assets ({freed:.0%} of the portfolio stays in the cash sleeve instead).")
            target.weights = w
        elif target.weights is None:
            target.weights = None
        return target
    keep = c["keep"][level]
    freed = 0.0
    for s in risk:
        freed += w[s] * (1 - keep)
        w[s] *= keep
    gold, gold_ok = c["shelter_gold"], False
    if gold in px and gold in settings.assets:
        g = px[gold].dropna()
        gold_ok = len(g) > 200 and g.iloc[-1] > g.iloc[-200:].mean()
    add_gold = 0.0
    if gold_ok:
        add_gold = min(freed * c["gold_share_of_shelter"], max(0.0, c["gold_max_weight"] - w.get(gold, 0.0)))
        w[gold] = w.get(gold, 0.0) + add_gold
    w["CASH"] = w.get("CASH", 0.0) + freed - add_gold
    target.weights = {k: v for k, v in w.items() if v > 1e-9}
    target.risk_off = True
    target.urgent = level >= 3
    target.risk_reason = f"crash guard {LEVELS[level]}: " + "; ".join(a["why"][1:2]).replace("Signals on: ", "").rstrip(".")
    target.why.insert(0, f"CRASH GUARD {LEVELS[level].upper()}. Keep {keep:.0%} of risk assets, move {freed:.0%} of the portfolio to the shelter "
                         f"({'cash' if not add_gold else f'cash {freed - add_gold:.0%} + gold {add_gold:.0%}, since gold is above its 200-day average'}). "
                         + " ".join(a["why"][:2]))
    return target


def drill(lots, cash_inr: float, px: pd.DataFrame, vix, settings, fy_realised: dict | None = None, usd_inr: float | None = None,
          level: int = 3) -> dict:
    """What would a crash exit cost if the guard hit `level` today? Same planner and tax lots, level forced, nothing stored.
    Uses buy & hold as the base so only the guard's own cut shows, not the strategy's usual rotation."""
    from .engine import make_plan
    plan = make_plan(px.index[-1], lots, cash_inr, px, vix, settings, fy_realised, "buy_hold", False,
                     usd_inr=usd_inr, guard_level=level, guard_mem={})
    sells = [t for t in plan.trades if t.side == "sell" and not t.kind.startswith("harvest")]
    sold = sum(t.value for t in sells)
    tax = max(0.0, plan.tax_after - plan.tax_before)
    cost = sum(t.cost for t in plan.trades if not t.kind.startswith("harvest"))
    rows = [{"symbol": t.symbol, "value": round(t.value), "tax": round(t.tax_now), "cost": round(t.cost),
             "lots": [{"buy_date": str(l.buy_date), "qty": round(q, 4)} for l, q in t.lots]} for t in sells]
    friction = (tax + cost) / plan.nav if plan.nav else 0.0
    # The exit pays if the market falls further than the friction plus the cost of getting back in (about the same costs again, no more tax).
    breakeven = (tax + 2 * cost) / sold if sold else 0.0
    return {"level": level, "nav": round(plan.nav), "sold": round(sold), "tax": round(tax), "cost": round(cost), "friction_pct": friction,
            "breakeven_fall": breakeven, "sells": rows, "waits": plan.deferred, "blocked": plan.blocked,
            "to_shelter": {t.symbol: round(t.value) for t in plan.trades if t.side == "buy" and not t.kind.startswith("harvest")}}


def drill_text(d: dict) -> str:
    if not d["sells"]:
        return "Nothing would be sold at this level: you hold no risk assets above the level's cap."
    L = [f"If the guard hit {LEVELS[d['level']]} today you would sell about Rs {d['sold']:,.0f} of Rs {d['nav']:,.0f} "
         f"({d['sold'] / max(d['nav'], 1):.0%}), paying about Rs {d['tax']:,.0f} tax and Rs {d['cost']:,.0f} costs ({d['friction_pct']:.2%} of the portfolio).",
         f"That exit pays for itself if the market then falls roughly another {d['breakeven_fall']:.1%} (tax, costs, and costs again to get back in)."]
    L += [f"  sell {r['symbol']} Rs {r['value']:,.0f}  (tax Rs {r['tax']:,.0f}, costs Rs {r['cost']:,.0f})" for r in d["sells"]]
    if d["to_shelter"]:
        L.append("  into: " + ", ".join(f"{k} Rs {v:,.0f}" for k, v in d["to_shelter"].items()))
    L += [f"  note: {w}" for w in d["waits"][:3]]
    return "\n".join(L)


def guard_markdown(a: dict, drills: list[dict]) -> str:
    L = ["## Crash guard", "",
         f"**Level {a['level']}: {a['label']}** (since {a['since']}, {a['score']:.0f} warning points"
         f"{', run-up lowers the bar' if a['froth'] else ''}). Keeps {'everything as the strategy says' if a['level'] < 2 else f'{a['keep'][a['level']]:.0%} of risk assets, the rest in the shelter'}.", ""]
    L += [f"- {'**ON** ' if f['points'] > 0 else 'off '} {f['name']}: {f['detail']}" for f in a["families"]]
    if not a["credit_available"]:
        L.append("- _Credit signal skipped: no HYG/IEF prices._")
    if a["level"] < 2:
        L.append("")
        L += [f"> {drill_text(d)}" for d in drills[-1:]]
    L.append("")
    return "\n".join(L)
