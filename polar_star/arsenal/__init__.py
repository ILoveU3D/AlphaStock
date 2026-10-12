"""量化武器库 (Arsenal) — every quantitative algorithm in the toolkit.

House rules (user mandates 2026-10-12/13):
- One weapon = one independent module + one registry entry (JSON).
  No scanner/deep castes: any weapon can dissect one stock (run) or
  sweep a whole market (scan); ``sweepable`` only flags compute cost.
- Entry ticket: verified lineage (paper / classic book / master
  practice / toolkit veteran). No trust lifecycle — a registered weapon
  is trusted; status is only ``armed`` (data-ready) or ``dormant``
  (waiting for a data source).
- strategy/ keeps strategy DECLARATIONS only (ids, weights, gate DSL,
  fame order); all computation lives here.

Registry entries: ``registry/<weapon-id>.json``; the module name is the
conventional ``<weapon_id>.py`` with dashes turned to underscores, and
each module exposes ``run(ctx, **params) -> dict``.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

REGISTRY_DIR = Path(__file__).resolve().parent / "registry"

_REGISTRY_CACHE: dict[str, dict] | None = None


def load_registry(force: bool = False) -> dict[str, dict]:
    """Scan registry/*.json -> {weapon_id: meta} (cached)."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None and not force:
        return _REGISTRY_CACHE
    out: dict[str, dict] = {}
    for p in sorted(REGISTRY_DIR.glob("*.json")):
        meta = json.loads(p.read_text(encoding="utf-8"))
        wid = meta.get("id") or p.stem
        if wid != p.stem:
            raise ValueError(
                f"arsenal registry id mismatch: {p.name} carries {wid!r}")
        meta.setdefault("module", wid.replace("-", "_"))
        out[wid] = meta
    _REGISTRY_CACHE = out
    return out


def list_weapons(stage: str = "", status: str = "") -> list[dict]:
    """Registry entries, optionally filtered by stage/status, id-sorted."""
    items = list(load_registry().values())
    if stage:
        items = [m for m in items if m.get("stage") == stage]
    if status:
        items = [m for m in items if m.get("status") == status]
    return items


def get_weapon(wid: str) -> dict:
    """One registry entry; ValueError with the known ids when unknown."""
    reg = load_registry()
    try:
        return reg[wid]
    except KeyError:
        known = ", ".join(sorted(reg))
        raise ValueError(
            f"unknown weapon {wid!r}; arsenal holds: {known}") from None


def weapon_runner(wid: str):
    """Import the weapon module and return its ``run`` callable."""
    meta = get_weapon(wid)
    mod = importlib.import_module(f"polar_star.arsenal.{meta['module']}")
    run = getattr(mod, "run", None)
    if not callable(run):
        raise ValueError(f"weapon {wid!r} module {meta['module']}.py "
                         f"has no run(ctx, **params)")
    return run


def build_context(data_dir=None, snapshot=None, with_kline=None) -> dict:
    """Assemble the execution context for run/scan/battery/screen.

    Keys: ``snap`` (snapshot dir), ``master`` (master.csv frame);
    with ``with_kline=(market, code)`` also ``row`` (the master row, or
    None when absent from the funnel) and ``kline`` (daily bars frame or
    None).  Live quotes / intel events are layered by the CLI callers,
    not here — this context is snapshot-pure and network-free.
    """
    from ..report import load_master, resolve_snapshot

    snap = resolve_snapshot(data_dir, snapshot)
    master = load_master(snap)
    ctx: dict = {"snap": snap, "master": master}
    if with_kline:
        from ..fetch.kline import kline_cache_path, load_kline
        market, code = str(with_kline[0]), str(with_kline[1])
        p = kline_cache_path(snap, market, code)
        ctx["kline"] = load_kline(p) if p.exists() else None
        row = master[(master["market"].astype(str) == market)
                     & (master["code"].astype(str) == code)]
        ctx["row"] = row.iloc[0] if len(row) else None
    return ctx
