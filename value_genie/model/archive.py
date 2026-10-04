"""Model archive: the AI-written cognitive dossier (model.json).

The dossier IS the model (user mandate 2026-10-03): machine gathers
raw material, the AI writes the understanding — business flywheel,
culture, reverse-DCF are the mandatory three-piece minimum; every other
dimension is AI-freeform (50 or 1000, weighted by AI judgment with the
basis written down — a weight without its basis is a placeholder and
gets flagged). No batch pipeline: one company at a time, by hand.

Quality bar: the dossier's information content must be >= the annual
report's (lint(): three-piece completeness + narrative weight bases +
text-volume ratio vs raw material). An INCOMPLETE dossier stays out of
the core_dcf hook.
"""

import json
from datetime import datetime
from pathlib import Path

from .. import config
from ..users import normalize_code
from . import store

SCHEMA_VERSION = 1

# machine-enforced minimum: dotted paths that must be non-empty
_REQUIRED = (
    "business_flywheel.text",
    "culture.vision",
    "culture.current_state",
    "reverse_dcf.implied_world",
    "reverse_dcf.my_world",
)

# free-form top-level blocks the writer may replace wholesale (@file)
_BLOCKS = ("world_narratives", "dimensions", "falsification_monitor")


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def archive_path(market: str, code: str) -> Path:
    return store._stock_dir(market, code) / "model.json"


def new_archive(market: str, code: str, name: str = "") -> dict:
    code = normalize_code(market, code)
    return {
        "id": f"{market}:{code}", "market": market, "code": code,
        "name": name, "version": SCHEMA_VERSION, "updated_at": _now(),
        "business_flywheel": {"text": "", "updated_at": None},
        "culture": {"vision": "", "current_state": "", "evidence": [],
                    "updated_at": None},
        "reverse_dcf": {"implied_world": "", "my_world": "", "gap": "",
                        "updated_at": None},
        "world_narratives": [],
        "dimensions": {},
        "falsification_monitor": [],
        "gaps": [],
        "changelog": [],
    }


def load_archive(market: str, code: str) -> dict | None:
    p = archive_path(market, code)
    return store._load_json(p, "model archive") if p.exists() else None


def save_archive(a: dict) -> Path:
    return store._save(archive_path(a["market"], a["code"]), a)


def _dig(obj: dict, parts: list):
    cur = obj
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return None, None
        cur = cur[p]
    return cur, parts[-1]


def _get_path(obj: dict, dotted: str):
    cur, leaf = _dig(obj, dotted.split("."))
    if cur is None:
        return None
    return cur.get(leaf) if isinstance(cur, dict) else None


def _set_path(obj: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def resolve_value(v: str):
    """A set value is text by default; '@path' loads a file (.json parsed,
    anything else as raw text) — long-form writing lives in files, not
    command lines."""
    v = v.strip()
    if v.startswith("@"):
        p = Path(v[1:]).expanduser()
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() == ".json":
            return json.loads(text)
        return text
    return v


def write_fields(market: str, code: str, updates: dict,
                 reason: str) -> dict:
    """Write understanding-layer fields; every change appends a changelog
    entry — reason is mandatory (the weight/argument IS the model, its
    basis is not optional)."""
    if not reason or not reason.strip():
        raise ValueError("--reason is required for every archive write")
    a = load_archive(market, code)
    if a is None:
        a = new_archive(market, code)
    for key, val in updates.items():
        if isinstance(val, str):
            val = resolve_value(val)
        top = key.split(".")[0]
        if top in _BLOCKS and "." not in key:
            a[top] = val
        elif top in ("business_flywheel", "culture", "reverse_dcf",
                     "dimensions", "gaps"):
            _set_path(a, key, val)
        else:
            raise ValueError(f"unknown archive key: {key} "
                             f"(blocks: {_BLOCKS}; sections: "
                             f"business_flywheel/culture/reverse_dcf/"
                             f"dimensions/gaps)")
        # stamp section update time
        if "." in key:
            sec = a.get(top)
            if isinstance(sec, dict) and "updated_at" in sec:
                sec["updated_at"] = _now()
        a.setdefault("changelog", []).append(
            {"at": _now(), "key": key, "reason": reason.strip()})
    a["updated_at"] = _now()
    save_archive(a)
    return a


def _text_volume(obj) -> int:
    """Character count of all string leaves (the dossier's information
    volume proxy — distilled text, not copied raw)."""
    if isinstance(obj, str):
        return len(obj)
    if isinstance(obj, dict):
        return sum(_text_volume(v) for k, v in obj.items()
                   if k not in ("changelog", "updated_at"))
    if isinstance(obj, list):
        return sum(_text_volume(v) for v in obj)
    return 0


def raw_text_volume(market: str, code: str) -> int:
    """Total characters of gathered raw material under raw/."""
    d = store.raw_dir(market, code)
    if not d.exists():
        return 0
    total = 0
    for p in d.glob("*.json"):
        try:
            total += _text_volume(
                json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return total


def lint(archive: dict) -> dict:
    """Quality bar (user mandate 2026-10-03): the dossier's information
    content must be >= the annual report's, else the modeling is
    unqualified. Machine-checkable portion: required three-piece minimum,
    narrative weight bases, and text-volume ratio vs raw material."""
    missing = [k for k in _REQUIRED
               if not str(_get_path(archive, k) or "").strip()]
    weak_weights = []
    for i, n in enumerate(archive.get("world_narratives") or []):
        if not isinstance(n, dict):
            weak_weights.append(f"world_narratives[{i}]: not an object")
            continue
        if not str(n.get("world") or "").strip():
            weak_weights.append(f"world_narratives[{i}]: no world text")
        if not str(n.get("weight_basis") or "").strip():
            weak_weights.append(
                f"world_narratives[{i}] ({n.get('name') or 'unnamed'}): "
                f"weight without basis — placeholder, not AI judgment")
    if not (archive.get("world_narratives") or []):
        weak_weights.append("no world_narratives — the model has no "
                            "world hypotheses")
    vol = _text_volume({k: v for k, v in archive.items()
                        if k not in ("changelog",)})
    raw_vol = raw_text_volume(archive["market"], archive["code"])
    ratio = (vol / raw_vol) if raw_vol > 0 else None
    min_ratio = config.MODEL_LINT_MIN_TEXT_RATIO
    if raw_vol == 0:
        missing.append("no raw material gathered — run `model gather`")
    elif ratio is not None and ratio < min_ratio:
        missing.append(
            f"text volume {vol} < {min_ratio:.0%} of raw material "
            f"{raw_vol} — dossier thinner than the annual report bar")
    complete = not missing and not weak_weights
    return {"complete": complete, "missing": missing,
            "weak_weights": weak_weights,
            "text_volume": vol, "raw_text_volume": raw_vol,
            "text_ratio": ratio, "min_ratio": min_ratio}


def status() -> list:
    """Modeling coverage: one row per dossier under models/."""
    out = []
    d = store.models_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*/*/model.json")):
        try:
            a = store._load_json(p, "model archive")
        except ValueError:
            continue
        out.append({"id": a["id"], "name": a.get("name", ""),
                    "updated_at": a.get("updated_at"),
                    "complete": lint(a)["complete"]})
    return out
