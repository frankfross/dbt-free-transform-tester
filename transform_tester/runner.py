"""Core runner: load test YAML, seed SQLite, run transforms, assert results.

Project layout (defaults, overridable via ``tft.yaml`` or CLI flags)::

    transforms/        one .sql file per transform (a single SELECT)
    transform_tests/   one .yaml file per test (or several tests per file)
    seeds/             optional .csv seed files, referenced by name

A transform may reference another transform with ``{{ ref("name") }}``;
referenced transforms are run first and materialized as temporary tables,
so transforms can be layered exactly like a dbt model graph — without dbt.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .assertions import run_assertions

REF_RE = re.compile(r"""\{\{\s*ref\(\s*["']([^"']+)["']\s*\)\s*\}\}""")


@dataclass
class TestResult:
    name: str
    path: Path
    passed: bool
    failures: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass
class TransformTest:
    name: str
    transform: str
    seeds: dict[str, Any]
    assertions: list
    path: Path


def load_config(project_dir: Path) -> dict:
    """Read ``tft.yaml`` if present, else fall back to the defaults."""
    config_path = project_dir / "tft.yaml"
    if not config_path.exists():
        return {"transforms_dir": "transforms", "tests_dir": "transform_tests"}
    with config_path.open() as fh:
        data = yaml.safe_load(fh) or {}
    return {
        "transforms_dir": data.get("transforms_dir", "transforms"),
        "tests_dir": data.get("tests_dir", "transform_tests"),
    }


def discover_tests(tests_dir: Path) -> list[TransformTest]:
    """Load every ``*.yaml``/``*.yml`` file under ``tests_dir``.

    A file may hold a single test mapping or a list of test mappings.
    """
    tests: list[TransformTest] = []
    for path in sorted(tests_dir.glob("*.y*ml")):
        with path.open() as fh:
            data = yaml.safe_load(fh)
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict) or "transform" not in item:
                raise ValueError(
                    f"{path}: every test needs at least a 'transform' key; got {item!r}"
                )
            tests.append(
                TransformTest(
                    name=item.get("name", f"{item['transform']} ({path.name})"),
                    transform=str(item["transform"]),
                    seeds=item.get("seeds", {}) or {},
                    assertions=item.get("assert", []) or [],
                    path=path,
                )
            )
    return tests


def _infer_value(raw: str) -> Any:
    """Best-effort type inference for CSV seed values."""
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _create_seed_table(conn: sqlite3.Connection, name: str, rows: list[dict]) -> None:
    """Create a seed table from a list of row dicts (columns = union of keys).

    Columns are created without a declared type so values keep the Python
    type they were given (int stays int, float stays float) — SQLite's
    typeless columns preserve that exactly.
    """
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    quoted = ", ".join(f'"{c}"' for c in columns)
    conn.execute(f'CREATE TABLE "{name}" ({quoted})')
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f'INSERT INTO "{name}" ({quoted}) VALUES ({placeholders})',
        [tuple(row.get(c) for c in columns) for row in rows],
    )


def _load_csv_seed(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return [{k: _infer_value(v) for k, v in row.items()} for row in csv.DictReader(fh)]


def seed_database(conn: sqlite3.Connection, seeds: dict, base_dir: Path) -> None:
    """Create one table per seed.

    A seed value is either an inline list of row mappings, or a string
    naming a ``.csv`` file (resolved relative to the test file's directory,
    then relative to the project root).
    """
    for table, spec in seeds.items():
        if isinstance(spec, str):
            for candidate in (base_dir / spec, Path.cwd() / spec):
                if candidate.exists():
                    rows = _load_csv_seed(candidate)
                    break
            else:
                raise FileNotFoundError(f"seed file not found: {spec}")
        elif isinstance(spec, list):
            rows = [dict(r) for r in spec]
        else:
            raise ValueError(f"seed {table!r}: expected a list of rows or a .csv path, got {spec!r}")
        _create_seed_table(conn, table, rows)


def read_transform(transforms_dir: Path, name: str) -> str:
    path = transforms_dir / f"{name}.sql"
    if not path.exists():
        raise FileNotFoundError(f"transform not found: {path}")
    return path.read_text().strip().rstrip(";").strip()


def materialize_transform(
    conn: sqlite3.Connection,
    transforms_dir: Path,
    name: str,
    done: set[str] | None = None,
    stack: list[str] | None = None,
) -> None:
    """Run a transform (and its ``ref()`` dependencies) into a temp table.

    Each transform is materialized once per test run, as a temporary table
    named after the transform. Circular references are an error, reported
    with the full cycle.
    """
    done = set() if done is None else done
    stack = [] if stack is None else stack
    if name in done:
        return
    if name in stack:
        cycle = " -> ".join(stack + [name])
        raise ValueError(f"circular ref() dependency: {cycle}")
    stack.append(name)
    sql = read_transform(transforms_dir, name)
    for ref_name in REF_RE.findall(sql):
        materialize_transform(conn, transforms_dir, ref_name, done, stack)
    sql = REF_RE.sub(lambda m: f'"{m.group(1)}"', sql)
    conn.execute(f'CREATE TEMP TABLE "{name}" AS {sql}')
    stack.pop()
    done.add(name)


def run_test(
    test: TransformTest, transforms_dir: Path, project_dir: Path
) -> TestResult:
    """Run one test in a fresh in-memory database; never raises on bad tests.

    Setup errors (missing transform, bad seed file, circular ref) are
    reported as test failures with the message, so one broken test file
    cannot abort the whole suite.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        seed_database(conn, test.seeds, test.path.parent)
        materialize_transform(conn, transforms_dir, test.transform)
        conn.execute('CREATE TEMP TABLE "result" AS SELECT * FROM '
                     f'"{test.transform}"')
        rows = [dict(r) for r in conn.execute('SELECT * FROM "result"')]
        failures = run_assertions(rows, test.assertions, conn)
        return TestResult(
            name=test.name, path=test.path, passed=not failures,
            failures=failures, rows=rows,
        )
    except Exception as exc:  # noqa: BLE001 - test setup errors become failures
        return TestResult(
            name=test.name, path=test.path, passed=False,
            failures=[f"setup failed: {exc}"],
        )
    finally:
        conn.close()


def run_all(
    project_dir: Path,
    transforms_dir: Path | None = None,
    tests_dir: Path | None = None,
    pattern: str | None = None,
) -> list[TestResult]:
    """Discover and run every test in a project (optionally name-filtered)."""
    config = load_config(project_dir)
    transforms = transforms_dir or project_dir / config["transforms_dir"]
    tests = tests_dir or project_dir / config["tests_dir"]
    if not tests.exists():
        raise FileNotFoundError(f"tests directory not found: {tests}")
    results = []
    for test in discover_tests(tests):
        if pattern and pattern not in test.name and pattern not in test.transform:
            continue
        results.append(run_test(test, transforms, project_dir))
    return results
