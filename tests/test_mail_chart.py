"""Tests for the pure-stdlib NAV chart (polar_star/mail_chart.py)."""

import struct
import zlib

import pytest

from polar_star import mail_chart as mc
from polar_star import trade


def _pixel(png: bytes, x: int, y: int) -> tuple:
    """RGB at (x, y) — the renderer writes filter byte 0 per row, so
    scanline reconstruction is a plain stride skip."""
    pos, idat, w = 8, b"", 0
    while pos < len(png):
        ln = struct.unpack(">I", png[pos:pos + 4])[0]
        tag = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            w = struct.unpack(">I", data[:4])[0]
        elif tag == b"IDAT":
            idat += data
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * 3 + 1
    off = y * stride + 1 + x * 3
    return tuple(raw[off:off + 3])


def _season(sid="s001", status="active", cur="USD", init=10000.0,
            marks=None):
    marks = marks or [("2026-09-16", 10000.0), ("2026-09-17", 10100.0),
                      ("2026-09-18", 9950.0)]
    return {"id": sid, "status": status, "base_currency": cur,
            "initial_capital": init,
            "nav_history": [{"date": d, "nav": v} for d, v in marks]}


class TestSeasonsCurves:
    def test_active_seasons_become_net_return_curves(self, monkeypatch):
        monkeypatch.setattr(
            trade, "list_seasons",
            lambda: [{"id": "s001", "status": "active"},
                     {"id": "s002", "status": "paused"},
                     {"id": "s003", "status": "active"}])
        seasons = {"s001": _season(),
                   "s002": _season(sid="s002"),
                   "s003": _season(sid="s003", cur="CNY")}
        monkeypatch.setattr(trade, "load_season",
                            lambda sid: seasons[sid])
        curves = mc.seasons_curves()
        # paused seasons never draw
        assert [c["id"] for c in curves] == ["s001", "s003"]
        first = curves[0]
        assert first["label"] == "S1 US"      # enumerated + currency tag
        # enumerate counts every season incl. the skipped paused one
        assert curves[1]["label"] == "S3 A"
        # points are (iso date, net return % vs initial capital)
        assert first["points"][1] == ("2026-09-17", pytest.approx(1.0))
        assert first["points"][2] == ("2026-09-18", pytest.approx(-0.5))

    def test_markless_and_same_day_seasons_skipped(self, monkeypatch):
        one_mark = _season(sid="s1",
                           marks=[("2026-09-16", 10000.0)])
        same_day = _season(sid="s2",
                           marks=[("2026-09-16", 10000.0)] * 3)
        monkeypatch.setattr(trade, "list_seasons", lambda: [
            {"id": "s1", "status": "active"},
            {"id": "s2", "status": "active"}])
        monkeypatch.setattr(
            trade, "load_season",
            lambda sid: {"s1": one_mark, "s2": same_day}[sid])
        assert mc.seasons_curves() == []

    def test_transfers_adjust_curve_to_digest_contract(self, monkeypatch):
        # net return must match trade._summary_from: nav + withdrawn -
        # deposited (S2 is a dividend season — raw NAV understates it)
        season = {"id": "s001", "status": "active", "base_currency": "USD",
                  "initial_capital": 10000.0,
                  "nav_history": [
                      {"date": "2026-09-16", "nav": 10000.0},
                      {"date": "2026-09-17", "nav": 10100.0},
                      {"date": "2026-09-18", "nav": 9600.0}],
                  "fills": [
                      {"action": "deposit", "date": "2026-09-10",
                       "base_value": 200.0},
                      {"action": "withdraw", "date": "2026-09-18",
                       "base_value": 500.0}]}
        monkeypatch.setattr(trade, "list_seasons",
                            lambda: [{"id": "s001", "status": "active"}])
        monkeypatch.setattr(trade, "load_season", lambda sid: season)
        pts = mc.seasons_curves()[0]["points"]
        assert pts[0][1] == pytest.approx(-2.0)   # deposit drags the mark
        assert pts[1][1] == pytest.approx(-1.0)
        assert pts[2][1] == pytest.approx(-1.0)   # withdrawal added back
        # last point == digest formula (nav + withdrawn - deposited)/init
        assert pts[2][1] == pytest.approx(
            (9600.0 + 500.0 - 200.0) / 10000.0 * 100.0 - 100.0)


