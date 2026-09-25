"""Tests for value_genie.atomic (crash-safe snapshot writes)."""

from pathlib import Path

import pandas as pd
import pytest

from value_genie.atomic import atomic_to_csv, atomic_write_text


class TestAtomicToCsv:
    def test_roundtrip(self, tmp_path):
        df = pd.DataFrame({"code": ["600519", "000858"],
                           "price": [1500.0, 130.0]})
        p = tmp_path / "sub" / "m.csv"
        atomic_to_csv(df, p)
        out = pd.read_csv(p, dtype={"code": str})
        assert list(out["code"]) == ["600519", "000858"]
        assert out["price"].tolist() == [1500.0, 130.0]

    def test_no_tmp_leftover_on_success(self, tmp_path):
        p = tmp_path / "m.csv"
        atomic_to_csv(pd.DataFrame({"a": [1]}), p)
        assert list(tmp_path.glob("m.csv.*.tmp")) == []

    def test_failed_write_preserves_existing_file(self, tmp_path,
                                                  monkeypatch):
        """A crash mid-write must leave the previous complete file
        untouched (never a truncated CSV the resume logic would reuse)."""
        p = tmp_path / "m.csv"
        p.write_text("code,price\n600519,1500\n", encoding="utf-8")

        def boom(self, *a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(pd.DataFrame, "to_csv", boom)
        with pytest.raises(OSError):
            atomic_to_csv(pd.DataFrame({"a": [1]}), p)
        assert p.read_text(encoding="utf-8") == "code,price\n600519,1500\n"
        assert list(tmp_path.glob("m.csv.*.tmp")) == []


class TestAtomicWriteText:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "sub" / "m.json"
        atomic_write_text(p, '{"a": 1}')
        assert p.read_text(encoding="utf-8") == '{"a": 1}'

    def test_failed_write_preserves_existing_file(self, tmp_path,
                                                  monkeypatch):
        p = tmp_path / "m.json"
        p.write_text("old", encoding="utf-8")

        def boom(self, *a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", boom)
        with pytest.raises(OSError):
            atomic_write_text(p, "new")
        assert p.read_text(encoding="utf-8") == "old"
        assert list(tmp_path.glob("m.json.*.tmp")) == []
