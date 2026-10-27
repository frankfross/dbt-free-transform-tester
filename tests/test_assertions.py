"""Tests for the assertion helpers (no database needed)."""

import sqlite3

from transform_tester.assertions import (
    assert_column_values,
    assert_equals,
    assert_equals_ordered,
    assert_not_null,
    assert_row_count,
    assert_unique,
    rows_match,
    run_assertions,
    values_equal,
)


def test_values_equal_plain_numbers():
    assert values_equal(5, 5.0)
    assert values_equal(5, 6) is False
    assert values_equal("a", "a")
    assert values_equal("a", "b") is False
    assert values_equal(None, None)
    assert values_equal(None, 0) is False


def test_values_equal_approx():
    assert values_equal({"approx": 24.98, "tol": 0.01}, 24.9800001)
    assert values_equal({"approx": 24.98, "tol": 0.01}, 25.0) is False
    assert values_equal({"approx": 24.98}, 24.98)  # default tolerance
    assert values_equal({"approx": 24.98}, "24.98") is False


def test_rows_match_order_insensitive():
    expected = [{"a": 1}, {"a": 2}]
    actual = [{"a": 2}, {"a": 1}]
    assert rows_match(expected, actual) == ([], [])


def test_rows_match_reports_missing_and_extra():
    missing, extra = rows_match([{"a": 1}, {"a": 2}], [{"a": 2}, {"a": 3}])
    assert missing == [{"a": 1}]
    assert extra == [{"a": 3}]


def test_rows_match_duplicates_matched_one_for_one():
    missing, extra = rows_match([{"a": 1}, {"a": 1}], [{"a": 1}])
    assert missing == [{"a": 1}]
    assert extra == []


def test_assert_equals_and_row_count():
    rows = [{"a": 1}, {"a": 2}]
    assert assert_equals(rows, [{"a": 2}, {"a": 1}]) == []
    assert assert_row_count(rows, 2) == []
    assert assert_row_count(rows, 3) == ["row_count: expected 3 rows, got 2"]
    failures = assert_equals(rows, [{"a": 1}, {"a": 9}])
    assert any("missing expected row {'a': 9}" in f for f in failures)
    assert any("unexpected extra row {'a': 2}" in f for f in failures)


def test_assert_equals_ordered_catches_swapped_rows():
    rows = [{"a": 2}, {"a": 1}]
    assert assert_equals_ordered(rows, [{"a": 1}, {"a": 2}])
    assert assert_equals_ordered(rows, [{"a": 2}, {"a": 1}]) == []


def test_assert_column_values():
    rows = [{"c": "x"}, {"c": "y"}, {"c": "x"}]
    assert assert_column_values(rows, {"c": ["x", "y"]}) == []
    assert assert_column_values(rows, {"c": ["x"]})


def test_assert_not_null_and_unique():
    rows = [{"id": 1, "v": "a"}, {"id": 2, "v": None}, {"id": 1, "v": "c"}]
    assert assert_not_null(rows, ["id"]) == []
    assert assert_not_null(rows, ["v"])
    assert assert_unique(rows, ["v"]) == []
    assert assert_unique(rows, ["id"])


def _conn_with_result():
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE "result" (a INTEGER, b TEXT)')
    conn.executemany('INSERT INTO "result" VALUES (?, ?)', [(1, "x"), (2, "y")])
    return conn


def test_run_assertions_sql_must_return_zero_rows():
    conn = _conn_with_result()
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    assert run_assertions(rows, [{"sql": "SELECT a FROM result WHERE a < 0"}], conn) == []
    failures = run_assertions(rows, [{"sql": "SELECT a FROM result WHERE a = 2"}], conn)
    assert len(failures) == 1 and "1 violating row" in failures[0]
    conn.close()


def test_run_assertions_unknown_and_malformed():
    conn = _conn_with_result()
    failures = run_assertions([{"a": 1}], [{"nope": 1}, "not-a-mapping"], conn)
    assert any("unknown assertion type: 'nope'" in f for f in failures)
    assert any("malformed assertion" in f for f in failures)
    conn.close()


def test_run_assertions_sql_error_is_a_failure_not_a_crash():
    conn = _conn_with_result()
    failures = run_assertions([{"a": 1}], [{"sql": "SELECT nope FROM result"}], conn)
    assert failures and "failed to run" in failures[0]
    conn.close()
