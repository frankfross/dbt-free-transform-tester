"""dbt-free-transform-tester: a small test harness for SQL transform files.

Seed tables, run a transform (a plain SELECT, optionally referencing other
transforms via ``{{ ref("name") }}``), and assert on the result — all on an
in-memory SQLite database. No dbt, no warehouse, no server.
"""

__version__ = "0.1.0"
