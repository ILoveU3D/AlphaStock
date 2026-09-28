"""stockanalysis.com flight-data parsers, shared by intel.ratings and
fetch.profiles (lifted from intel/ratings.py 2026-09-29; the balanced
bracket scan and bare-key fixes are probe-validated 2026-09-09)."""

import json
import re


def sa_flight_array(html: str, key: str) -> str | None:
    """Extract `key:[...]` from an embedded flight-data payload via a
    quote-aware balanced bracket scan."""
    j = html.find(f"{key}:[")
    if j < 0:
        return None
    k = j + len(key) + 1            # position of '['
    depth, in_str, esc = 0, False, False
    start = k
    while k < len(html):
        c = html[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return html[start:k + 1]
        k += 1
    return None


def sa_flight_string(html: str, key: str) -> str | None:
    """Extract `key:"..."` (JS string literal with escapes) from the
    flight-data payload; returns the unescaped value."""
    j = html.find(f'{key}:"')
    if j < 0:
        return None
    k = j + len(key) + 1            # position of the opening quote
    esc = False
    start = k
    k += 1
    while k < len(html):
        c = html[k]
        if esc:
            esc = False
        elif c == "\\":
            esc = True
        elif c == '"':
            try:
                v = json.loads(html[start:k + 1])
                return v if isinstance(v, str) else None
            except json.JSONDecodeError:
                return None
        k += 1
    return None


def sa_json(blob: str) -> list | None:
    """Bare-key JS array literal -> parsed list. Two probe-validated
    fixes: quote bare keys, and leading-dot floats (stars:.6 -> 0.6)."""
    fixed = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)',
                   r'\1"\2"\3', blob)
    fixed = re.sub(r'([{:[,\s])\.(\d)', r'\g<1>0.\2', fixed)
    try:
        v = json.loads(fixed)
        return v if isinstance(v, list) else None
    except json.JSONDecodeError:
        return None