def _curves():
    return [
        {"id": "s001", "label": "S1 US",
         "points": [("2026-09-16", 0.0), ("2026-09-17", -0.8),
                    ("2026-09-18", 1.2), ("2026-09-19", 0.4)]},
        {"id": "s002", "label": "S2 HK",
         "points": [("2026-09-16", 2.0), ("2026-09-17", 1.1),
                    ("2026-09-18", 1.9), ("2026-09-19", 2.6)]},
    ]


class TestRenderSeasons:
    def test_png_signature_and_dims(self):
        png = mc.render_seasons_png(_curves())
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", png[16:24])   # IHDR
        assert (w, h) == (640, 300)
        assert len(png) < 100_000   # inline attachment stays small

    def test_zero_line_always_in_span(self):
        # all-negative and all-positive windows must both clamp to 0
        for pts in ([("2026-09-16", -3.0), ("2026-09-17", -1.0)],
                    [("2026-09-16", 1.0), ("2026-09-17", 3.0)]):
            png = mc.render_seasons_png(
                [{"id": "s", "label": "S1", "points": pts}])
            assert png[:4] == b"\x89PNG"

    def test_single_day_span_renders(self):
        # d1 == d0 must not divide by zero (max(..., 1) guard)
        png = mc.render_seasons_png(
            [{"id": "s", "label": "S1",
              "points": [("2026-09-16", 0.0), ("2026-09-16", 1.0)]}])
        assert png[:4] == b"\x89PNG"

    def test_empty_curves_rejected(self):
        with pytest.raises(ValueError, match="no active season"):
            mc.render_seasons_png([])

    def test_legend_swatches_keep_their_own_curve_colors(self):
        # the legend must pair S1->red, S2->navy, S3->green; reversing
        # the palette independently of the curves once painted S1 navy
        curves = [
            {"id": "s1", "label": "S1 US",
             "points": [("2026-09-16", 0.0), ("2026-09-20", 9.0)]},
            {"id": "s2", "label": "S2 HK",
             "points": [("2026-09-16", 0.0), ("2026-09-20", 4.0)]},
            {"id": "s3", "label": "S3 A",
             "points": [("2026-09-16", 0.0), ("2026-09-20", -2.0)]},
        ]
        png = mc.render_seasons_png(curves)
        first_x = {}
        for x in range(0, 640):
            p = _pixel(png, x, 13)      # legend swatch band (y 9..18)
            if p in mc.PALETTE[:len(curves)]:
                first_x.setdefault(p, x)
        # left-to-right swatch order follows the curve order
        by_x = [c for c, _ in sorted(first_x.items(), key=lambda kv: kv[1])]
        assert by_x == mc.PALETTE[:len(curves)]

    def test_zero_line_drawn_between_gridlines(self):
        curves = [{"id": "s", "label": "S1",
                   "points": [("2026-09-16", 1.0), ("2026-09-20", -1.0)]}]
        png = mc.render_seasons_png(curves)
        # the zero reference spans the plot width in the ZERO tone; the
        # curve crossing it breaks at most a sample or two
        rows = [y for y in range(31, 278)
                if sum(1 for x in range(80, 560, 40)
                       if _pixel(png, x, y) == mc.ZERO) >= 10]
        assert rows, "no zero reference line in the plot area"


