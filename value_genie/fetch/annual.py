"""Annual-report text material for the modeling workbench.

Probe-finalized 2026-10-04 (data/probe_mdna.py):

- A: emweb PC_HSF10 BusinessAnalysis — ``jyps`` latest-period MD&A
  review (BUSINESS_REVIEW, full text), ``zygcfx`` multi-year segment
  breakdown (income/cost/profit by product line), ``zyfw`` business
  scope; OperationsRequired — ``hxtc`` core themes, ``jgyc`` sell-side
  consensus forecasts, ``ybzy`` research ratings; CompanyManagement —
  ``gglb`` executive bios. NOTE: jyps serves only the LATEST period
  (pagination is ignored, verified on SH600519) — historical MD&A full
  text lives in annual-report PDFs, and without a PDF parser in the
  global Python that history remains a declared gap.
- US: SEC EDGAR 10-K primary document — Item 1 (Business) and Item 7
  (MD&A) section slices, HTML stripped with the stdlib parser.
- HK: no text source without a PDF parser — gap only.

All network entry points are module-level (monkeypatch boundary);
a source failure returns None (fail-closed).
"""

import json
import re
from html.parser import HTMLParser

from .. import config
from ..users import normalize_code
from .http import SEC, Fetcher

EMWEB = Fetcher({"User-Agent": config.EM_UA}, "EMWEB")

_BA_URL = ("https://emweb.securities.eastmoney.com/PC_HSF10/"
           "BusinessAnalysis/PageAjax")
_OR_URL = ("https://emweb.securities.eastmoney.com/PC_HSF10/"
           "OperationsRequired/PageAjax")
_CM_URL = ("https://emweb.securities.eastmoney.com/PC_HSF10/"
           "CompanyManagement/PageAjax")

_PDF_GAP = ("historical MD&A / prospectus full text lives in disclosure "
            "PDFs; no PDF parser in the global Python — install pypdf "
            "globally to unlock (user installs, never vendored)")


def _a_emcode(code: str) -> str:
    """688795 -> SH688795 (6/9 SH, 4/8 BJ, else SZ)."""
    head = code[0]
    pre = "SH" if head in "69" else "BJ" if head in "48" else "SZ"
    return f"{pre}{code}"


def _txt(v) -> str:
    return str(v).strip() if v not in (None, "") else ""


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# A-share: emweb F10 annual texts + consensus
# ---------------------------------------------------------------------------
def fetch_annual_a(code: str) -> dict | None:
    code = normalize_code("A", code)
    em = _a_emcode(code)
    ba = EMWEB.get_json(_BA_URL, params={"code": em}, retries=2)
    if not ba:
        return None
    jyps = (ba.get("jyps") or [])
    latest = jyps[0] if jyps else {}
    segments = [{
        "report_date": _txt(r.get("REPORT_DATE"))[:10],
        "type": _txt(r.get("MAINOP_TYPE")),
        "item": _txt(r.get("ITEM_NAME")),
        "income": _num(r.get("MAIN_BUSINESS_INCOME")),
        "income_ratio": _num(r.get("MBI_RATIO")),
        "cost": _num(r.get("MAIN_BUSINESS_COST")),
        "gross_margin": _num(r.get("GROSS_RPOFIT_RATIO")),
    } for r in (ba.get("zygcfx") or [])]
    zyfw = (ba.get("zyfw") or [{}])
    out = {
        "id": f"A:{code}", "market": "A", "code": code,
        "source": "emweb_hsf10_businessanalysis",
        "mdna_latest": {
            "report_date": _txt(latest.get("REPORT_DATE"))[:10],
            "text": _txt(latest.get("BUSINESS_REVIEW")),
        },
        "segments": segments,
        "business_scope": _txt(zyfw[0].get("BUSINESS_SCOPE")),
        "gaps": [_PDF_GAP],
    }
    op = EMWEB.get_json(_OR_URL, params={"code": em}, retries=2)
    if op:
        out["core_themes"] = [{
            "keyword": _txt(r.get("KEYWORD")),
            "title": _txt(r.get("MAINPOINT")),
            "content": _txt(r.get("MAINPOINT_CONTENT")),
        } for r in (op.get("hxtc") or [])]
        out["consensus"] = {
            "forecasts": [{
                "org": _txt(r.get("ORG_NAME_ABBR")),
                "publish_date": _txt(r.get("PUBLISH_DATE"))[:10],
                "years": [y for y in ({
                    "year": _txt(r.get(f"YEAR{i}"))
                        or _txt(r.get(f"YEAR_MARK{i}")),
                    "eps": _num(r.get(f"EPS{i}")),
                    "pe": _num(r.get(f"PE{i}")),
                    "net_profit": _num(r.get(f"NETPROFIT{i}")),
                } for i in (1, 2, 3, 4)) if y["year"] or y["eps"]],
            } for r in (op.get("jgyc") or [])],
            "ratings": [{
                "publish_date": _txt(r.get("publish_time"))[:10],
                "rating": _txt(r.get("rating")),
                "rating_name": _txt(r.get("em_rating_name")),
                "aim_price": _num(r.get("aim_price")),
                "report_type": _txt(r.get("report_type")),
                "title": _txt(r.get("title")),
            } for r in (op.get("ybzy") or [])],
        }
    else:
        out.setdefault("gaps", []).append(
            "OperationsRequired (themes/consensus) unreachable")
    cm = EMWEB.get_json(_CM_URL, params={"code": em}, retries=2)
    if cm:
        out["management"] = [{
            "name": _txt(r.get("PERSON_NAME")),
            "position": _txt(r.get("POSITION")),
            "resume": _txt(r.get("RESUME")),
        } for r in (cm.get("gglb") or [])]
    return out


