"""Tests for value_genie.fetch.annual (annual-report text material)."""

from value_genie.fetch import annual as fa

_BA = {
    "jyps": [{"REPORT_DATE": "2026-06-30 00:00:00",
              "BUSINESS_REVIEW": "经营评述全文" * 300}],
    "zygcfx": [
        {"REPORT_DATE": "2025-12-31 00:00:00", "MAINOP_TYPE": "2",
         "ITEM_NAME": "GPU 芯片", "MAIN_BUSINESS_INCOME": 1.2e9,
         "MBI_RATIO": 80.0, "MAIN_BUSINESS_COST": 6e8,
         "GROSS_RPOFIT_RATIO": 50.0},
        {"REPORT_DATE": "2024-12-31 00:00:00", "MAINOP_TYPE": "2",
         "ITEM_NAME": "GPU 芯片", "MAIN_BUSINESS_INCOME": 4e8,
         "MBI_RATIO": 90.0, "MAIN_BUSINESS_COST": 3e8,
         "GROSS_RPOFIT_RATIO": 25.0},
    ],
    "zyfw": [{"BUSINESS_SCOPE": "集成电路设计"}],
}
_OP = {
    "hxtc": [{"KEYWORD": "GPU", "MAINPOINT": "国产替代",
              "MAINPOINT_CONTENT": "全功能 GPU 平台" * 30}],
    "jgyc": [{"ORG_NAME_ABBR": "某券商", "PUBLISH_DATE": "2026-09-01",
              "YEAR1": "2026", "EPS1": -0.5, "PE1": None}],
    "ybzy": [{"publish_time": "2026-09-01 10:00", "rating": "buy",
              "em_rating_name": "买入", "aim_price": None,
              "report_type": "深度报告", "title": "GPU 平台启航"}],
}
_CM = {"gglb": [{"PERSON_NAME": "张建中", "POSITION": "董事长",
                 "RESUME": "前 NVIDIA 全球副总裁" * 20}]}


def _emweb_router(url, params=None, **kw):
    if "BusinessAnalysis" in url:
        return _BA
    if "OperationsRequired" in url:
        return _OP
    if "CompanyManagement" in url:
        return _CM
    return None


def test_a_aggregates_all_sections(monkeypatch):
    monkeypatch.setattr(fa.EMWEB, "get_json", _emweb_router)
    doc = fa.fetch_annual("A", "688795")
    assert doc["id"] == "A:688795"
    assert len(doc["mdna_latest"]["text"]) > 1000
    assert doc["mdna_latest"]["report_date"] == "2026-06-30"
    assert len(doc["segments"]) == 2
    assert doc["segments"][0]["item"] == "GPU 芯片"
    assert doc["business_scope"] == "集成电路设计"
    assert doc["core_themes"][0]["keyword"] == "GPU"
    assert doc["consensus"]["forecasts"][0]["org"] == "某券商"
    assert doc["consensus"]["ratings"][0]["rating_name"] == "买入"
    assert "NVIDIA" in doc["management"][0]["resume"]
    assert any("PDF" in g for g in doc["gaps"])   # PDF gap declared


def test_a_fail_closed_when_businessanalysis_down(monkeypatch):
    monkeypatch.setattr(fa.EMWEB, "get_json", lambda *a, **k: None)
    assert fa.fetch_annual("A", "688795") is None


def test_a_survives_partial_failure(monkeypatch):
    def router(url, params=None, **kw):
        if "BusinessAnalysis" in url:
            return _BA
        return None                       # OP and CM down
    monkeypatch.setattr(fa.EMWEB, "get_json", router)
    doc = fa.fetch_annual("A", "688795")
    assert doc is not None
    assert "consensus" not in doc
    assert any("OperationsRequired" in g for g in doc["gaps"])


# --- US: 10-K Item slicing -------------------------------------------------

