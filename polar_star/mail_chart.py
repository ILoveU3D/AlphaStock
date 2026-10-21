"""NAV curve chart for the daily letter (user mandate 2026-10-21:
收益曲线使用图像展示).

Pure-stdlib renderer — the repo rule is pandas + requests only, so no
matplotlib/Pillow: curves are drawn pixel-by-pixel onto an RGB canvas
and encoded as PNG with zlib. In-image text uses a built-in 5x7 ASCII
bitmap font (Chinese lives in the letter HTML around the image, so no
font files are needed). ``mail send`` replaces the ``{{NAV_CHART}}``
fragment marker with a CID-referenced <img> of this chart.
"""

import struct
import zlib
from bisect import bisect_right
from datetime import date

# ---------------------------------------------------------------------------
# Seasons -> curve points (read-only; no NAV marking here — the digest
# already walked the mark path)
# ---------------------------------------------------------------------------
_CURRENCY_TAG = {"USD": "US", "HKD": "HK", "CNY": "A"}


def _transfer_adjustments(season) -> tuple:
    """(sorted dates, cumulative adjustments) for the net-return series —
    withdrawals re-enter the return (+), deposits leave it (-), the same
    contract as trade._summary_from's net_return_pct, so the chart agrees
    with the letter's headline numbers (S2 is the dividend season: raw NAV
    understates a withdrawing account)."""
    rows = []
    for f in season.get("fills") or []:
        if f.get("action") not in ("deposit", "withdraw"):
            continue
        try:
            v = float(f.get("base_value") or 0.0)
        except (TypeError, ValueError):
            continue
        rows.append((str(f.get("date") or ""),
                     v if f["action"] == "withdraw" else -v))
    rows.sort()
    dates, cums, running = [], [], 0.0
    for d, v in rows:
        running += v
        dates.append(d)
        cums.append(running)
    return dates, cums


def seasons_curves() -> list:
    """[{id, label, points: [(iso_date, net_return_pct), ...]}] for
    every active season with at least two NAV marks. Net return is
    transfer-adjusted (withdrawn +, deposited -), matching the digest."""
    from . import trade

    out = []
    for i, s in enumerate(trade.list_seasons(), start=1):
        if s.get("status") != "active":
            continue
        season = trade.load_season(s["id"])
        init = float(season.get("initial_capital") or 0)
        if init <= 0:
            continue
        tx_dates, tx_cums = _transfer_adjustments(season)
        pts = []
        for e in season.get("nav_history") or []:
            try:
                nav = float(e["nav"])
                d = str(e["date"])
                date.fromisoformat(d)
            except (KeyError, TypeError, ValueError):
                continue
            if nav > 0:
                k = bisect_right(tx_dates, d)
                adj = tx_cums[k - 1] if k else 0.0
                pts.append((d, (nav + adj) / init * 100.0 - 100.0))
        if len(pts) >= 2 and pts[0][0] != pts[-1][0]:
            tag = _CURRENCY_TAG.get(season.get("base_currency"), "")
            out.append({"id": s["id"],
                        "label": f"S{i} {tag}".strip(),
                        "points": pts})
    return out


# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------
PALETTE = [(0xc8, 0x00, 0x00),   # S1 red (letter accent)
           (0x10, 0x24, 0x3e),   # S2 navy (masthead)
           (0x1a, 0x7a, 0x4a),   # S3 green (down-green family)
           (0xb8, 0x86, 0x0f)]   # S4 gold (fallback)
GRID = (0xe6, 0xeb, 0xf0)
ZERO = (0xb8, 0xc2, 0xce)
TEXT = (0x5a, 0x6b, 0x7f)
BG = (0xff, 0xff, 0xff)


