"""Atomic file writes: a crash mid-write must never leave a truncated
dataset that the snapshot resume logic would mistake for a complete one.
"""

import os
from pathlib import Path

import pandas as pd


def _tmp_path(path: Path) -> Path:
    # pid in the name: two concurrent processes never truncate each
    # other's tmp file
    return path.with_name(f"{path.name}.{os.getpid()}.tmp")


def atomic_to_csv(df: pd.DataFrame, path) -> None:
    """Write a CSV via tmp+os.replace; the target is always complete."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Write text via tmp+os.replace; the target is always complete."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
