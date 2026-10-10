"""The seeded database must (1) agree with facts.yaml — the documents are rendered
from the same file, so a mismatch would make the agent contradict its own policies —
(2) be relative to "today", (3) be deterministic, and (4) contain the planted demo
scenarios the example questions rely on."""

import json
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.data import seed
from app.data.seed import build_database, ensure_fresh, seeded_on
from app.domain import pricing
from tests.conftest import TODAY


@pytest.fixture(scope="module")
def conn(db_path: Path):
    with closing(sqlite3.connect(db_path)) as c:
        c.row_factory = sqlite3.Row
        yield c


def rows(conn: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    return conn.execute(sql).fetchall()


def days(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


# --- consistency with the fact sheet ---


def test_reference_tables_mirror_facts(conn, facts):
    carriers = {r["code"]: r for r in rows(conn, "SELECT * FROM carriers")}
    assert set(carriers) == {c["code"] for c in facts["carriers"]}
    for c in facts["carriers"]:
        assert carriers[c["code"]]["hazmat_certified"] == int(c["hazmat_certified"])
        assert json.loads(carriers[c["code"]]["modes"]) == c["modes"]

    warehouses = {r["code"]: r for r in rows(conn, "SELECT * FROM warehouses")}
    assert {
        w["code"]: json.loads(warehouses[w["code"]]["hazmat_docks"]) for w in facts["warehouses"]
    } == {w["code"]: w["hazmat_docks"] for w in facts["warehouses"]}


def test_rate_cards_equal_the_pricing_engine(conn, facts):
    cards = rows(conn, "SELECT * FROM rate_cards")
    expected = sum(len(c["modes"]) * len(c["zones"]) for c in facts["carriers"])
    assert len(cards) == expected
    for r in cards:
        assert r["rate_per_lb"] == pricing.rate_per_lb(
            facts, r["carrier_code"], r["mode"], r["zone"]
        )


def test_freight_costs_are_what_the_quote_tool_would_charge(conn, facts):
    """So "what did SH-x cost vs. what would it cost now?" never disagrees."""
    for s in rows(conn, "SELECT * FROM shipments"):
        hazmat = s["hazmat_class"] is not None
        args = (facts, s["carrier_code"], s["mode"], s["zone"], s["weight_lb"])
        if hazmat and s["carrier_code"] == "LKX":  # planted violation, priced as if allowed
            expected = {pricing.quote(*args).total_usd + facts["surcharges"]["hazmat_fee_usd"]}
        else:
            expected = {
                pricing.quote(*args, hazmat, liftgate).total_usd for liftgate in (False, True)
            }
        assert s["freight_cost_usd"] in expected, s["id"]


def test_shipments_respect_mode_weight_limits(conn, facts):
    for s in rows(conn, "SELECT id, mode, weight_lb FROM shipments"):
        assert s["mode"] in pricing.allowed_modes(facts, s["weight_lb"]), s["id"]


def test_hazmat_only_on_hazmat_docks_and_in_hazmat_facilities(conn):
    assert not rows(conn, "SELECT * FROM dock_slots d JOIN warehouses w ON w.code = d.warehouse_code "
                          "WHERE d.is_hazmat_dock = 1 AND w.hazmat_docks = '[]'")  # fmt: skip
    assert not rows(conn, "SELECT * FROM inventory i JOIN warehouses w ON w.code = i.warehouse_code "
                          "WHERE i.hazmat_class IS NOT NULL AND w.hazmat_docks = '[]'")  # fmt: skip


# --- dates are relative to today ---


def test_meta_records_the_seeding_day(db_path):
    assert seeded_on(db_path) == TODAY


def test_dates_span_the_documented_window(conn):
    (first_ship, last_ship), = conn.execute("SELECT MIN(ship_date), MAX(ship_date) FROM shipments")  # fmt: skip
    assert (first_ship, last_ship) == (days(-60), days(14))
    (first_slot, last_slot), = conn.execute("SELECT MIN(slot_date), MAX(slot_date) FROM dock_slots")  # fmt: skip
    assert (first_slot, last_slot) == (days(-3), days(21))


def test_tomorrow_has_bookable_slots_at_chi1(conn):
    assert rows(conn, f"SELECT 1 FROM dock_slots WHERE warehouse_code = 'CHI1' "
                      f"AND slot_date = '{days(1)}' AND status = 'available'")  # fmt: skip


def test_no_slots_on_days_a_facility_is_closed(conn):
    by_weekday = {
        (r["warehouse_code"], date.fromisoformat(r["slot_date"]).strftime("%a"))
        for r in rows(conn, "SELECT DISTINCT warehouse_code, slot_date FROM dock_slots")
    }
    assert ("MKE1", "Sat") not in by_weekday and ("MKE1", "Sun") not in by_weekday
    assert ("CHI1", "Sun") not in by_weekday
    assert ("JOL1", "Sun") in by_weekday  # the only 7-day facility


def test_shipment_status_is_consistent_with_dates(conn):
    today = TODAY.isoformat()
    for s in rows(conn, "SELECT * FROM shipments"):
        if s["ship_date"] > today:
            assert s["status"] == "scheduled" and s["delivered_date"] is None
        if s["status"] in ("delivered", "exception"):
            assert s["delivered_date"] is not None and s["delivered_date"] <= today
        if s["status"] == "delayed":
            assert s["delivered_date"] is None and s["promised_date"] < today


# --- planted demo scenarios (the example questions in the UI depend on them) ---


def test_exactly_two_hazmat_shipments_used_a_non_certified_carrier(conn):
    violations = rows(conn, "SELECT s.* FROM shipments s JOIN carriers c ON c.code = s.carrier_code "
                            "WHERE s.hazmat_class IS NOT NULL AND c.hazmat_certified = 0")  # fmt: skip
    assert len(violations) == 2
    assert {v["carrier_code"] for v in violations} == {"LKX"}
    assert all(v["ship_date"] < TODAY.isoformat() for v in violations)


def test_weather_hold_affects_recent_i94_freight(conn):
    held = rows(conn, f"SELECT * FROM shipments WHERE destination_city IN ('Detroit', 'Minneapolis') "
                      f"AND ship_date >= '{days(-5)}' AND ship_date < '{TODAY}'")  # fmt: skip
    assert held
    for s in held:
        assert s["delivered_date"] is None
        assert s["exception_note"].startswith("Weather hold")


def test_some_inventory_is_below_reorder_point(conn):
    assert rows(conn, "SELECT 1 FROM inventory WHERE qty_on_hand < reorder_point")


# --- determinism and refresh ---


def _dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as c:
        return list(c.iterdump())


def test_same_day_produces_identical_database(tmp_path, facts):
    build_database(tmp_path / "a.db", facts, TODAY)
    build_database(tmp_path / "b.db", facts, TODAY)
    assert _dump(tmp_path / "a.db") == _dump(tmp_path / "b.db")


def test_reseeding_tomorrow_shifts_every_date(tmp_path, facts):
    build_database(tmp_path / "next.db", facts, TODAY + timedelta(days=1))
    with closing(sqlite3.connect(tmp_path / "next.db")) as c:
        assert c.execute("SELECT MIN(ship_date) FROM shipments").fetchone()[0] == days(-59)


def test_ensure_fresh_rebuilds_only_when_stale(tmp_path, facts, monkeypatch):
    db = tmp_path / "logistics.db"
    build_database(db, facts, TODAY - timedelta(days=1))
    monkeypatch.setattr(seed, "company_today", lambda _facts: TODAY)

    assert ensure_fresh(db, facts) is True
    assert seeded_on(db) == TODAY
    assert ensure_fresh(db, facts) is False
    assert not db.with_suffix(".tmp").exists()  # atomic swap leaves no temp file behind