# 5x7 bitmap font (uppercase ASCII + symbols), one 5-char bit row each.
FONT5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "-": ["00000", "00000", "00000", "01110", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "00000", "00100"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    ":": ["00000", "00100", "00000", "00000", "00000", "00100", "00000"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


class _Canvas:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.px = [[BG] * w for _ in range(h)]

    def point(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = color

    def hline(self, x0, x1, y, color):
        for x in range(x0, x1 + 1):
            self.point(x, y, color)

    def rect_fill(self, x, y, w, h, color):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.point(xx, yy, color)

    def line(self, x0, y0, x1, y1, color, thickness=2):
        """Bresenham with a vertical smear for thickness."""
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x1 >= x0 else -1
        sy = 1 if y1 >= y0 else -1
        err = dx - dy
        x, y = x0, y0
        while True:
            for t in range(thickness):
                self.point(x, y + t, color)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def text(self, x, y, s, color, scale=1):
        cx = x
        for ch in str(s).upper():
            glyph = FONT5X7.get(ch) or FONT5X7[" "]
            for ry, row in enumerate(glyph):
                for rx, bit in enumerate(row):
                    if bit == "1":
                        self.rect_fill(cx + rx * scale, y + ry * scale,
                                       scale, scale, color)
            cx += 6 * scale
        return cx

    def text_width(self, s, scale=1):
        return len(str(s)) * 6 * scale

    def png(self) -> bytes:
        raw = bytearray()
        for row in self.px:
            raw.append(0)
            for p in row:
                raw.extend(p)

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
                + chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
def render_seasons_png(curves: list, width: int = 640,
                       height: int = 300) -> bytes:
    """One line per season: cumulative net return %, x = date."""
    if not curves:
        raise ValueError("no active season curves to draw")
    pad = {"l": 46, "r": 14, "t": 30, "b": 22}
    plot_w = width - pad["l"] - pad["r"]
    plot_h = height - pad["t"] - pad["b"]

    days = []
    vals = []
    for c in curves:
        for d, v in c["points"]:
            days.append(date.fromisoformat(d))
            vals.append(v)
    d0, d1 = min(days), max(days)
    vmin, vmax = min(vals), max(vals)
    if vmax < 0:
        vmax = 0.0
    if vmin > 0:
        vmin = 0.0
    span = (vmax - vmin) or 1.0
    vmin, vmax = vmin - span * 0.08, vmax + span * 0.08

    def x_of(d) -> int:
        frac = ((d - d0).days / max((d1 - d0).days, 1))
        return pad["l"] + int(frac * plot_w)

    def y_of(v) -> int:
        frac = (v - vmin) / (vmax - vmin)
        return pad["t"] + int((1.0 - frac) * plot_h)

    cv = _Canvas(width, height)

    # horizontal grid: 5 evenly spaced guides; the zero line is the
    # reference a cumulative-return chart is read against, so it gets
    # its own heavier tone wherever it falls (never on a gridline)
    for i in range(5):
        v = vmin + (vmax - vmin) * i / 4.0
        y = y_of(v)
        cv.hline(pad["l"], width - pad["r"], y, GRID)
        label = f"{v:+.1f}%" if abs(v) >= 0.05 else "0.0%"
        cv.text(pad["l"] - cv.text_width(label) - 6, y - 3, label, TEXT)
    if vmin < 0 < vmax:
        cv.hline(pad["l"], width - pad["r"], y_of(0.0), ZERO)

    for c, color in zip(curves, PALETTE):
        pts = [(x_of(date.fromisoformat(d)), y_of(v))
               for d, v in c["points"]]
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            cv.line(xa, ya, xb, yb, color)

    # title (left) + legend (right, one swatch per curve drawn right to
    # left; every swatch keeps its own curve's color — pairing drifts if
    # the palette is reversed independently of the curves)
    cv.text(pad["l"], 8, "CUMULATIVE RETURN", TEXT, scale=2)
    title_end = pad["l"] + cv.text_width("CUMULATIVE RETURN", scale=2)
    lx = width - pad["r"]
    for i in range(len(curves) - 1, -1, -1):
        lw = cv.text_width(curves[i]["label"], scale=2)
        if lx - lw - 26 < title_end + 12:
            break   # never collide with the title
        cv.text(lx - lw, 8, curves[i]["label"], TEXT, scale=2)
        cv.rect_fill(lx - lw - 16, 9, 10, 10, PALETTE[i])
        lx -= lw + 26

    # x labels: first / last date
    for d, x in ((d0, pad["l"]), (d1, width - pad["r"])):
        s = d.strftime("%m-%d")
        cv.text(max(min(x, width - pad["r"] - cv.text_width(s)),
                    pad["l"]), height - 15, s, TEXT)
    return cv.png()
