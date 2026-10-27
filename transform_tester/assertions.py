"""Assertion helpers: compare a transform's result rows against expectations.

Every assertion returns a list of failure strings (empty = passed), so the
runner can report all failures of a test at once instead of stopping at
the first one.
"""

from __future__ import annotations

from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def values_equal(expected: Any, actual: Any, tol: float = 1e-9) -> bool:
    """Tolerant equality for a single expected/actual value pair.

    ``{"approx": x, "tol": t}`` in an expected row matches any number within
    ``t`` of ``x``. Plain numbers compare numerically (``5 == 5.0``), so an
    integer expectation still matches a float result. Everything else
    compares with plain ``==``.
    """
    if isinstance(expected, dict) and set(expected) == {"approx", "tol"}:
        return _is_number(actual) and abs(float(actual) - float(expected["approx"])) <= float(expected["tol"])
    if isinstance(expected, dict) and set(expected) == {"approx"}:
        return _is_number(actual) and abs(float(actual) - float(expected["approx"])) <= tol
    if _is_number(expected) and _is_number(actual):
        return abs(float(expected) - float(actual)) <= tol
    return expected == actual


def rows_match(expected: list[dict], actual: list[dict], tol: float = 1e-9) -> tuple[list[dict], list[dict]]:
    """Match expected rows against actual rows (order-insensitive).

    Returns ``(missing, extra)``: expected rows with no match in the
    result, and result rows with no match in the expectations. Matching is
    greedy but exact for distinct rows; duplicate rows are matched one
    for one, so a duplicated row in either side is reported.
    """
    remaining = list(actual)
    missing: list[dict] = []
    for exp_row in expected:
        match_idx = None
        for i, act_row in enumerate(remaining):
            if set(exp_row) != set(act_row):
                continue
            if all(values_equal(exp_row[k], act_row[k], tol) for k in exp_row):
                match_idx = i
                break
        if match_idx is None:
            missing.append(exp_row)
        else:
            remaining.pop(match_idx)
    return missing, remaining


def assert_row_count(rows: list[dict], expected: int) -> list[str]:
    if len(rows) != expected:
        return [f"row_count: expected {expected} rows, got {len(rows)}"]
    return []


def assert_equals(rows: list[dict], expected: list[dict], tol: float = 1e-9) -> list[str]:
    missing, extra = rows_match(expected, rows, tol)
    failures: list[str] = []
    for row in missing:
        failures.append(f"equals: missing expected row {row}")
    for row in extra:
        failures.append(f"equals: unexpected extra row {row}")
    return failures


def assert_equals_ordered(rows: list[dict], expected: list[dict], tol: float = 1e-9) -> list[str]:
    failures: list[str] = []
    if len(rows) != len(expected):
        failures.append(
            f"equals_ordered: expected {len(expected)} rows, got {len(rows)}"
        )
        return failures
    for i, (exp_row, act_row) in enumerate(zip(expected, rows)):
        if set(exp_row) != set(act_row) or not all(
            values_equal(exp_row[k], act_row[k], tol) for k in exp_row
        ):
            failures.append(f"equals_ordered: row {i} differs — expected {exp_row}, got {act_row}")
    return failures


def assert_column_values(rows: list[dict], expected: dict[str, list]) -> list[str]:
    failures: list[str] = []
    for column, values in expected.items():
        actual_values = sorted({row.get(column) for row in rows}, key=repr)
        if sorted(values, key=repr) != actual_values:
            failures.append(
                f"column_values: column {column!r} expected distinct values "
                f"{sorted(values, key=repr)}, got {actual_values}"
            )
    return failures


def assert_not_null(rows: list[dict], columns: list[str]) -> list[str]:
    failures: list[str] = []
    for column in columns:
        bad = [i for i, row in enumerate(rows) if row.get(column) is None]
        if bad:
            failures.append(
                f"not_null: column {column!r} is NULL in {len(bad)} row(s) "
                f"(first at result index {bad[0]})"
            )
    return failures


def assert_unique(rows: list[dict], columns: list[str]) -> list[str]:
    failures: list[str] = []
    seen: dict[tuple, int] = {}
    for i, row in enumerate(rows):
        key = tuple(row.get(c) for c in columns)
        if key in seen:
            failures.append(
                f"unique: columns {columns} duplicate value {key} "
                f"(rows {seen[key]} and {i})"
            )
            break
        seen[key] = i
    return failures


def run_assertions(rows: list[dict], assertions: list, conn) -> list[str]:
    """Run a test's ``assert:`` list against the transform result rows.

    ``conn`` is the SQLite connection (result is materialized as the
    ``result`` table) so ``sql:`` assertions can query it directly.
    Unknown assertion keys are reported as failures, not ignored — a
    typo in a test file should fail loudly, never pass silently.
    """
    failures: list[str] = []
    for assertion in assertions or []:
        if not isinstance(assertion, dict) or len(assertion) != 1:
            failures.append(f"malformed assertion (expected a single-key mapping): {assertion!r}")
            continue
        kind, spec = next(iter(assertion.items()))
        if kind == "row_count":
            failures += assert_row_count(rows, int(spec))
        elif kind == "equals":
            failures += assert_equals(rows, list(spec))
        elif kind == "equals_ordered":
            failures += assert_equals_ordered(rows, list(spec))
        elif kind == "column_values":
            failures += assert_column_values(rows, dict(spec))
        elif kind == "not_null":
            failures += assert_not_null(rows, list(spec))
        elif kind == "unique":
            failures += assert_unique(rows, list(spec))
        elif kind == "sql":
            # Custom assertion query: must return zero rows. The transform
            # result is available as the `result` table; seed tables too.
            try:
                cursor = conn.execute(str(spec))
                bad = cursor.fetchall()
                columns = [d[0] for d in cursor.description]
            except Exception as exc:  # noqa: BLE001 - surfaced as a test failure
                failures.append(f"sql: assertion query failed to run: {exc}")
                continue
            if bad:
                failures.append(
                    f"sql: assertion query returned {len(bad)} violating row(s) "
                    f"(first: {dict(zip(columns, bad[0]))})"
                )
        else:
            failures.append(f"unknown assertion type: {kind!r}")
    return failures


def format_rows(rows: list[dict]) -> str:
    """Render rows one per line for failure output."""
    if not rows:
        return "  (no rows)"
    return "\n".join(f"  {row}" for row in rows)
