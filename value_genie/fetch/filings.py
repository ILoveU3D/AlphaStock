"""Disclosure PDF full texts for the modeling workbench.

Probe-finalized 2026-10-04 (data/probe_filings.py):

- A: cninfo (法定披露平台) — topSearch maps code -> orgId, then
  hisAnnouncement query by category (``category_ndbg_szsh`` annual
  reports) or searchkey (``招股`` prospectus); PDFs on
  static.cninfo.com.cn are text-based (pypdf extracts cleanly,
  230 pages / 220k chars / ~10s).
- MD&A slicing: A-share annual reports carry ``第X节 管理层讨论与分析``
  (new-format reports) — the body heading is the first match past the
  TOC region; sliced to the next section heading.
- HK: HKEXnews PDFs — not yet probed; declared gap.
- US: 10-K HTML already covered by fetch/annual.py (no PDF needed).

pypdf is a soft dependency (user-installed into the global Python,
never vendored): without it every entry point returns None and the
gather reports a gap.
"""

import io
import re

from .. import config
from ..users import normalize_code
from .http import Fetcher

CN = Fetcher({"User-Agent": config.EM_UA}, "CNINFO")

CN_SEARCH_URL = ("http://www.cninfo.com.cn/new/information/"
                 "topSearch/query")
CN_QUERY_URL = ("http://www.cninfo.com.cn/new/hisAnnouncement/query")
CN_STATIC = "http://static.cninfo.com.cn/"

ANNUAL_CATEGORY = "category_ndbg_szsh"
PROSPECTUS_KEY = "招股"

_MDNA_START = re.compile(
    r"第[一二三四五六七八九十百]+节[\s　]*管理层讨论与分析")
_MDNA_END = re.compile(
    r"第[一二三四五六七八九十百]+节[\s　]*(?:公司治理|环境|重要事项|"
    r"股份变动|财务报告)")
_TOC_FRACTION = 0.05     # heading hits inside the first 5% = TOC
_MIN_MDNA_CHARS = 2000


def _pypdf():
    try:
        import pypdf
        return pypdf
    except ImportError:
        return None


def _cn_orgid(code: str) -> tuple | None:
    d = CN.post_json(CN_SEARCH_URL, data={"keyWord": code, "maxNum": 10},
                     retries=2)
    for it in d or []:
        if str(it.get("code")) == code:
            return str(it.get("orgId") or ""), str(it.get("zwjc") or "")
    return None


def _cn_query(code: str, org_id: str, category: str = "",
              searchkey: str = "", max_pages: int = 3) -> list:
    rows = []
    for page in range(1, max_pages + 1):
        d = CN.post_json(CN_QUERY_URL, data={
            "pageNum": page, "pageSize": 30, "column": "sse",
            "tabName": "fulltext", "plate": "",
            "stock": f"{code},{org_id}", "searchkey": searchkey,
            "secid": "", "category": category, "trade": "",
            "seDate": "", "sortName": "", "sortType": "",
            "isHLtitle": "true"}, retries=2)
        batch = ((d or {}).get("announcements")) or []
        rows += batch
        if len(batch) < 30:
            break
    return rows


def _pdf_text(url: str) -> tuple:
    """(full_text, page_count); (None, 0) on any failure."""
    pypdf = _pypdf()
    if pypdf is None:
        return None, 0
    raw = CN.get_bytes(url, timeout=180)
    if not raw or not raw.startswith(b"%PDF"):
        return None, 0
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        parts = [(p.extract_text() or "") for p in reader.pages]
        return "".join(parts), len(reader.pages)
    except Exception:
        return None, 0


def slice_mdna_a(text: str) -> tuple | None:
    """(start, end) of the MD&A section body, skipping the TOC."""
    starts = [m.start() for m in _MDNA_START.finditer(text)
              if m.start() > len(text) * _TOC_FRACTION]
    if not starts:
        return None
    s = starts[0]
    m = _MDNA_END.search(text, s)
    end = m.start() if m else len(text)
    if end - s < _MIN_MDNA_CHARS:
        return None
    return (s, end)


def _clean_title(t: str) -> str:
    return re.sub(r"</?em>", "", str(t or ""))


def fetch_filings_a(code: str,
                    max_reports: int | None = None,
                    with_prospectus: bool = True) -> dict | None:
    """Annual-report + prospectus full texts for one A-share company.

    Returns {id, source, reports: [{kind, title, date, url, pages,
    chars, text, mdna}], gaps}; ``text`` is the full extracted text and
    ``mdna`` the sliced MD&A section (when detectable). None on
    discovery failure (fail-closed)."""
    code = normalize_code("A", code)
    if _pypdf() is None:
        return None
    found = _cn_orgid(code)
    if not found or not found[0]:
        return None
    org_id, name = found
    limit = max_reports or config.FILINGS_MAX_REPORTS
    gaps = []
    reports = []

    rows = _cn_query(code, org_id, category=ANNUAL_CATEGORY)
    annual = [r for r in rows
              if "年度报告" in _clean_title(r.get("announcementTitle"))
              and "摘要" not in _clean_title(r.get("announcementTitle"))]
    annual.sort(key=lambda r: r.get("announcementTime") or 0,
                reverse=True)
    for r in annual[:limit]:
        title = _clean_title(r.get("announcementTitle"))
        url = CN_STATIC + str(r.get("adjunctUrl") or "")
        text, pages = _pdf_text(url)
        if text is None:
            gaps.append(f"PDF extraction failed: {title}")
            continue
        span = slice_mdna_a(text)
        reports.append({
            "kind": "annual", "title": title,
            "date": str(r.get("announcementTime") or ""),
            "url": url, "pages": pages, "chars": len(text),
            "text": text,
            "mdna": (text[span[0]:span[1]] if span else ""),
            "mdna_sliced": span is not None,
        })
        if span is None:
            gaps.append(f"MD&A section not detected: {title}")

    if with_prospectus:
        rows = _cn_query(code, org_id, searchkey=PROSPECTUS_KEY)
        prosp = [r for r in rows
                 if "招股说明书" in _clean_title(r.get("announcementTitle"))
                 and "提示性公告" not in _clean_title(
                     r.get("announcementTitle"))]
        prosp.sort(key=lambda r: r.get("announcementTime") or 0,
                   reverse=True)
        if prosp:
            r = prosp[0]
            title = _clean_title(r.get("announcementTitle"))
            url = CN_STATIC + str(r.get("adjunctUrl") or "")
            text, pages = _pdf_text(url)
            if text is None:
                gaps.append(f"PDF extraction failed: {title}")
            else:
                reports.append({
                    "kind": "prospectus", "title": title,
                    "date": str(r.get("announcementTime") or ""),
                    "url": url, "pages": pages, "chars": len(text),
                    "text": text,
                })
        else:
            gaps.append("no prospectus found on cninfo")

    if not reports:
        return None
    return {"id": f"A:{code}", "market": "A", "code": code,
            "name": name, "source": "cninfo", "reports": reports,
            "gaps": gaps}
