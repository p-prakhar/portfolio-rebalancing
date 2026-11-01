"""Current fixed-deposit rates across banks, fetched from each bank's public rate page.

Order of trust: live page -> last good fetch (cache, with its age) -> the manual card in config/fd_rates.yaml.
A fetch that fails, or parses to something implausible, never breaks the engine; it falls through and says so.
Rate pages change layout, so the parser is deliberately generic (a table row = tenure cell followed by rate cells)
and every number is range-checked. Edit `sources` or the manual `cards` in the yaml when a bank changes its page.

Rates are the bank's card rates for a fresh deposit below Rs 3 crore. A negotiated or old deposit differs.
Small finance banks pay more but carry more risk: DICGC insures only Rs 5 lakh per depositor per bank
(principal plus interest together), so keep each SFB deposit well under that.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

import yaml

from .config import ROOT

CFG = ROOT / "config" / "fd_rates.yaml"
CACHE = ROOT / "data" / "cache" / "fd_rates.json"
UA = {"User-Agent": "Mozilla/5.0 (portfolio-engine fd rate checker)"}
MIN_RATE, MAX_RATE = 0.02, 0.12
STALE_DAYS = 14
_UNIT = {"day": 1, "week": 7, "month": 30.4167, "year": 365}
_TEN = re.compile(r"(\d+(?:\.\d+)?)\s*(day|week|month|year)s?", re.I)


def load_config() -> dict:
    return yaml.safe_load(CFG.read_text()) or {}


def _days(m) -> float:
    return float(m.group(1)) * _UNIT[m.group(2).lower()]


def parse_tenure(cell: str) -> tuple[float, float] | None:
    """'1 year to less than 2 years' -> (365, 729); '7 days to 45 days' -> (7, 45); 'Above 5 years' -> (1827, inf)."""
    c = cell.strip()
    ms = list(_TEN.finditer(c))
    if not ms or len(c) > 80 or "%" in c:
        return None
    lo_words = re.search(r"\b(above|more than|over|greater than)\b", c, re.I)
    if len(ms) == 1:
        d = _days(ms[0])
        return (d, float("inf")) if lo_words else (d, d)
    lo, hi = _days(ms[0]), _days(ms[-1])
    if re.search(r"less than|<|below|under", c, re.I) and "up to" not in c.lower():
        hi -= 1
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def _pct(cell: str) -> float | None:
    m = re.fullmatch(r"\s*(\d{1,2}(?:\.\d{1,3})?)\s*%?\s*(?:p\.?a\.?)?\s*", cell, re.I)
    if not m:
        return None
    v = float(m.group(1)) / 100
    return v if MIN_RATE <= v <= MAX_RATE else None


def parse_rates(html: str) -> list[dict]:
    """Rows of {lo, hi, general, senior} (annual rates as fractions, tenure bounds in days) from any rate page."""
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    t = re.sub(r"(?i)<br\s*/?>|</t[dh]>|</li>|</p>|</div>|</tr>", "|", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&#37;", "%")
    cells = [re.sub(r"\s+", " ", c).strip() for c in t.split("|")]
    cells = [c for c in cells if c]
    rows, i = [], 0
    while i < len(cells):
        ten = parse_tenure(cells[i])
        if ten:
            rates = []
            j = i + 1
            while j < len(cells) and len(rates) < 2 and _pct(cells[j]) is not None:
                rates.append(_pct(cells[j]))
                j += 1
            if rates:
                rows.append({"lo": ten[0], "hi": ten[1], "general": rates[0], "senior": rates[1] if len(rates) > 1 else rates[0]})
                i = j
                continue
        i += 1
    return _main_table(rows)


def _main_table(rows: list[dict]) -> list[dict]:
    """Pages often carry several tables (special, bulk or limited-offer cards besides the regular one). Tenures rise
    down a table and restart at the next, so split there and keep the first table that is nearly as long as the longest
    (the regular card comes before bulk-deposit cards, and a short or mangled fragment must not win)."""
    runs, cur = [], []
    for r in rows:
        if cur and r["lo"] < cur[-1]["lo"]:
            runs.append(cur)
            cur = []
        cur.append(r)
    if cur:
        runs.append(cur)
    top = max((len(r) for r in runs), default=0)
    return next((r for r in runs if len(r) >= 0.8 * top), [])


def _sane(rows: list[dict]) -> bool:
    """A real card has several slabs and rates that do not jump around wildly between neighbours."""
    if len(rows) < 3:
        return False
    g = [r["general"] for r in rows]
    return max(g) - min(g) <= 0.05


def fetch_bank(src: dict) -> list[dict]:
    import requests
    r = requests.get(src["url"], headers=UA, timeout=25)
    r.raise_for_status()
    rows = parse_rates(r.text)
    if not _sane(rows):
        raise ValueError(f"page parsed to {len(rows)} rate rows that did not look like a rate card")
    return rows


def _read_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def _write_cache(d: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(d, indent=1))
    except OSError:
        pass


def _manual(card: dict) -> list[dict]:
    return [{"lo": c[0], "hi": c[1], "general": c[2] / 100, "senior": (c[3] if len(c) > 3 else c[2] + 0.5) / 100}
            for c in card.get("slabs", [])]


def current(refresh: bool = True, today: date | None = None) -> dict:
    """{bank_key: {name, kind, rows, origin: live|cache|manual, as_of, note}} for every bank in the config."""
    today = today or date.today()
    cfg = load_config()
    cache = _read_cache()
    out, dirty = {}, False
    for key, b in (cfg.get("banks") or {}).items():
        entry = {"key": key, "name": b["name"], "kind": b.get("kind", "large"), "dicgc": b.get("kind") == "sfb"}
        rows, origin, as_of, note = None, None, None, ""
        if refresh and b.get("url"):
            try:
                rows = fetch_bank(b)
                origin, as_of = "live", str(today)
                cache[key] = {"as_of": as_of, "rows": rows}
                dirty = True
            except Exception as e:           # network, layout change, implausible numbers: fall through
                note = f"live fetch failed ({type(e).__name__}: {str(e)[:80]})"
        if rows is None and key in cache:
            rows, origin, as_of = cache[key]["rows"], "cache", cache[key]["as_of"]
            age = (today - date.fromisoformat(as_of)).days
            note = (note + "; " if note else "") + f"last good fetch {age} days ago" + (" (stale)" if age > STALE_DAYS else "")
        if rows is None:
            rows, origin, as_of = _manual(b), "manual", str(b.get("as_of", ""))
            note = (note + "; " if note else "") + "using the manual card in config/fd_rates.yaml; check the bank's site"
        entry.update(rows=rows, origin=origin, as_of=as_of, note=note)
        out[key] = entry
    if dirty:
        _write_cache(cache)
    return out


def rate_for(rows: list[dict], months: float, senior: bool = False) -> float | None:
    d = months * 365 / 12
    hit = [r for r in rows if r["lo"] <= d <= r["hi"]]
    if not hit:
        hit = [r for r in rows if r["lo"] <= d]
        hit = hit[-1:] if hit else []
    return (hit[0]["senior"] if senior else hit[0]["general"]) if hit else None


def ranking(banks: dict, months: float = 12, senior: bool = False) -> list[dict]:
    res = []
    for b in banks.values():
        r = rate_for(b["rows"], months, senior)
        if r is not None:
            res.append({"bank": b["name"], "kind": b["kind"], "rate": r, "origin": b["origin"], "as_of": b["as_of"], "dicgc": b["dicgc"]})
    return sorted(res, key=lambda x: -x["rate"])


def class_yields(banks: dict, months: float = 12) -> dict:
    """Replacements for the generic FD classes from fetched data only (live or cache; the rough manual card never
    overrides the class defaults): large banks = their average, SFB = the best SFB rate."""
    real = {k: b for k, b in banks.items() if b["origin"] != "manual"}
    big = [rate_for(b["rows"], months) for b in real.values() if b["kind"] == "large"]
    sfb = [rate_for(b["rows"], months) for b in real.values() if b["kind"] == "sfb"]
    big, sfb = [x for x in big if x], [x for x in sfb if x]
    out = {}
    if big:
        out["bank_fd"] = sum(big) / len(big)
    if sfb:
        out["sfb_fd"] = max(sfb)
    return out


def apply_to_classes(spec: dict, months: float = 12, refresh: bool = False) -> dict:
    """Overwrite income_yield of bank_fd and sfb_fd in a loaded asset_classes spec. Safe to call offline."""
    try:
        ys = class_yields(current(refresh=refresh), months)
    except Exception:
        return {}
    for c in spec.get("classes", spec if isinstance(spec, list) else []):
        if isinstance(c, dict) and c.get("key") in ys:
            c["income_yield"] = round(ys[c["key"]], 4)
    return ys


def card_rate_for_period(bank_key: str, held_days: float, banks: dict | None = None) -> float | None:
    """The bank's card rate for the time a deposit was actually held (used for the early-break payout)."""
    banks = banks or current(refresh=False)
    b = banks.get(bank_key)
    return rate_for(b["rows"], held_days * 12 / 365) if b else None


def render(banks: dict, months: float = 12, senior: bool = False) -> str:
    L = [f"FD card rates for a {months:g}-month deposit ({'senior citizen' if senior else 'general'}):", ""]
    for i, r in enumerate(ranking(banks, months, senior), 1):
        tag = " [SFB: insured only to Rs 5 lakh per bank]" if r["dicgc"] else ""
        L.append(f"{i:>2}. {r['bank']:<28} {r['rate']*100:5.2f}%  ({r['origin']}, {r['as_of']}){tag}")
    notes = [f"- {b['name']}: {b['note']}" for b in banks.values() if b["note"]]
    if notes:
        L += ["", "Notes:"] + notes
    L += ["", "Card rates for fresh deposits; interest is taxed at your slab every year. Verify on the bank's site before booking."]
    return "\n".join(L)
