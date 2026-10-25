"""Small statistics helpers: how sure are we, and what could the next few years look like.

numpy only (no scipy), so CI stays light.
  xirr                 money-weighted annual return of dated cash flows
  bootstrap_excess     block-bootstrap interval for a strategy's annual excess return over a baseline
  deflated_sharpe      Bailey and Lopez de Prado: chance the Sharpe ratio is real after trying many variants
  monte_carlo          block-bootstrap of past daily returns into forward value and drawdown paths
"""
from __future__ import annotations

from datetime import date
from statistics import NormalDist

import numpy as np

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annualised internal rate of return for (date, amount) flows; money in negative, money out positive."""
    if len(flows) < 2 or not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    d0 = min(d for d, _ in flows)
    t = np.array([(d - d0).days / 365.0 for d, _ in flows])
    a = np.array([x for _, x in flows], dtype=float)

    def f(r):
        return float(np.sum(a / (1.0 + r) ** t))

    lo, hi = -0.99, 10.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if flo * fm <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def block_bootstrap(x: np.ndarray, n_boot: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Circular moving-block resamples of a 1-D series: n_boot rows, len(x) columns."""
    n = len(x)
    starts = rng.integers(0, n, size=(n_boot, int(np.ceil(n / block))))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return x[idx.reshape(n_boot, -1)[:, :n]]


def bootstrap_excess(strategy_nav: np.ndarray, base_nav: np.ndarray, n_boot: int = 2000, block: int = 63,
                     seed: int = 7) -> dict:
    """Annualised excess return (strategy minus baseline, from daily log returns) with a 90% bootstrap interval.

    Blocks of ~3 months keep volatility clustering and trend in each resample. `p_positive` is the share of
    resamples with positive excess, a rough chance the edge is more than luck of this one history.
    """
    r = np.diff(np.log(strategy_nav)) - np.diff(np.log(base_nav))
    r = r[np.isfinite(r)]
    if len(r) < 2 * block:
        return {"excess": None, "lo": None, "hi": None, "p_positive": None}
    rng = np.random.default_rng(seed)
    ann = block_bootstrap(r, n_boot, block, rng).mean(axis=1) * 252
    return {"excess": float(r.mean() * 252), "lo": float(np.percentile(ann, 5)), "hi": float(np.percentile(ann, 95)),
            "p_positive": float((ann > 0).mean())}


def _moments(r: np.ndarray) -> tuple[float, float, float]:
    sd = r.std(ddof=1)
    z = (r - r.mean()) / sd
    return float(r.mean() / sd), float((z ** 3).mean()), float((z ** 4).mean())


def deflated_sharpe(excess_returns: np.ndarray, trial_sharpes: list[float]) -> float | None:
    """Probability that the true Sharpe of a daily excess-return series is above what the best of
    len(trial_sharpes) tries would show by chance alone (Bailey and Lopez de Prado, 2014).

    `trial_sharpes` are the per-period Sharpe ratios of every variant tried. Near 1 is convincing,
    0.5 or below means indistinguishable from the luck of picking the best of many.
    """
    r = excess_returns[np.isfinite(excess_returns)]
    n = len(trial_sharpes)
    if len(r) < 30 or n < 2 or r.std(ddof=1) == 0:
        return None
    sr, skew, kurt = _moments(r)
    v = float(np.var(trial_sharpes, ddof=1))
    sr0 = np.sqrt(v) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n) + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n * np.e)))
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return None
    return float(_N.cdf((sr - sr0) * np.sqrt(len(r) - 1) / np.sqrt(denom)))


def monte_carlo(daily_returns: np.ndarray, start_value: float, years: float = 3.0, n_paths: int = 2000,
                block: int = 21, seed: int = 11) -> dict:
    """Resample past daily returns in blocks into forward paths. Pre-tax; past returns are a guide, not a forecast."""
    steps = int(round(years * 252))
    r = np.asarray(daily_returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2 * block:
        return {}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(steps / block))
    starts = rng.integers(0, len(r) - block + 1, size=(n_paths, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_paths, -1)[:, :steps]
    paths = start_value * np.cumprod(1 + r[idx], axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.full((n_paths, 1), start_value), paths], axis=1), axis=1)
    mdd = (np.concatenate([np.full((n_paths, 1), start_value), paths], axis=1) / peak - 1).min(axis=1)
    end = paths[:, -1]
    pct = lambda a, q: float(np.percentile(a, q))
    return {"years": years, "start": start_value,
            "end_p10": pct(end, 10), "end_p50": pct(end, 50), "end_p90": pct(end, 90),
            "prob_loss": float((end < start_value).mean()),
            "mdd_p50": pct(mdd, 50), "mdd_p10": pct(mdd, 10),
            "prob_dd_20": float((mdd < -0.20).mean()), "prob_dd_30": float((mdd < -0.30).mean())}
