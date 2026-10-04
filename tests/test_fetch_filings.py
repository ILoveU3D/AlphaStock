"""Tests for value_genie.fetch.filings (cninfo disclosure PDFs)."""

import json

import pytest

from value_genie import config
from value_genie.fetch import filings as ff
from value_genie.model import gather as mg
from value_genie.model import store


def _fake_annual_text(body_chars=6000):
    """Fake annual-report text: TOC hit inside the first 5%, body
    heading after it, MD&A body, then the next section."""
    toc = "目录\n第三节 管理层讨论与分析 ... 25\n" + "x" * 100
    filler = "第一节 释义\n" + "释" * 4000
    body = ("第三节 管理层讨论与分析\n一、经营情况讨论与分析\n"
            + "经营讨论正文。" * (body_chars // 7))
    tail = "第四节 公司治理\n" + "治理" * 500
    return toc + filler + body + tail


class TestSliceMdna:
    def test_skips_toc_and_slices_body(self):
        text = _fake_annual_text()
        span = ff.slice_mdna_a(text)
        assert span is not None
        chunk = text[span[0]:span[1]]
        assert "经营讨论正文" in chunk
        assert "公司治理" not in chunk
        assert not chunk.startswith("目录")

    def test_too_short_is_rejected(self):
        text = ("x" * 1000) + "第三节 管理层讨论与分析\n短" + \
               "第四节 公司治理" + ("y" * 1000)
        assert ff.slice_mdna_a(text) is None

    def test_no_heading_returns_none(self):
        assert ff.slice_mdna_a("没有任何章节标题" * 500) is None


_ANN_ROWS = [
    {"announcementTitle": "摩尔线程2025年年度报告摘要",
     "announcementTime": 1777219200000,
     "adjunctUrl": "finalpage/2026-04-27/ABS.PDF"},
    {"announcementTitle": "摩尔线程2025年年度报告",
     "announcementTime": 1777219200000,
     "adjunctUrl": "finalpage/2026-04-27/FULL.PDF"},
    {"announcementTitle": "摩尔线程2024年年度报告",
     "announcementTime": 1745654400000,
     "adjunctUrl": "finalpage/2025-04-27/OLD.PDF"},
]
_PROSP_ROWS = [
    {"announcementTitle": "首次公开发行股票并在科创板上市招股说明书提示性公告",
     "announcementTime": 1, "adjunctUrl": "p/NOTICE.PDF"},
    {"announcementTitle": "首次公开发行股票并在科创板上市招股说明书",
     "announcementTime": 2, "adjunctUrl": "p/FULL.PDF"},
]


@pytest.fixture
def cninfo_mock(monkeypatch):
    monkeypatch.setattr(ff, "_cn_orgid",
                        lambda code: ("9900063221", "摩尔线程"))

    def query(code, org_id, category="", searchkey="", max_pages=3):
        if category == ff.ANNUAL_CATEGORY:
            return _ANN_ROWS
        if searchkey == ff.PROSPECTUS_KEY:
            return _PROSP_ROWS
        return []
    monkeypatch.setattr(ff, "_cn_query", query)
    monkeypatch.setattr(ff, "_pdf_text",
                        lambda url: (_fake_annual_text(), 230))


def test_fetch_filings_a_structure(cninfo_mock):
    doc = ff.fetch_filings_a("688795")
    assert doc["id"] == "A:688795"
    kinds = [r["kind"] for r in doc["reports"]]
    assert kinds == ["annual", "annual", "prospectus"]
    a0 = doc["reports"][0]
    assert a0["title"] == "摩尔线程2025年年度报告"   # 摘要 excluded
    assert a0["url"].endswith("FULL.PDF")
    assert a0["mdna_sliced"] is True
    assert "经营讨论正文" in a0["mdna"]
    assert len(a0["text"]) > 4000
    assert doc["gaps"] == []


def test_fetch_filings_respects_limit(cninfo_mock, monkeypatch):
    monkeypatch.setattr(config, "FILINGS_MAX_REPORTS", 1)
    doc = ff.fetch_filings_a("688795")
    annuals = [r for r in doc["reports"] if r["kind"] == "annual"]
    assert len(annuals) == 1


def test_fetch_filings_fail_closed(monkeypatch):
    monkeypatch.setattr(ff, "_pypdf", lambda: None)
    assert ff.fetch_filings_a("688795") is None
    monkeypatch.setattr(ff, "_pypdf", lambda: object())
    monkeypatch.setattr(ff, "_cn_orgid", lambda code: None)
    assert ff.fetch_filings_a("688795") is None


def test_gather_filings_writes_subdir_and_index(tmp_path, monkeypatch,
                                                cninfo_mock):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "FILINGS_MAX_REPORTS", 1)
    path, gap = mg.gather_filings("A", "688795")
    assert gap is None
    index = json.loads(open(path, encoding="utf-8").read())
    assert len(index["reports"]) == 2            # 1 annual + prospectus
    a0 = index["reports"][0]
    assert a0["file"].startswith("filings/")
    assert "text" not in a0                       # full text not in index
    fdir = store.raw_dir("A", "688795") / "filings"
    full = (fdir / "annual_0.txt").read_text(encoding="utf-8")
    assert "经营讨论正文" in full
    mdna = (fdir / "annual_0_mdna.txt").read_text(encoding="utf-8")
    assert "公司治理" not in mdna
    assert (fdir / "prospectus.txt").exists()


def test_gather_filings_non_a_is_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    path, gap = mg.gather_filings("HK", "00700")
    assert path is None and "A-share only" in gap
