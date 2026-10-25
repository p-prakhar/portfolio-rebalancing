"""Automatic strategy switcher: a meta-policy that decides which strategy (or mix) to follow, tested walk-forward.

Input is the daily value curve of each strategy as followed by the daily simulation (each curve already has its own
trading costs and Indian tax inside it). The meta-policy holds one sleeve per strategy. Moving money from one sleeve
to another means selling part of it, so every move pays costs and capital-gains tax on that sleeve's gain, using the
rules in settings.yaml (20% short term, 12.5% long term above the yearly exemption, plus cess). Losses are not
refunded, which is slightly pessimistic. Decisions at day t use curves up to day t-1 only.

Policies (parameters fixed in advance, none tuned on the history reported):
  equal_weight     all strategies, equal money, rebalanced when a sleeve drifts more than the band
  inverse_vol      weights proportional to 1 / 12-month volatility of each strategy
  momentum_switch  100% in the strategy with the best 12-month return; change only if a challenger leads by 3 points
  hedge            multiplicative weights (Hedge / exponentiated gradient) on monthly outperformance of each strategy
                   against the equal-weight average, capped at 40% per strategy

Sources of the methods are in docs/SWITCHER.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Settings
from .stats import bootstrap_excess, deflated_sharpe

LOOKBACK = 252            # trading days of history a signal needs
MARGIN = 0.03             # momentum_switch: challenger must lead the incumbent by this much (12-month return)
HEDGE_ETA = 20.0          # hedge: 1 point of monthly outperformance moves log-weight by 0.2
HEDGE_CAP = 0.40
BAND = 0.10               # do not trade a sleeve unless it is this far (absolute weight) from target
SIDE_COST = 0.001         # one-way trading cost of moving money between sleeves


def _tax(st: float, lt: float, s: Settings) -> float:
    t = s.tax
    return (max(st, 0) * t["equity_stcg_rate"] + max(lt - t["ltcg_exemption"], 0) * t["equity_ltcg_rate"]) * (1 + t["cess"])


@dataclass
class Sleeves:
    value: np.ndarray
    basis: np.ndarray
    age: np.ndarray                              # value-weighted days since the money entered the sleeve
    st: float = 0.0                              # gains realised this financial year
    lt: float = 0.0
    tax_paid: float = 0.0
    cost_paid: float = 0.0
    moves: int = 0
    log: list = field(default_factory=list)


def _sell(sl: Sleeves, k: int, amount: float, s: Settings) -> float:
    """Sell `amount` from sleeve k; returns tax due now (marginal, given gains already realised this year)."""
    v = sl.value[k]
    if amount <= 0 or v <= 0:
        return 0.0
    f = min(amount / v, 1.0)
    gain = f * (v - sl.basis[k])
    before = _tax(sl.st, sl.lt, s)
    if sl.age[k] > 365:
        sl.lt += gain
    else:
        sl.st += gain
    sl.value[k] -= f * v
    sl.basis[k] *= 1 - f
    return _tax(sl.st, sl.lt, s) - before


def _rebalance(sl: Sleeves, target: np.ndarray, s: Settings, day: pd.Timestamp, side_cost: float) -> None:
    total = sl.value.sum()
    cur = sl.value / total
    if np.abs(cur - target).max() <= BAND:
        return
    want = target * total
    sells = np.maximum(sl.value - want, 0)
    if sells.sum() < 0.01 * total:
        return
    tax = sum(_sell(sl, k, sells[k], s) for k in range(len(sells)) if sells[k] > 0)
    cost = side_cost * 2 * sells.sum()
    sl.tax_paid += tax
    sl.cost_paid += cost
    pot = sells.sum() - tax - cost
    buy_need = np.maximum(want - sl.value, 0)
    if buy_need.sum() <= 0:
        return
    buy = buy_need / buy_need.sum() * pot
    sl.age = np.where(buy > 0, (sl.age * sl.value) / np.maximum(sl.value + buy, 1e-9), sl.age)
    sl.value = sl.value + buy
    sl.basis = sl.basis + buy
    sl.moves += 1
    sl.log.append((str(day.date()), {int(k): round(float(target[k]), 3) for k in np.nonzero(target > 0.001)[0]}))


def _w_equal(hist, n, state): return np.full(n, 1 / n)


def _w_invvol(hist, n, state):
    vol = hist.pct_change().iloc[-LOOKBACK:].std().replace(0, np.nan)
    w = (1 / vol).fillna(0).to_numpy()
    return w / w.sum() if w.sum() > 0 else np.full(n, 1 / n)


def _w_momentum(hist, n, state):
    r = (hist.iloc[-1] / hist.iloc[-LOOKBACK - 1] - 1).to_numpy()
    cur = state.get("incumbent")
    best = int(np.nanargmax(r))
    if cur is None or r[best] > r[cur] + MARGIN:
        cur = best
    state["incumbent"] = cur
    w = np.zeros(n)
    w[cur] = 1.0
    return w


def _w_hedge(hist, n, state):
    month = hist.iloc[-1] / hist.iloc[state["last_i"]] - 1 if "last_i" in state else None
    state["last_i"] = len(hist) - 1
    lw = state.setdefault("logw", np.zeros(n))
    if month is not None:
        m = month.to_numpy()
        lw += HEDGE_ETA * (m - m.mean())
    w = np.exp(lw - lw.max())
    w /= w.sum()
    for _ in range(10):                               # cap by clipping and redistributing
        over = w > HEDGE_CAP
        if not over.any():
            break
        excess = (w[over] - HEDGE_CAP).sum()
        w[over] = HEDGE_CAP
        w[~over] += excess * w[~over] / w[~over].sum()
    return w


POLICIES = {"equal_weight": _w_equal, "inverse_vol": _w_invvol, "momentum_switch": _w_momentum, "hedge": _w_hedge}


def run(navs: pd.DataFrame, policy: str, s: Settings, start: pd.Timestamp, end: pd.Timestamp, lump: float = 1_000_000,
        side_cost: float = SIDE_COST) -> dict:
    """Follow `policy` from `start` to `end`. `policy` is a POLICIES key or the name of one column (fixed strategy)."""
    n = navs.shape[1]
    px = navs.loc[:end]
    idx = px.index[px.index >= start]
    rets = px.pct_change().fillna(0).to_numpy()
    pos0 = px.index.get_loc(idx[0])
    fixed = policy in navs.columns
    state: dict = {}
    w0 = np.eye(n)[list(navs.columns).index(policy)] if fixed else None
    sl = None
    month_of = px.index.to_period("M")
    out = []
    for i in range(pos0, px.shape[0]):
        ts = px.index[i]
        if sl is not None:
            sl.value = sl.value * (1 + rets[i])
            sl.age = sl.age + (ts - px.index[i - 1]).days
        first_of_month = i == pos0 or month_of[i] != month_of[i - 1]
        if sl is None:                                    # day one: buy the starting mix, no tax on a fresh purchase
            w = w0 if fixed else POLICIES[policy](px.iloc[:i], n, state) if i > LOOKBACK else np.full(n, 1 / n)
            sl = Sleeves(w * lump, w * lump, np.zeros(n))
            sl.cost_paid += side_cost * lump if not fixed else 0.0
            sl.value = sl.value - (side_cost * lump if not fixed else 0.0) * w
        elif not fixed and first_of_month and i > LOOKBACK:
            _rebalance(sl, POLICIES[policy](px.iloc[:i], n, state), s, ts, side_cost)
        out.append(sl.value.sum())
        # financial-year rollover: exemption resets
        if i + 1 < px.shape[0] and px.index[i + 1].month == 4 and ts.month == 3:
            sl.st = sl.lt = 0.0
    nav = pd.Series(out, index=idx)
    tmp = Sleeves(sl.value.copy(), sl.basis.copy(), sl.age.copy(), sl.st, sl.lt)
    liq = sum(_sell(tmp, k, tmp.value[k], s) for k in range(n))
    yrs = (idx[-1] - idx[0]).days / 365.25
    after = (nav.iloc[-1] - liq) / lump
    return {"nav": nav, "cagr": after ** (1 / yrs) - 1 if after > 0 else float("nan"), "after_tax_value": float(nav.iloc[-1] - liq),
            "max_drawdown": float((nav / nav.cummax() - 1).min()), "tax_paid": sl.tax_paid + liq, "costs": sl.cost_paid,
            "moves": sl.moves, "years": yrs, "log": sl.log, "weights_names": list(navs.columns)}


def load_navs(path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df.dropna(how="any").sort_index()


def evaluate(navs: pd.DataFrame, s: Settings, lump: float = 1_000_000, window_years: int = 3, step_months: int = 6,
             baseline: str = "equal_weight") -> dict:
    """Walk-forward comparison of every meta-policy against the fixed strategies and the equal-weight blend."""
    start = navs.index[LOOKBACK + 1]
    end = navs.index[-1]
    names = list(navs.columns)
    runs = {p: run(navs, p, s, start, end, lump) for p in list(POLICIES) + names}
    base = runs[baseline]["nav"]
    hold = next((c for c in names if "hold" in c.lower()), None)

    def excess_daily(nav): return np.diff(np.log(nav.to_numpy())) - np.diff(np.log(base.to_numpy()))
    trial_sr = [float(excess_daily(r["nav"]).mean() / (excess_daily(r["nav"]).std(ddof=1) or np.nan)) for k, r in runs.items() if k != baseline]
    table = {}
    for k, r in runs.items():
        bs = bootstrap_excess(r["nav"].to_numpy(), base.to_numpy()) if k != baseline else {}
        table[k] = {"kind": "meta" if k in POLICIES else "fixed", "cagr_after_tax": r["cagr"], "max_drawdown": r["max_drawdown"],
                    "tax_paid": r["tax_paid"], "costs": r["costs"], "moves": r["moves"],
                    "excess_vs_blend": bs.get("excess"), "ci_lo": bs.get("lo"), "ci_hi": bs.get("hi"), "p_positive": bs.get("p_positive"),
                    "deflated_sharpe": deflated_sharpe(excess_daily(r["nav"]), [x for x in trial_sr if np.isfinite(x)]) if k != baseline else None}
    # rolling windows: does each meta-policy beat the equal-weight blend window after window?
    wins, t = [], start
    while t + pd.DateOffset(years=window_years) <= end + pd.Timedelta(days=5):
        wins.append((t, min(t + pd.DateOffset(years=window_years), end)))
        t += pd.DateOffset(months=step_months)
    roll = {p: [] for p in POLICIES if p != baseline}
    if hold:
        roll["blend_vs_hold"] = []
    for a, b in wins:
        ra = {p: run(navs, p, s, a, b, lump) for p in list(POLICIES)}
        for p in roll:
            if p == "blend_vs_hold":
                roll[p].append(ra["equal_weight"]["cagr"] - run(navs, hold, s, a, b, lump)["cagr"])
            else:
                roll[p].append(ra[p]["cagr"] - ra[baseline]["cagr"])
    summary = {p: {"windows": len(v), "win_rate": float(np.mean(np.array(v) > 0)), "median": float(np.median(v)), "worst": float(np.min(v))}
               for p, v in roll.items() if v}
    verdict = {}
    for p in POLICIES:
        if p == baseline:
            continue
        row, w = table[p], summary.get(p, {})
        convincing = (row["ci_lo"] or -1) > 0 and (row["deflated_sharpe"] or 0) > 0.95 and w.get("win_rate", 0) >= 0.6 and w.get("worst", -1) > -0.05
        verdict[p] = "switch: edge survives the checks" if convincing else "no reliable edge over the equal-weight blend"
    return {"start": str(start.date()), "end": str(end.date()), "years": round((end - start).days / 365.25, 2), "strategies": names,
            "table": table, "rolling": summary, "verdict": verdict, "trials": len(trial_sr), "window_years": window_years,
            "best_fixed_hindsight": max(names, key=lambda n: table[n]["cagr_after_tax"])}


def report(res: dict) -> str:
    pc = lambda x: "-" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:+.1%}"
    L = ["# Automatic strategy switcher, tested walk-forward", "",
         f"{res['start']} to {res['end']} ({res['years']} years). Each rule sees only the past, pays trading costs and Indian capital-gains tax "
         "every time it moves money between strategies, and is compared with simply splitting money equally across all strategies. "
         f"{res['trials']} variants were tried in total, which the deflated-Sharpe column accounts for.", "",
         "| rule | per year after tax | worst fall | moves | tax paid | costs | gap vs equal blend | 90% range | deflated Sharpe | verdict |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    order = sorted(res["table"], key=lambda k: (res["table"][k]["kind"] != "meta", -res["table"][k]["cagr_after_tax"]))
    for k in order:
        r = res["table"][k]
        rng = "-" if r["ci_lo"] is None else f"{pc(r['ci_lo'])} to {pc(r['ci_hi'])}"
        ds = "-" if r["deflated_sharpe"] is None else f"{r['deflated_sharpe']:.2f}"
        v = res["verdict"].get(k, "baseline" if k == "equal_weight" else "fixed strategy" if r["kind"] == "fixed" else "")
        L.append(f"| {k} | {r['cagr_after_tax']:.1%} | {r['max_drawdown']:.1%} | {r['moves']} | {r['tax_paid']:,.0f} | {r['costs']:,.0f} | "
                 f"{pc(r['excess_vs_blend'])} | {rng} | {ds} | {v} |")
    L += ["", f"## Rolling {res['window_years']}-year windows against the equal blend", "",
          "| rule | windows | beat the blend | median gap | worst gap |", "|---|---|---|---|---|"]
    for p, w in res["rolling"].items():
        L.append(f"| {p} | {w['windows']} | {w['win_rate']:.0%} | {pc(w['median'])} | {pc(w['worst'])} |")
    L += ["", f"Best single strategy in hindsight: {res['best_fixed_hindsight']} (not knowable in advance, so not a fair target).", "",
          "_Windows overlap, so they are not independent. 'switch' needs the 90% range above zero, deflated Sharpe above 0.95, a win in 60% of windows "
          "and no window worse than -5 points a year._"]
    return "\n".join(L)
