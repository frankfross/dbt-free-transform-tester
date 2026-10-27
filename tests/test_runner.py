"""Tests for the runner: seeding, transforms, ref(), and failure reporting."""

from pathlib import Path

import pytest
import yaml

from transform_tester.runner import (
    discover_tests,
    load_config,
    materialize_transform,
    run_all,
    run_test,
    seed_database,
)
from transform_tester.runner import TransformTest
import sqlite3


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "transforms").mkdir()
    (tmp_path / "transform_tests").mkdir()
    (tmp_path / "transforms" / "totals.sql").write_text(
        "SELECT customer_id, SUM(amount) AS total FROM orders GROUP BY customer_id"
    )
    (tmp_path / "transform_tests" / "totals.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "totals per customer",
                "transform": "totals",
                "seeds": {
                    "orders": [
                        {"customer_id": 1, "amount": 10},
                        {"customer_id": 1, "amount": 5},
                        {"customer_id": 2, "amount": 7},
                    ]
                },
                "assert": [
                    {"row_count": 2},
                    {
                        "equals": [
                            {"customer_id": 1, "total": 15},
                            {"customer_id": 2, "total": 7},
                        ]
                    },
                ],
            }
        )
    )
    return tmp_path


def test_run_all_passes_on_fixture_project(project):
    results = run_all(project)
    assert len(results) == 1
    assert results[0].passed
    assert results[0].rows == [
        {"customer_id": 1, "total": 15},
        {"customer_id": 2, "total": 7},
    ]


def test_run_all_pattern_filter(project):
    assert run_all(project, pattern="totals")
    assert run_all(project, pattern="no-such-test") == []


def test_failing_assertion_reports_the_difference(project):
    test = discover_tests(project / "transform_tests")[0]
    test.assertions = [{"equals": [{"customer_id": 1, "total": 999}]}]
    result = run_test(test, project / "transforms", project)
    assert not result.passed
    assert any("missing expected row" in f for f in result.failures)
    assert any("unexpected extra row" in f for f in result.failures)


def test_missing_transform_is_a_failure_not_a_crash(project):
    test = TransformTest(
        name="ghost", transform="does_not_exist", seeds={}, assertions=[],
        path=project / "transform_tests" / "totals.yaml",
    )
    result = run_test(test, project / "transforms", project)
    assert not result.passed
    assert result.failures[0].startswith("setup failed: transform not found")


def test_csv_seed(tmp_path):
    (tmp_path / "transforms").mkdir()
    (tmp_path / "seeds").mkdir()
    (tmp_path / "transforms" / "t.sql").write_text("SELECT COUNT(*) AS n FROM items")
    (tmp_path / "seeds" / "items.csv").write_text("id,price\n1,9.99\n2,5\n3,\n")
    conn = sqlite3.connect(":memory:")
    seed_database(conn, {"items": "seeds/items.csv"}, tmp_path)
    rows = conn.execute("SELECT id, price FROM items ORDER BY id").fetchall()
    # int/float inference per value; empty string becomes NULL
    assert rows == [(1, 9.99), (2, 5), (3, None)]
    conn.close()


def test_missing_seed_file_is_a_failure(tmp_path):
    test = TransformTest(
        name="bad seed", transform="t", seeds={"items": "seeds/nope.csv"},
        assertions=[], path=tmp_path / "x.yaml",
    )
    result = run_test(test, tmp_path / "transforms", tmp_path)
    assert not result.passed
    assert "seed file not found" in result.failures[0]


def test_ref_chain_materializes_dependencies(tmp_path):
    (tmp_path / "transforms").mkdir()
    (tmp_path / "transforms" / "base.sql").write_text(
        "SELECT 1 AS a UNION ALL SELECT 2"
    )
    (tmp_path / "transforms" / "derived.sql").write_text(
        'SELECT a * 10 AS b FROM {{ ref("base") }}'
    )
    conn = sqlite3.connect(":memory:")
    materialize_transform(conn, tmp_path / "transforms", "derived")
    rows = conn.execute("SELECT b FROM derived ORDER BY b").fetchall()
    assert rows == [(10,), (20,)]
    conn.close()


def test_ref_cycle_is_an_error(tmp_path):
    (tmp_path / "transforms").mkdir()
    (tmp_path / "transforms" / "a.sql").write_text('SELECT * FROM {{ ref("b") }}')
    (tmp_path / "transforms" / "b.sql").write_text('SELECT * FROM {{ ref("a") }}')
    conn = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="circular ref"):
        materialize_transform(conn, tmp_path / "transforms", "a")
    conn.close()


def test_load_config_defaults_and_file(tmp_path):
    assert load_config(tmp_path) == {
        "transforms_dir": "transforms",
        "tests_dir": "transform_tests",
    }
    (tmp_path / "tft.yaml").write_text("transforms_dir: sql\ntests_dir: checks\n")
    assert load_config(tmp_path) == {
        "transforms_dir": "sql",
        "tests_dir": "checks",
    }


def test_discover_tests_accepts_a_list_in_one_file(tmp_path):
    (tmp_path / "transform_tests").mkdir()
    (tmp_path / "transform_tests" / "two.yaml").write_text(
        yaml.safe_dump(
            [
                {"name": "one", "transform": "a", "assert": [{"row_count": 0}]},
                {"name": "two", "transform": "b", "assert": [{"row_count": 0}]},
            ]
        )
    )
    tests = discover_tests(tmp_path / "transform_tests")
    assert [t.name for t in tests] == ["one", "two"]


def test_discover_tests_rejects_test_without_transform(tmp_path):
    (tmp_path / "transform_tests").mkdir()
    (tmp_path / "transform_tests" / "bad.yaml").write_text(
        yaml.safe_dump({"name": "no transform here"})
    )
    with pytest.raises(ValueError, match="at least a 'transform' key"):
        discover_tests(tmp_path / "transform_tests")
