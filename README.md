# dbt-free-transform-tester

A small test harness for SQL transform files — seed, run, assert. No dbt,
no warehouse, no server, no YAML-to-SQL compiler pretending to be a
framework.

You write plain SQL transforms (one `SELECT` per file), describe the input
data and the expected output in a YAML test file, and `tft` runs the whole
thing against an in-memory SQLite database and tells you what doesn't
match. It exists for the case dbt is the wrong tool: a handful of
transforms, a repo you own end to end, and tests you can run in under a
second without provisioning anything.

- **Seed tables inline or from CSV** — write rows in the test YAML, or
  point at a `.csv` file under `seeds/`.
- **Layered transforms with `{{ ref("name") }}`** — a transform can read
  another transform's output; dependencies run first and are materialized
  as temporary tables. Circular references are an error, with the cycle
  named.
- **Assertions that say what went wrong** — exact-row matching (order
  insensitive, with float tolerance and `{"approx": x, "tol": t}` values),
  `row_count`, `column_values`, `not_null`, `unique`, ordered matching,
  and custom `sql:` assertions that must return zero rows (the transform
  result is available as the `result` table).
- **Broken tests fail, they don't crash the run** — a missing transform,
  a bad seed file, or a circular ref is reported as a test failure with
  the message, so one bad file can't abort the suite.
- **Exit code 0 only when every test passes** — safe to wire into CI.

## Quickstart

```bash
pip install -r requirements.txt
python -m transform_tester.cli init my-transforms
cd my-transforms
python -m transform_tester.cli run
```

Example output:

```
✓ customer_summary rolls completed orders up to lifetime value  (customer_summary.yaml)
✓ order_totals sums completed orders only  (order_totals.yaml)

2 passed, 0 failed, 2 total
```

The scaffolded project has two transforms (`order_totals`,
`customer_summary` — the second one built on the first via `ref()`),
CSV seeds, and one test file per transform. The same project also lives
in `examples/` in this repo.

## Project layout

```
transforms/          one .sql file per transform (a single SELECT)
transform_tests/     one .yaml file per test (or several tests per file)
seeds/               optional .csv seed files
tft.yaml             optional: override the two directory names
```

## Writing a test

```yaml
name: order_totals sums completed orders only
transform: order_totals
seeds:
  orders: ../seeds/orders.csv          # or inline rows:
  order_lines:                         #   - {order_id: 1, sku: 'A100', qty: 2, unit_price: 9.99}
    - {order_id: 1, sku: 'A100', qty: 2, unit_price: 9.99}
    - {order_id: 1, sku: 'B200', qty: 1, unit_price: 5.00}
assert:
  - row_count: 1
  - equals:
      - {order_id: 1, customer_id: 10, total: 24.98, line_count: 2}
  - not_null: [order_id, customer_id, total]
  - unique: [order_id]
  # Custom SQL assertion — must return zero rows. The transform result
  # is available as the `result` table; seed tables are available too.
  - sql: "SELECT order_id FROM result WHERE total <= 0"
```

Notes on matching:

- `equals` is order-insensitive and matches rows one-for-one, so a
  duplicated row in either side is reported. Use `equals_ordered` when
  row order is part of the contract.
- Numbers compare numerically (`5` matches `5.0`). Float sums are
  rarely bit-exact, so use `{"approx": 24.98, "tol": 0.01}` for money
  instead of exact equality.
- Unknown assertion keys fail the test loudly — a typo in a test file
  should never pass silently.

## Layered transforms

```sql
-- transforms/customer_summary.sql
SELECT
    customer_id,
    COUNT(*) AS completed_orders,
    SUM(total) AS lifetime_value
FROM {{ ref("order_totals") }}
GROUP BY customer_id
```

`order_totals` runs first and is materialized as a temporary table, then
`customer_summary` reads from it. The dependency graph is resolved
recursively; a cycle fails with the full chain named.

## What a failure looks like

Change an expectation to something wrong and run again:

```
✓ customer_summary rolls completed orders up to lifetime value  (customer_summary.yaml)
✗ order_totals sums completed orders only  (order_totals.yaml)
    FAIL equals: missing expected row {'order_id': 1, 'customer_id': 10, 'total': 999.99, 'line_count': 2}
    FAIL equals: unexpected extra row {'order_id': 1, 'customer_id': 10, 'total': 24.98, 'line_count': 2}
    result rows:
  {'order_id': 1, 'customer_id': 10, 'total': 24.98, 'line_count': 2}
  {'order_id': 2, 'customer_id': 10, 'total': 14.97, 'line_count': 1}

1 passed, 1 failed, 2 total
```

`--verbose` prints the result rows for failing tests; without it you get
just the failures.

## CLI reference

```
tft run [project] [--transforms-dir DIR] [--tests-dir DIR]
        [--pattern TEXT] [--verbose]
    Run all transform tests in a project (default: current directory).
    --pattern runs only tests whose name or transform contains the text.

tft init <directory>
    Scaffold an example project in a new directory.
```

## Design notes

- **SQLite, in memory, one database per test.** Tests are isolated from
  each other by construction, and nothing is written to disk. The SQL
  dialect is SQLite's — the harness tests transform *logic*, not
  warehouse-specific functions. If a transform uses a function SQLite
  doesn't have, that shows up immediately as a setup failure, which is
  the honest place for it to show up.
- **Seed tables are typeless.** Columns are created without a declared
  type so values keep the Python type they were given (an `int` seed
  stays an `int` in the result). CSV seeds infer `int`/`float`/string
  per value; an empty CSV cell becomes `NULL`.
- **No test framework is smuggled in.** Assertions are data (a YAML
  list), not code — a non-engineer can read and edit a test file, and a
  test file can be reviewed in a PR like any other config.
- **What this is not:** a replacement for dbt on a real warehouse, a
  data-quality monitor, or a migration tool. It covers the small end —
  a repo of SQL transforms with tests that run anywhere — and stops
  there on purpose.

## Running the tool's own tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -q
```