# ---------------------------------------------------------------------------
# US: SEC EDGAR 10-K Item 1 / Item 7 slices
# ---------------------------------------------------------------------------
class _HTMLText(HTMLParser):
    """Minimal stdlib HTML->text (block tags become newlines)."""

    _BLOCKS = {"p", "div", "br", "tr", "table", "h1", "h2", "h3", "h4",
               "li", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        return re.sub(r"[ \t]+", " ",
                      re.sub(r"\n\s*\n+", "\n\n", raw)).strip()


def _strip_html(html: str) -> str:
    p = _HTMLText()
    p.feed(html)
    return p.text()


def _slice_item(text: str, start_pat: str, end_pats: list,
                max_len: int = 80000) -> str:
    """Slice a 10-K section: last occurrence of the item heading (the
    body, not the TOC) to the next item heading after it. Only
    line-anchored matches bound the slice when any exist — MD&A bodies
    cite sibling items mid-sentence (KO FY2025: 'see Item 8. Financial
    Statements…' 467 chars into the section), and first-hit logic on
    such a cross-reference truncated the whole MD&A away."""
    def hits(pat: str) -> list:
        return [(m.start(), m.end())
                for m in re.finditer(pat, text, re.I)]

    def anchored(hs: list) -> list:
        return [h for h in hs if h[0] == 0 or text[h[0] - 1] == "\n"]

    sh = hits(start_pat)
    starts = anchored(sh) or sh
    if not starts:
        return ""
    s = max(h[1] for h in starts)
    ends = []
    for ep in end_pats:
        ends.extend(h[0] for h in anchored(hits(ep)) if h[0] > s)
    if not ends:   # no line-anchored heading anywhere — layout variance
        for ep in end_pats:
            ends.extend(h[0] for h in hits(ep) if h[0] > s)
    end = min(ends) if ends else len(text)
    chunk = text[s:end].strip()
    if len(chunk) < 500:      # mis-sliced (TOC hit) — declare, don't fake
        return ""
    return chunk[:max_len]


def fetch_annual_us(ticker: str) -> dict | None:
    from .fundamentals import load_sec_cik_map
    ticker = normalize_code("US", ticker)
    cik = (load_sec_cik_map() or {}).get(ticker)
    if not cik:
        return None
    sub = SEC.get_json(
        config.SEC_SUBMISSIONS_URL_TMPL.format(cik=int(cik)),
        timeout=30)
    if not sub:
        return None
    recent = (sub.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accs = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    dates = recent.get("filingDate") or []
    idx = next((i for i, f in enumerate(forms) if f == "10-K"), None)
    if idx is None:
        return None
    acc = str(accs[idx]).replace("-", "")
    doc = str(docs[idx])
    url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
           f"{acc}/{doc}")
    html = SEC.get_text(url, timeout=60)
    if not html:
        return None
    text = _strip_html(html)
    item1 = _slice_item(text, r"Item\s+1[\.\:\s—-]+Business",
                        [r"Item\s+1A[\.\:\s—-]", r"Item\s+2[\.\:\s—-]"])
    item7 = _slice_item(text,
                        r"Item\s+7[\.\:\s—-]+Management",
                        [r"Item\s+7A[\.\:\s—-]", r"Item\s+8[\.\:\s—-]"])
    gaps = []
    if not item1:
        gaps.append("Item 1 (Business) slice failed — 10-K layout "
                    "variance; read the filing at the url")
    if not item7:
        gaps.append("Item 7 (MD&A) slice failed — same remedy")
    return {
        "id": f"US:{ticker}", "market": "US", "code": ticker,
        "source": "sec_edgar_10k",
        "tenk": {"accession": accs[idx], "filing_date": dates[idx],
                 "url": url,
                 "item1_business": item1, "item7_mdna": item7,
                 "full_text_len": len(text)},
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# Dispatcher (HK: PDF-only sources -> gap, handled by the caller)
# ---------------------------------------------------------------------------
FETCHERS = {"A": fetch_annual_a, "US": fetch_annual_us}


def fetch_annual(market: str, code: str) -> dict | None:
    fn = FETCHERS.get(market)
    return fn(code) if fn else None
