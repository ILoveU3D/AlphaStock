"""Inspect gathered raw material for a model target (campaign helper).

Usage: python scripts/model_peek.py US:TDC [section]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    target = sys.argv[1].replace(":", "/")
    section = sys.argv[2] if len(sys.argv) > 2 else "all"
    raw = ROOT / "models" / target / "raw"
    if not raw.exists():
        print(f"no raw material at {raw}")
        return
    if section in ("all", "history"):
        p = raw / "history.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            print(f"== history: {d.get('name')} ({d.get('source')})")
            for y in d.get("years", []):
                def m(k):
                    v = y.get(k)
                    return f"{v/1e6:.0f}M" if v is not None else "-"
                print(f"  {y['fy']}: rev={m('revenue')} ebit={m('ebit')} "
                      f"ni={m('net_income')} ocf={m('ocf')} "
                      f"capex={m('capex')} cash={m('cash')} debt={m('debt')} "
                      f"shares={y.get('shares')}")
    if section in ("all", "peers"):
        p = raw / "peers.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            t = d.get("target", {})
            print(f"== target: {t.get('name')} px={t.get('price')} "
                  f"mc={t.get('market_cap')} pe={t.get('pe_ttm')} "
                  f"ps={t.get('ps') and round(t.get('ps'), 2)} "
                  f"roe={t.get('roe') and round(t.get('roe'), 1)} "
                  f"rev_yoy={t.get('rev_yoy') and round(t.get('rev_yoy'), 1)} "
                  f"fcf_yield={t.get('fcf_yield') and round(t.get('fcf_yield'), 1)}")
            for pr in d.get("peers", []):
                print(f"  peer {pr.get('code')}: {pr.get('name')} "
                      f"pe={pr.get('pe_ttm')} ps={pr.get('ps') and round(pr.get('ps'), 2)} "
                      f"roe={pr.get('roe') and round(pr.get('roe'), 1)} "
                      f"rev_yoy={pr.get('rev_yoy') and round(pr.get('rev_yoy'), 1)}")
    if section in ("all", "annual"):
        p = raw / "annual.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            tk = d.get("tenk", {})
            print(f"== 10-K filed {tk.get('filing_date')} url={tk.get('url')}")
            for k, v in tk.items():
                if isinstance(v, str) and len(v) > 200:
                    print(f"  {k}: {len(v)} chars")
    if section in ("all", "intel"):
        p = raw / "intel.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            print(f"== intel: {len(d) if isinstance(d, list) else 'dict'} entries")
    if section == "mdna":
        d = json.loads((raw / "annual.json").read_text(encoding="utf-8"))
        mdna = d["tenk"]["item7_mdna"]
        print(mdna[:int(sys.argv[3]) if len(sys.argv) > 3 else 6000])
    if section == "item1":
        d = json.loads((raw / "annual.json").read_text(encoding="utf-8"))
        print(d["tenk"]["item1_business"][:int(sys.argv[3]) if len(sys.argv) > 3 else 6000])
    if section == "grep":
        d = json.loads((raw / "annual.json").read_text(encoding="utf-8"))
        kw = sys.argv[3]
        import re
        for sec in ("item1_business", "item7_mdna"):
            txt = d["tenk"].get(sec, "")
            for m in list(re.finditer(kw, txt, re.IGNORECASE))[:4]:
                print(f"[{sec}] ...{txt[max(0, m.start()-200):m.start()+300]}...".replace("\n", " "))
                print()


if __name__ == "__main__":
    main()
