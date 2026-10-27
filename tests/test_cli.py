"""Tests for the CLI: init scaffolding, run exit codes, and filters."""

import filecmp
import subprocess
import sys
from pathlib import Path

from transform_tester.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "transform_tester.cli", *args],
        capture_output=True, text=True, cwd=cwd or REPO_ROOT,
    )


def test_examples_pass():
    result = run_cli("run", "examples")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed, 0 failed, 2 total" in result.stdout


def test_run_failing_project_exits_1(tmp_path):
    (tmp_path / "transforms").mkdir()
    (tmp_path / "transform_tests").mkdir()
    (tmp_path / "transforms" / "t.sql").write_text("SELECT 1 AS a")
    (tmp_path / "transform_tests" / "t.yaml").write_text(
        "name: wrong expectation\ntransform: t\nassert:\n  - row_count: 5\n"
    )
    result = run_cli("run", str(tmp_path))
    assert result.returncode == 1
    assert "row_count: expected 5 rows, got 1" in result.stdout
    assert "0 passed, 1 failed, 1 total" in result.stdout


def test_run_missing_tests_dir_exits_2(tmp_path):
    result = run_cli("run", str(tmp_path))
    assert result.returncode == 2
    assert "tests directory not found" in result.stderr


def test_run_pattern_filters(tmp_path):
    (tmp_path / "transforms").mkdir()
    (tmp_path / "transform_tests").mkdir()
    (tmp_path / "transforms" / "t.sql").write_text("SELECT 1 AS a")
    (tmp_path / "transform_tests" / "a.yaml").write_text(
        "name: alpha\ntransform: t\nassert: []\n"
    )
    (tmp_path / "transform_tests" / "b.yaml").write_text(
        "name: beta\ntransform: t\nassert:\n  - row_count: 9\n"
    )
    result = run_cli("run", str(tmp_path), "--pattern", "alpha")
    assert result.returncode == 0
    assert "1 passed, 0 failed, 1 total" in result.stdout


def test_init_scaffolds_a_working_project(tmp_path):
    target = tmp_path / "my-project"
    assert main(["init", str(target)]) == 0
    assert (target / "tft.yaml").exists()
    assert (target / "transforms" / "order_totals.sql").exists()
    result = run_cli("run", str(target))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed, 0 failed, 2 total" in result.stdout


def test_init_refuses_non_empty_directory(tmp_path):
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "file.txt").write_text("x")
    assert main(["init", str(tmp_path / "busy")]) == 1


def test_init_output_matches_examples():
    """The repo's examples/ must stay identical to what `tft init` creates,
    so the README quickstart and the scaffold never drift apart."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "scaffold"
        assert main(["init", str(target)]) == 0
        examples = REPO_ROOT / "examples"
        for rel in ("tft.yaml", "transforms/order_totals.sql",
                    "transforms/customer_summary.sql", "seeds/orders.csv",
                    "seeds/order_lines.csv",
                    "transform_tests/order_totals.yaml",
                    "transform_tests/customer_summary.yaml"):
            assert filecmp.cmp(examples / rel, target / rel, shallow=False), rel
