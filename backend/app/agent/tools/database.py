"""`query_database` tool: LLM-written SQL, executed safely.

Defense in depth — each layer alone would stop a destructive query:
  1. sqlglot allow-list: exactly one statement, and it must be a read query.
  2. The SQLite connection is opened read-only (`mode=ro`) with `query_only`.
  3. A progress handler aborts queries that run longer than the time budget.
  4. Results are capped at `row_limit` rows (fetchmany, so huge scans stop early).
"""

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

QUERY_TIMEOUT_S = 3.0
BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}

SCHEMA_DESCRIPTION = """\
SQLite database of Harbor & Pine Logistics operations. Dates are TEXT 'YYYY-MM-DD', times TEXT 'HH:MM' (facility local time).

warehouses(code PK e.g. 'CHI1', name, address, city, state, dock_count, hazmat_docks JSON array e.g. '[11, 12]', open_time, close_time, operating_days e.g. 'Mon-Sat')
carriers(code PK e.g. 'PRL', name, modes JSON array of 'PARCEL'|'LTL'|'FTL', zones JSON array of 'Z1'..'Z4', hazmat_certified 0/1, cargo_insurance_usd)
customers(id PK, name, industry, tier 'Gold'|'Silver'|'Standard', account_manager)
rate_cards(id, carrier_code FK, mode, zone, rate_per_lb, min_charge_usd)
dock_slots(id, warehouse_code FK, dock_no, is_hazmat_dock 0/1, slot_date, start_time, end_time, status 'available'|'booked'|'blocked', carrier_code FK NULL unless booked, note e.g. maintenance reason)
shipments(id PK e.g. 'SH-24123', customer_id FK, origin_warehouse FK, destination_city, destination_state, zone, carrier_code FK, mode, weight_lb, pallets, hazmat_class NULL|'3'|'8'|'9', un_number, ship_date, promised_date, delivered_date NULL until delivered, status 'scheduled'|'in_transit'|'delivered'|'delayed'|'exception', exception_note free text e.g. weather holds or damage, freight_cost_usd)
inventory(id, warehouse_code FK, sku, description, category, customer_id FK, qty_on_hand, qty_reserved, reorder_point, unit_weight_lb, hazmat_class, un_number, last_counted)

Notes: a shipment is on time when delivered_date <= promised_date. Dock slots exist only for days a facility is open (no rows = closed). Use explicit date literals from the system prompt, never date('now')."""


class SqlGuardError(ValueError):
    """The query was rejected before execution."""


@dataclass
class QueryResult:
    """Tool output. `str()` is what the LLM sees; the fields feed the trace UI."""

    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None
    duration_ms: int = 0

    def __str__(self) -> str:
        if self.error:
            return f"SQL error: {self.error}\nFix the query and try again."
        if not self.rows:
            return "Query returned 0 rows."
        header = " | ".join(self.columns)
        lines = [" | ".join("NULL" if v is None else str(v) for v in row) for row in self.rows]
        note = f"\n(showing first {len(self.rows)} rows; more exist)" if self.truncated else ""
        return f"{len(self.rows)} row(s):\n{header}\n" + "\n".join(lines) + note

    def to_ui(self) -> dict[str, Any]:
        return {
            "sql": self.sql,
            "columns": self.columns,
            "rows": self.rows[:20],
            "row_count": len(self.rows),
            "truncated": self.truncated,
            "error": self.error,
        }


def validate_sql(sql: str) -> str:
    """Returns the normalized query or raises SqlGuardError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise SqlGuardError(f"could not parse SQL ({e.errors[0]['description']})") from e
    if len(statements) != 1:
        raise SqlGuardError("exactly one SQL statement is allowed")
    stmt = statements[0]
    if not isinstance(stmt, exp.Query):
        raise SqlGuardError(f"only read-only SELECT queries are allowed, got {stmt.key.upper()}")
    for node in stmt.walk():
        if isinstance(node, exp.DML | exp.DDL | exp.Command):
            raise SqlGuardError("data-modifying statements are not allowed")
        if isinstance(node, exp.Func) and node.name.lower() in BLOCKED_FUNCTIONS:
            raise SqlGuardError(f"function {node.name} is not allowed")
    return stmt.sql(dialect="sqlite")


class OperationalDB:
    def __init__(self, db_path: Path, row_limit: int = 50):
        self.db_path = db_path
        self.row_limit = row_limit

    def _connect(self) -> sqlite3.Connection:
        # as_uri() percent-encodes spaces etc.; mode=ro makes the file handle read-only.
        conn = sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
        return conn

    def run(self, sql: str, row_limit: int | None = None) -> QueryResult:
        limit = row_limit or self.row_limit
        started = time.perf_counter()
        result = QueryResult(sql=sql.strip())
        try:
            safe_sql = validate_sql(sql)
            with closing(self._connect()) as conn:
                deadline = time.monotonic() + QUERY_TIMEOUT_S
                # Called every 10k VM instructions; a truthy return aborts the query.
                conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
                cursor = conn.execute(safe_sql)
                result.columns = [d[0] for d in cursor.description or []]
                rows = cursor.fetchmany(limit + 1)
                result.truncated = len(rows) > limit
                result.rows = [list(r) for r in rows[:limit]]
        except SqlGuardError as e:
            result.error = f"Rejected: {e}."
        except sqlite3.OperationalError as e:
            msg = str(e)
            result.error = "query timed out" if "interrupted" in msg else msg
        except sqlite3.Error as e:
            result.error = str(e)
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    def scalar(self, sql: str) -> Any:
        with closing(self._connect()) as conn:
            row = conn.execute(sql).fetchone()
            return row[0] if row else None
