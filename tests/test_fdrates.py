"""FD rate parsing, fallbacks and wiring. Synthetic pages only; no network."""
from datetime import date

from pe import fdrates as F

TABLE = """<table><tr><th>Tenure</th><th>General</th><th>Senior</th></tr>
<tr><td>7 days to 45 days</td><td>3.00%</td><td>3.50%</td></tr>
<tr><td>46 days to 179 days</td><td>4.50%</td><td>5.00%</td></tr>
<tr><td>1 year to less than 2 years</td><td>6.50%</td><td>7.00%</td></tr>
<tr><td>2 years to less than 3 years</td><td>6.40%</td><td>6.90%</td></tr></table>"""
LIST = "<ul><li>181 days - 364 days</li><li>6.25</li><li>1 year</li><li>6.9</li><li>Above 3 years</li><li>6.1</li></ul>"


def test_parse_table_and_tenure_bounds():
    rows = F.parse_rates(TABLE)
    assert len(rows) == 4 and rows[2]["general"] == 0.065 and rows[2]["senior"] == 0.07
    assert rows[2]["lo"] <= 365 <= rows[2]["hi"] < 730
    assert F.rate_for(rows, 12) == 0.065 and F.rate_for(rows, 18, senior=True) == 0.07


def test_parse_list_layout_and_open_ended_tenure():
    rows = F.parse_rates(LIST)
    assert [r["general"] for r in rows] == [0.0625, 0.069, 0.061]
    assert rows[2]["hi"] == float("inf")


def test_ignores_implausible_rates_and_junk():
    assert F.parse_rates("<td>1 year</td><td>65</td><td>0.1</td>") == []
    assert not F._sane(F.parse_rates("<td>1 year</td><td>6.5</td>"))


def _cfg(tmp_path, monkeypatch, url="http://x"):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"banks:\n  a:\n    name: A\n    kind: large\n    url: {url}\n    as_of: 2026-01-01\n"
                   "    slabs: [[7, 364, 5.0], [365, 729, 6.0], [730, 1825, 5.5]]\n"
                   "  s:\n    name: S\n    kind: sfb\n    as_of: 2026-01-01\n    slabs: [[7, 364, 6.0], [365, 729, 8.0]]\n")
    monkeypatch.setattr(F, "CFG", cfg)
    monkeypatch.setattr(F, "CACHE", tmp_path / "cache.json")


def test_fallback_order_live_then_cache_then_manual(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    live = F.parse_rates(TABLE)
    monkeypatch.setattr(F, "fetch_bank", lambda src: live)
    r = F.current(today=date(2026, 11, 1))
    assert r["a"]["origin"] == "live" and r["s"]["origin"] == "manual"   # no url -> manual
    def boom(src): raise OSError("blocked")
    monkeypatch.setattr(F, "fetch_bank", boom)
    r = F.current(today=date(2026, 11, 10))
    assert r["a"]["origin"] == "cache" and "9 days ago" in r["a"]["note"]
    (tmp_path / "cache.json").unlink()
    r = F.current(today=date(2026, 11, 10))
    assert r["a"]["origin"] == "manual" and "failed" in r["a"]["note"]
    assert F.rate_for(r["a"]["rows"], 12) == 0.06


def test_stale_cache_flagged(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(F, "fetch_bank", lambda s: F.parse_rates(TABLE))
    F.current(today=date(2026, 1, 1))
    monkeypatch.setattr(F, "fetch_bank", lambda s: (_ for _ in ()).throw(OSError("x")))
    assert "stale" in F.current(today=date(2026, 3, 1))["a"]["note"]


def test_class_yields_ignore_manual_and_sfb_takes_best(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    manual = F.current(refresh=False)
    assert F.class_yields(manual) == {}                       # manual card never overrides class defaults
    banks = {"a": {**manual["a"], "origin": "live"}, "s": {**manual["s"], "origin": "cache"}}
    y = F.class_yields(banks, 12)
    assert y["bank_fd"] == 0.06 and y["sfb_fd"] == 0.08
    spec = {"classes": [{"key": "bank_fd", "income_yield": 0.066}, {"key": "sfb_fd", "income_yield": 0.08}, {"key": "x"}]}
    monkeypatch.setattr(F, "current", lambda refresh=False: banks)
    F.apply_to_classes(spec)
    assert spec["classes"][0]["income_yield"] == 0.06


def test_ranking_and_render_flag_sfb(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    banks = F.current(refresh=False)
    rk = F.ranking(banks, 12)
    assert rk[0]["bank"] == "S" and rk[0]["dicgc"]
    assert "Rs 5 lakh" in F.render(banks, 12)