_TENK_HTML = """
<html><body>
<p>PART I</p>
<p>Item 1. Business ... 2</p>
<p>Item 1A. Risk Factors ... 30</p>
<p>Item 7. Management's Discussion ... 55</p>
<p>Item 8. Financial Statements ... 90</p>
<div>Item 1. Business</div>
<div>Our company designs accelerated computing platforms. """ + \
    "Real business text. " * 200 + """</div>
<div>Item 1A. Risk Factors</div>
<div>Item 7. Management's Discussion and Analysis of Financial
Condition and Results of Operations</div>
<div>Revenue grew strongly. """ + "MD&A body text. " * 200 + """</div>
<div>Item 8. Financial Statements and Supplementary Data</div>
</body></html>
"""


def test_strip_html_drops_scripts_and_blocks():
    html = "<div>hello</div><script>var x=1;</script><p>world</p>"
    text = fa._strip_html(html)
    assert "hello" in text and "world" in text
    assert "var x" not in text


def test_slice_item_skips_toc():
    text = fa._strip_html(_TENK_HTML)
    item7 = fa._slice_item(text, r"Item\s+7[\.\:\s—-]+Management",
                           [r"Item\s+7A[\.\:\s—-]", r"Item\s+8[\.\:\s—-]"])
    assert "MD&A body text" in item7
    assert "Financial Statements and Supplementary" not in item7


def test_slice_item_ignores_mid_sentence_item_citations():
    # KO FY2025 case (2026-10-04): the MD&A opens by citing
    # 'Item 8. Financial Statements and Supplementary Data' mid-sentence
    # 467 chars in; first-hit end logic truncated the whole MD&A to ""
    # (<500 guard). Real headings are line-anchored, citations are not.
    html = ("<html><body>"
            "<p>Item 7. Management's Discussion and Analysis</p>"
            "<p>Read this together with 'Item 8. Financial Statements and"
            " Supplementary Data' of this report.</p>"
            "<p>" + "Operating results discussion. " * 200 + "</p>"
            "<p>Item 7A. Quantitative and Qualitative Disclosures</p>"
            "</body></html>")
    text = fa._strip_html(html)
    item7 = fa._slice_item(text, r"Item\s+7[\.\:\s—-]+Management",
                           [r"Item\s+7A[\.\:\s—-]", r"Item\s+8[\.\:\s—-]"])
    assert "Operating results discussion" in item7
    assert "Quantitative and Qualitative" not in item7


def test_us_10k_pipeline(monkeypatch):
    monkeypatch.setattr(fa, "_TENK_HTML", _TENK_HTML, raising=False)
    from value_genie.fetch import fundamentals as fund
    monkeypatch.setattr(fund, "load_sec_cik_map",
                        lambda: {"AAPL": "0000320193"})
    submissions = {
        "filings": {"recent": {
            "form": ["8-K", "10-K"],
            "accessionNumber": ["0001-26-000001", "0000-25-000099"],
            "primaryDocument": ["pr.htm", "aapl-10k.htm"],
            "filingDate": ["2026-02-01", "2025-11-01"]}}}
    monkeypatch.setattr(fa.SEC, "get_json",
                        lambda *a, **k: submissions)
    monkeypatch.setattr(fa.SEC, "get_text",
                        lambda *a, **k: _TENK_HTML)
    doc = fa.fetch_annual("US", "AAPL")
    assert doc["tenk"]["accession"] == "0000-25-000099"
    assert doc["tenk"]["filing_date"] == "2025-11-01"
    assert "/data/320193/" in doc["tenk"]["url"]   # Archives drops zeros
    assert "accelerated computing platforms" in doc["tenk"]["item1_business"]
    assert "MD&A body text" in doc["tenk"]["item7_mdna"]
    assert doc["gaps"] == []


def test_us_fail_closed_without_cik(monkeypatch):
    from value_genie.fetch import fundamentals as fund
    monkeypatch.setattr(fund, "load_sec_cik_map", lambda: {})
    assert fa.fetch_annual("US", "ZZZZ") is None


def test_hk_has_no_text_source():
    assert fa.fetch_annual("HK", "00700") is None
