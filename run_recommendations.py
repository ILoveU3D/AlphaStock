"""Run tests + generate today's master-strategy recommendations.

Usage (from repo root):
    python run_recommendations.py

Environment note: dependencies (pandas/requests/pytest) are vendored in
libs/ as cp314 wheels, so any Python 3.14 works with PYTHONPATH=libs.
The .venv is an empty shell (no pandas installed) — never rely on it.

Writes:
    test_results.txt          — pytest output
    recommendations.txt       — per-master top picks
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
LIBS = ROOT / "libs"


def _env() -> dict:
    return {**os.environ, "PYTHONPATH": str(LIBS)}


def _probe(python: str) -> bool:
    """True if `python` can import the vendored deps (must be 3.14)."""
    try:
        r = subprocess.run(
            [python, "-c", "import pandas, requests, pytest"],
            cwd=ROOT, env=_env(), capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _find_python() -> str:
    """First candidate that can actually run the toolkit."""
    candidates = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),  # probed, not trusted
        sys.executable,
    ]
    for c in candidates:
        if Path(c).exists() and _probe(c):
            return c
    raise SystemExit(
        "No usable Python: need Python 3.14 (libs/ wheels are cp314) with "
        "pandas/requests/pytest importable via PYTHONPATH=libs")


PY = _find_python()


def run(cmd, label, timeout=600):
    print(f"\n=== {label} ===")
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=_env(),
                           capture_output=True, text=True, timeout=timeout)
        out = r.stdout + ("\n--- STDERR ---\n" + r.stderr if r.stderr else "")
        print(out[-2500:])
        return r.returncode, out
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT after {timeout}s]")
        return 1, f"[TIMEOUT after {timeout}s]"


def main():
    print(f"python  : {PY}")
    print(f"PYTHONPATH includes libs/ : {LIBS}")

    # 1) Tests
    rc, out = run([PY, "-B", "-m", "pytest", "tests", "-q", "--no-header"],
                  "PYTEST", timeout=600)
    (ROOT / "test_results.txt").write_text(out, encoding="utf-8")

    # 2) Strategy list (sanity)
    run([PY, "-B", "-m", "value_genie", "strategy", "list"],
        "STRATEGY LIST", timeout=60)

    # 3) Per-master screens
    masters = ["buffett", "duan", "sheng", "livermore"]
    all_out = []
    for m in masters:
        rc, out = run(
            [PY, "-B", "-m", "value_genie", "screen", "--strategy", m,
             "--top", "10"],
            f"SCREEN --strategy {m}", timeout=180)
        all_out.append(f"\n\n===== {m.upper()} =====\n{out}")

    # Also a balanced preset run for reference
    rc, out = run(
        [PY, "-B", "-m", "value_genie", "screen", "--strategy", "balanced",
         "--top", "10"],
        "SCREEN --strategy balanced", timeout=180)
    all_out.append(f"\n\n===== BALANCED (preset) =====\n{out}")

    (ROOT / "recommendations.txt").write_text(
        "".join(all_out), encoding="utf-8")
    print("\n\nDone. See test_results.txt and recommendations.txt")


if __name__ == "__main__":
    main()