def _season_positions(sid="s001", status="active", cur="USD",
                      marks=None):
    if marks is None:
        marks = [("2026-10-22", [("US", "ZM", 10.0, 96.0, 91.0)]),
                 ("2026-10-23", [("US", "ZM", 10.0, 96.0, 91.0)])]
    positions = [{"market": m, "code": c, "qty": q, "avg_cost": cost,
                  "currency": cur}
                 for d, rows in marks
                 for m, c, q, p, cost in rows]
    return {"id": sid, "status": status, "base_currency": cur,
            "initial_capital": 10000.0,
            "positions": positions,
            "nav_history": [
                {"date": d,
                 "positions": [{"market": m, "code": c, "qty": q,
                                "price": p, "currency": cur}
                               for m, c, q, p, _ in rows]}
                for d, rows in marks]}


class TestPositionsPnl:
    def test_pnl_pct_from_latest_mark_cost(self, monkeypatch):
        season = _season_positions()
        monkeypatch.setattr(trade, "list_seasons",
                            lambda: [{"id": "s001", "status": "active"}])
        monkeypatch.setattr(trade, "load_season", lambda sid: season)
        rows = mc.positions_pnl()
        assert len(rows) == 1
        r = rows[0]
        assert r["label"] == "US:ZM"
        assert r["pct"] == pytest.approx((96.0 / 91.0 - 1.0) * 100.0)
        assert r["pnl"] == pytest.approx(50.0)      # (96-91) x 10
        assert r["currency"] == "USD"

    def test_paused_and_markless_seasons_skipped(self, monkeypatch):
        paused = _season_positions(sid="s002", status="paused")
        markless = _season_positions(sid="s003", marks=[])
        monkeypatch.setattr(trade, "list_seasons", lambda: [
            {"id": "s002", "status": "paused"},
            {"id": "s003", "status": "active"}])
        monkeypatch.setattr(trade, "load_season",
                            lambda sid: {"s002": paused,
                                         "s003": markless}[sid])
        assert mc.positions_pnl() == []

    def test_season_index_counts_every_season(self, monkeypatch):
        # labels match the NAV chart's S-numbering (paused seasons count)
        s1 = _season_positions(sid="s001", status="paused")
        s2 = _season_positions(sid="s002", cur="HKD",
                               marks=[("2026-10-23",
                                       [("HK", "3306", 500.0, 22.0,
                                         21.5)])])
        monkeypatch.setattr(trade, "list_seasons", lambda: [
            {"id": "s001", "status": "paused"},
            {"id": "s002", "status": "active"}])
        monkeypatch.setattr(trade, "load_season",
                            lambda sid: {"s001": s1, "s002": s2}[sid])
        rows = mc.positions_pnl()
        assert [(r["season"], r["label"]) for r in rows] == [(2, "HK:3306")]


class TestRenderPositions:
    def _items(self):
        return [
            {"season": 1, "label": "US:ZM", "pct": 5.2},
            {"season": 1, "label": "US:HRMY", "pct": -9.6},
            {"season": 2, "label": "HK:3306", "pct": 2.5},
            {"season": 3, "label": "A:603444", "pct": -10.1},
        ]

    def test_png_signature_dims_and_size(self):
        png = mc.render_positions_png(self._items())
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", png[16:24])
        assert w == 640
        assert h == 34 + 26 * 4 + 26      # height grows with row count
        assert len(png) < 100_000

    def test_all_zero_renders(self):
        items = [{"season": 1, "label": "US:ZM", "pct": 0.0}]
        assert mc.render_positions_png(items)[:4] == b"\x89PNG"

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="no open positions"):
            mc.render_positions_png([])

    def test_bars_carry_season_palette_colors(self):
        items = [{"season": 1, "label": "US:ZM", "pct": 5.2},
                 {"season": 2, "label": "HK:3306", "pct": 2.5},
                 {"season": 3, "label": "A:603444", "pct": -1.0}]
        png = mc.render_positions_png(items)
        row_y = [34 + 26 * i + 5 for i in range(3)]   # bar center band
        colors = []
        for y in row_y:
            seen = {_pixel(png, x, y) for x in range(104, 574)}
            hit = seen & set(mc.PALETTE)
            colors.append(hit.pop() if hit else None)
        assert colors == mc.PALETTE[:3]   # S1 red, S2 navy, S3 green
