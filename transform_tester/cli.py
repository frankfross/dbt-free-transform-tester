"""Command line interface: ``tft run`` and ``tft init``.

``tft run`` discovers ``transform_tests/*.yaml`` in the project directory,
runs each test against an in-memory SQLite database, and prints one line
per test plus a summary. Exit code is 0 only when every test passes.

``tft init <dir>`` scaffolds a small example project so the workflow can
be tried in under a minute.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .assertions import format_rows
from .runner import run_all


def _templates_dir() -> Path:
    return Path(str(resources.files("transform_tester") / "templates"))


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.directory)
    if target.exists() and any(target.iterdir()):
        print(f"tft init: {target} already exists and is not empty", file=sys.stderr)
        return 1
    shutil.copytree(_templates_dir(), target)
    print(f"Created example project in {target}/")
    print("  cd {0} && python -m transform_tester.cli run".format(target))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    project_dir = Path(args.project)
    try:
        results = run_all(
            project_dir,
            transforms_dir=Path(args.transforms_dir) if args.transforms_dir else None,
            tests_dir=Path(args.tests_dir) if args.tests_dir else None,
            pattern=args.pattern,
        )
    except FileNotFoundError as exc:
        print(f"tft run: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"tft run: invalid test file: {exc}", file=sys.stderr)
        return 2

    passed = sum(1 for r in results if r.passed)
    for result in results:
        mark = "\u2713" if result.passed else "\u2717"
        print(f"{mark} {result.name}  ({result.path.name})")
        for failure in result.failures:
            print(f"    FAIL {failure}")
        if not result.passed and args.verbose:
            print("    result rows:")
            print(format_rows(result.rows))
    print(f"\n{passed} passed, {len(results) - passed} failed, {len(results)} total")
    return 0 if passed == len(results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tft",
        description="Test harness for SQL transform files — seed, run, assert. No dbt.",
    )
    parser.add_argument("--version", action="version", version=f"tft {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run all transform tests in a project")
    run.add_argument("project", nargs="?", default=".", help="project directory (default: .)")
    run.add_argument("--transforms-dir", help="override transforms directory")
    run.add_argument("--tests-dir", help="override transform-tests directory")
    run.add_argument("--pattern", help="only run tests whose name/transform contains this text")
    run.add_argument("--verbose", action="store_true", help="print result rows for failing tests")
    run.set_defaults(func=cmd_run)

    init = sub.add_parser("init", help="scaffold an example project")
    init.add_argument("directory", help="directory to create the example project in")
    init.set_defaults(func=cmd_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
