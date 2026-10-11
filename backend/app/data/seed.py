"""Builds the operational SQLite database from the fact sheet.

Deterministic (fixed RNG seed) but *relative to today*: every date is an offset
from the seeding day, so "is there a free dock tomorrow?" always has a real answer.
The DB is written to a temp file and atomically swapped in, so readers never see
a half-built database.
"""

import json
import math
import os
import random
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.domain import pricing
from app.domain.facts import Facts

SEED_VERSION = "1"
RNG_SEED = 42

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE warehouses (
    code           TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    address        TEXT NOT NULL,
    city           TEXT NOT NULL,
    state          TEXT NOT NULL,
    dock_count     INTEGER NOT NULL,
    hazmat_docks   TEXT NOT NULL,   -- JSON array of dock numbers
    open_time      TEXT NOT NULL,   -- HH:MM local time
    close_time     TEXT NOT NULL,
    operating_days TEXT NOT NULL    -- e.g. 'Mon-Sat'
);
CREATE TABLE carriers (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    modes               TEXT NOT NULL,  -- JSON array: PARCEL / LTL / FTL
    zones               TEXT NOT NULL,  -- JSON array: Z1..Z4
    hazmat_certified    INTEGER NOT NULL,
    cargo_insurance_usd INTEGER NOT NULL
);
CREATE TABLE customers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    industry        TEXT NOT NULL,
    tier            TEXT NOT NULL,  -- Gold / Silver / Standard
    account_manager TEXT NOT NULL
);
CREATE TABLE rate_cards (
    id             INTEGER PRIMARY KEY,
    carrier_code   TEXT NOT NULL REFERENCES carriers(code),
    mode           TEXT NOT NULL,
    zone           TEXT NOT NULL,
    rate_per_lb    REAL NOT NULL,
    min_charge_usd REAL NOT NULL
);
CREATE TABLE dock_slots (
    id             INTEGER PRIMARY KEY,
    warehouse_code TEXT NOT NULL REFERENCES warehouses(code),
    dock_no        INTEGER NOT NULL,
    is_hazmat_dock INTEGER NOT NULL,
    slot_date      TEXT NOT NULL,   -- YYYY-MM-DD
    start_time     TEXT NOT NULL,   -- HH:MM
    end_time       TEXT NOT NULL,
    status         TEXT NOT NULL,   -- available / booked / blocked
    carrier_code   TEXT REFERENCES carriers(code),
    note           TEXT
);
CREATE TABLE shipments (
    id                 TEXT PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers(id),
    origin_warehouse   TEXT NOT NULL REFERENCES warehouses(code),
    destination_city   TEXT NOT NULL,
    destination_state  TEXT NOT NULL,
    zone               TEXT NOT NULL,
    carrier_code       TEXT NOT NULL REFERENCES carriers(code),
    mode               TEXT NOT NULL,
    weight_lb          REAL NOT NULL,
    pallets            INTEGER NOT NULL,
    hazmat_class       TEXT,
    un_number          TEXT,
    ship_date          TEXT NOT NULL,
    promised_date      TEXT NOT NULL,
    delivered_date     TEXT,
    status             TEXT NOT NULL,  -- scheduled / in_transit / delivered / delayed / exception
    exception_note     TEXT,
    freight_cost_usd   REAL NOT NULL
);
CREATE TABLE inventory (
    id              INTEGER PRIMARY KEY,
    warehouse_code  TEXT NOT NULL REFERENCES warehouses(code),
    sku             TEXT NOT NULL,
    description     TEXT NOT NULL,
    category        TEXT NOT NULL,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    qty_on_hand     INTEGER NOT NULL,
    qty_reserved    INTEGER NOT NULL,
    reorder_point   INTEGER NOT NULL,
    unit_weight_lb  REAL NOT NULL,
    hazmat_class    TEXT,
    un_number       TEXT,
    last_counted    TEXT NOT NULL
);
CREATE INDEX ix_slots_lookup ON dock_slots (warehouse_code, slot_date, status);
CREATE INDEX ix_shipments_dates ON shipments (ship_date, promised_date);
CREATE INDEX ix_shipments_carrier ON shipments (carrier_code);
CREATE INDEX ix_inventory_sku ON inventory (sku);
"""

# (id, name, industry, tier, account manager, hazmat profile or None)
CUSTOMERS = [
    (1, "Brightleaf Home Goods", "Home goods", "Gold", "Dana Whitfield", None),
    (2, "Northfield Medical Supply", "Healthcare", "Gold", "Marcus Lee", None),
    (3, "Copperline Electronics", "Electronics", "Silver", "Priya Raman", ("9", "UN3481")),
    (4, "Oak & Ember Furniture", "Furniture", "Standard", "Dana Whitfield", None),
    (5, "Sunbelt Pet Co.", "Pet supplies", "Silver", "Tom Okafor", None),
    (6, "Vantage Auto Parts", "Automotive", "Silver", "Marcus Lee", ("8", "UN2794")),
    (7, "Greenway Grocers", "Grocery", "Gold", "Priya Raman", None),
    (8, "Polar Peak Outdoor", "Sporting goods", "Standard", "Tom Okafor", None),
    (9, "Ion Cell Energy", "Energy storage", "Gold", "Marcus Lee", ("9", "UN3480")),
    (10, "Riverbend Paints", "Coatings", "Silver", "Dana Whitfield", ("3", "UN1263")),
    (11, "Maple Street Apparel", "Apparel", "Standard", "Tom Okafor", None),
    (12, "Clearwater Janitorial", "Cleaning supplies", "Standard", "Priya Raman", ("8", "UN1760")),
]

# Zones approximate road distance from Chicago (Z1 <100 mi, Z2 100-300, Z3 300-600, Z4 >600).
DESTINATIONS = {
    "Z1": [("Chicago", "IL"), ("Naperville", "IL"), ("Aurora", "IL"), ("Gary", "IN"),
           ("Kenosha", "WI")],
    "Z2": [("Madison", "WI"), ("Peoria", "IL"), ("Grand Rapids", "MI"), ("Fort Wayne", "IN"),
           ("Detroit", "MI")],
    "Z3": [("Kansas City", "MO"), ("St. Louis", "MO"), ("Minneapolis", "MN"), ("Columbus", "OH"),
           ("Louisville", "KY")],
    "Z4": [("Atlanta", "GA"), ("Dallas", "TX"), ("Denver", "CO"), ("Newark", "NJ"),
           ("Charlotte", "NC")],
}  # fmt: skip

# (sku, description, category, owner customer id, unit weight lb, hazmat class, UN number)
PRODUCTS = [
    ("BLH-1001", "Ceramic dinnerware set, 16 pc", "Home goods", 1, 18.0, None, None),
    ("BLH-1002", "Linen bath towel bundle", "Home goods", 1, 6.5, None, None),
    ("BLH-1003", "Cast iron skillet 12 in", "Home goods", 1, 8.2, None, None),
    ("NMS-2001", "Nitrile exam gloves, case of 1000", "Healthcare", 2, 11.0, None, None),
    ("NMS-2002", "Surgical masks, case of 2000", "Healthcare", 2, 9.5, None, None),
    ("NMS-2003", "Digital thermometer, 50-pack", "Healthcare", 2, 4.0, None, None),
    ("CPE-3001", "Laptop with Li-ion battery installed", "Electronics", 3, 7.5, "9", "UN3481"),
    ("CPE-3002", "27 in monitor", "Electronics", 3, 16.0, None, None),
    ("CPE-3003", "Wireless headset with Li-ion battery", "Electronics", 3, 1.2, "9", "UN3481"),
    ("OEF-4001", "Solid oak dining table", "Furniture", 4, 140.0, None, None),
    ("OEF-4002", "Upholstered armchair", "Furniture", 4, 62.0, None, None),
    ("SPC-5001", "Dry dog food 40 lb bag", "Pet supplies", 5, 40.0, None, None),
    ("SPC-5002", "Clumping cat litter 25 lb", "Pet supplies", 5, 25.0, None, None),
    ("VAP-6001", "Lead-acid car battery, wet", "Automotive", 6, 41.0, "8", "UN2794"),
    ("VAP-6002", "Brake pad set", "Automotive", 6, 5.5, None, None),
    ("VAP-6003", "Synthetic motor oil 5 qt", "Automotive", 6, 10.0, None, None),
    ("GWG-7001", "Canned tomatoes, case of 24", "Grocery", 7, 22.0, None, None),
    ("GWG-7002", "Rolled oats, case of 12", "Grocery", 7, 14.0, None, None),
    ("PPO-8001", "4-person camping tent", "Sporting goods", 8, 12.0, None, None),
    ("PPO-8002", "Insulated hiking boots", "Sporting goods", 8, 3.8, None, None),
    ("ICE-9001", "Li-ion battery module 48V 5kWh", "Energy storage", 9, 110.0, "9", "UN3480"),
    ("ICE-9002", "Li-ion cell pack 12V", "Energy storage", 9, 9.0, "9", "UN3480"),
    ("ICE-9003", "Battery inverter (no cells)", "Energy storage", 9, 35.0, None, None),
    ("RBP-1101", "Exterior latex paint 5 gal", "Coatings", 10, 58.0, None, None),
    ("RBP-1102", "Oil-based enamel paint 1 gal", "Coatings", 10, 11.0, "3", "UN1263"),
    ("RBP-1103", "Paint thinner 1 gal", "Coatings", 10, 7.5, "3", "UN1263"),
    ("MSA-1201", "Cotton t-shirt, 24-pack", "Apparel", 11, 8.0, None, None),
    ("MSA-1202", "Denim jeans, 12-pack", "Apparel", 11, 15.0, None, None),
    ("CWJ-1301", "Industrial drain cleaner 1 gal", "Cleaning supplies", 12, 9.0, "8", "UN1760"),
    ("CWJ-1302", "Microfiber cloths, 100-pack", "Cleaning supplies", 12, 3.0, None, None),
]

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIPMENT_DAYS = range(-60, 15)  # relative to today
SLOT_DAYS = range(-3, 22)


def _open_weekdays(span: str) -> set[int]:
    start, end = span.split("-")
    return set(range(WEEKDAYS.index(start), WEEKDAYS.index(end) + 1))


def _hhmm(t: str) -> time:
    return datetime.strptime(t, "%H:%M").time()


def _booking_probability(days_ahead: int) -> float:
    if days_ahead <= 0:
        return 0.85
    if days_ahead == 1:
        return 0.75
    if days_ahead == 2:
        return 0.6
    if days_ahead <= 7:
        return 0.45
    if days_ahead <= 14:
        return 0.25
    return 0.1


def _gen_dock_slots(facts: Facts, today: date, rng: random.Random) -> list[tuple]:
    hazmat_carriers = [c["code"] for c in facts["carriers"] if c["hazmat_certified"]]
    truck_carriers = [c["code"] for c in facts["carriers"] if set(c["modes"]) & {"LTL", "FTL"}]
    maintenance_day = today + timedelta(days=2)
    slot_len = timedelta(minutes=facts["dock_rules"]["slot_minutes"])

    rows = []
    for wh in facts["warehouses"]:
        open_days = _open_weekdays(wh["days"])
        open_t, close_t = _hhmm(wh["open"]), _hhmm(wh["close"])
        for offset in SLOT_DAYS:
            day = today + timedelta(days=offset)
            if day.weekday() not in open_days:
                continue
            for dock in range(1, wh["dock_count"] + 1):
                is_hazmat = dock in wh["hazmat_docks"]
                start = datetime.combine(day, open_t)
                while start.time() < close_t:
                    end = start + slot_len
                    status, carrier, note = "available", None, None
                    # Fixed scenario: CHI1 hazmat dock 12 is down for maintenance in 2 days.
                    if wh["code"] == "CHI1" and dock == 12 and day == maintenance_day:
                        status, note = "blocked", "Scheduled maintenance"
                    elif rng.random() < 0.03:
                        status, note = "blocked", "Dock equipment repair"
                    elif rng.random() < _booking_probability(offset):
                        status = "booked"
                        carrier = rng.choice(hazmat_carriers if is_hazmat else truck_carriers)
                    rows.append((
                        wh["code"], dock, int(is_hazmat), day.isoformat(),
                        start.strftime("%H:%M"), end.strftime("%H:%M"), status, carrier, note,
                    ))  # fmt: skip
                    start = end
    return rows


def _gen_shipments(facts: Facts, today: date, rng: random.Random) -> list[tuple]:
    carriers = {c["code"]: c for c in facts["carriers"]}
    origins = [w["code"] for w in facts["warehouses"]]
    origin_weights = [0.4, 0.25, 0.25, 0.1]
    zones = list(DESTINATIONS)
    zone_weights = [0.3, 0.3, 0.25, 0.15]

    rows, seq = [], 24001
    for offset in SHIPMENT_DAYS:
        ship_day = today + timedelta(days=offset)
        count = rng.randint(2, 4) if ship_day.weekday() == 6 else rng.randint(5, 9)
        for _ in range(count):
            cust = rng.choice(CUSTOMERS)
            hazmat = cust[5] if cust[5] and rng.random() < 0.6 else None
            zone = rng.choices(zones, zone_weights)[0]
            city, state = rng.choice(DESTINATIONS[zone])

            roll = rng.random()
            if roll < 0.2 and not hazmat:
                weight = round(rng.uniform(5, 150), 1)
            elif roll < 0.75:
                weight = float(rng.randrange(300, 9000, 25))
            else:
                weight = float(rng.randrange(8000, 42000, 100))
            mode = rng.choice(pricing.allowed_modes(facts, weight))
            eligible = pricing.eligible_carriers(facts, mode, zone, hazmat is not None)
            if not eligible:  # e.g. hazmat LTL to Z4 on a quiet day — fall back to FTL
                mode, weight = "FTL", max(weight, 8000.0)
                eligible = pricing.eligible_carriers(facts, mode, zone, hazmat is not None)
            carrier = rng.choice(eligible)["code"]

            liftgate = mode == "LTL" and rng.random() < 0.1
            cost = pricing.quote(
                facts, carrier, mode, zone, weight, hazmat is not None, liftgate
            ).total_usd
            pallets = 0 if mode == "PARCEL" else min(26, math.ceil(weight / 1400))

            promised = ship_day + timedelta(days=facts["transit_days"][zone])
            delivered, status, note = None, "scheduled", None
            if ship_day <= today:
                on_time = rng.random() < carriers[carrier]["on_time_bias"]
                actual = promised + timedelta(days=0 if on_time else rng.choice([1, 2, 3, 5]))
                if actual <= today:
                    delivered, status = actual.isoformat(), "delivered"
                    if rng.random() < 0.02:
                        status, note = "exception", "Damage reported at delivery; claim opened"
                else:
                    status = "delayed" if today > promised else "in_transit"

            rows.append((
                f"SH-{seq}", cust[0], rng.choices(origins, origin_weights)[0], city, state, zone,
                carrier, mode, weight, pallets, hazmat[0] if hazmat else None,
                hazmat[1] if hazmat else None, ship_day.isoformat(), promised.isoformat(),
                delivered, status, note, cost,
            ))  # fmt: skip
            seq += 1

    _inject_compliance_violations(rows, facts, today)
    _inject_weather_disruption(rows, today)
    return rows


WEATHER_HOLD_CITIES = {"Detroit", "Minneapolis"}


def _inject_weather_disruption(rows: list[tuple], today: date) -> None:
    """Holds this week's I-94 freight: a live 'why is this late?' scenario."""
    window_start = (today - timedelta(days=5)).isoformat()
    for i, r in enumerate(rows):
        if r[3] in WEATHER_HOLD_CITIES and window_start <= r[12] < today.isoformat():
            r = list(r)
            r[14] = None  # not delivered yet
            r[15] = "delayed" if r[13] < today.isoformat() else "in_transit"
            r[16] = (
                "Weather hold: severe storms closed sections of I-94 (MI/MN); carrier ETA +2 days"
            )
            rows[i] = tuple(r)


def _inject_compliance_violations(rows: list[tuple], facts: Facts, today: date) -> None:
    """Plants two past hazmat LTL shipments on a non-certified carrier.

    Gives the demo a realistic audit finding ("which hazmat shipments broke the
    carrier policy?") that requires joining the policy PDF with SQL data.
    """
    lkx_zones = next(c["zones"] for c in facts["carriers"] if c["code"] == "LKX")
    candidates = [
        i
        for i, r in enumerate(rows)
        if r[10] and r[7] == "LTL" and r[5] in lkx_zones and r[12] < today.isoformat()
    ]
    for i in candidates[3:5]:
        r = list(rows[i])
        r[6] = "LKX"
        r[17] = (
            pricing.quote(facts, "LKX", "LTL", r[5], r[8]).total_usd
            + facts["surcharges"]["hazmat_fee_usd"]
        )
        rows[i] = tuple(r)


def _gen_inventory(facts: Facts, today: date, rng: random.Random) -> list[tuple]:
    rows = []
    for wh in facts["warehouses"]:
        hazmat_ok = bool(wh["hazmat_docks"])
        stocked = [p for p in PRODUCTS if hazmat_ok or p[5] is None]
        for sku, desc, cat, cust, unit_w, hz, un in rng.sample(stocked, k=min(18, len(stocked))):
            reorder = rng.choice([20, 40, 60, 100, 150])
            qty = rng.randint(0, reorder - 1) if rng.random() < 0.15 else rng.randint(reorder, 900)
            reserved = rng.randint(0, qty // 4) if qty else 0
            counted = today - timedelta(days=rng.randint(0, 20))
            rows.append((wh["code"], sku, desc, cat, cust, qty, reserved, reorder, unit_w, hz, un,
                         counted.isoformat()))  # fmt: skip
    return rows


def build_database(db_path: Path, facts: Facts, today: date) -> dict[str, int]:
    """(Re)creates the database for `today`. Returns row counts per table."""
    rng = random.Random(RNG_SEED)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)

    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("seeded_on", today.isoformat()),
                ("timezone", facts["company"]["timezone"]),
                ("seed_version", SEED_VERSION),
            ],
        )
        conn.executemany(
            "INSERT INTO warehouses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (w["code"], w["name"], w["address"], w["city"], w["state"], w["dock_count"],
                 json.dumps(w["hazmat_docks"]), w["open"], w["close"], w["days"])
                for w in facts["warehouses"]
            ],
        )  # fmt: skip
        conn.executemany(
            "INSERT INTO carriers VALUES (?, ?, ?, ?, ?, ?)",
            [
                (c["code"], c["name"], json.dumps(c["modes"]), json.dumps(c["zones"]),
                 int(c["hazmat_certified"]), c["cargo_insurance_usd"])
                for c in facts["carriers"]
            ],
        )  # fmt: skip
        conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", [c[:5] for c in CUSTOMERS])
        conn.executemany(
            "INSERT INTO rate_cards (carrier_code, mode, zone, rate_per_lb, min_charge_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (c["code"], mode, zone, pricing.rate_per_lb(facts, c["code"], mode, zone),
                 facts["base_rates"][mode]["min_charge"])
                for c in facts["carriers"]
                for mode in c["modes"]
                for zone in c["zones"]
            ],
        )  # fmt: skip
        conn.executemany(
            "INSERT INTO dock_slots (warehouse_code, dock_no, is_hazmat_dock, slot_date, "
            "start_time, end_time, status, carrier_code, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _gen_dock_slots(facts, today, rng),
        )
        conn.executemany(
            "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _gen_shipments(facts, today, rng),
        )
        conn.executemany(
            "INSERT INTO inventory (warehouse_code, sku, description, category, customer_id, "
            "qty_on_hand, qty_reserved, reorder_point, unit_weight_lb, hazmat_class, un_number, "
            "last_counted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _gen_inventory(facts, today, rng),
        )
        conn.commit()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        conn.close()

    os.replace(tmp_path, db_path)
    return counts


def company_today(facts: Facts) -> date:
    return datetime.now(ZoneInfo(facts["company"]["timezone"])).date()


def seeded_on(db_path: Path) -> date | None:
    if not db_path.exists():
        return None
    try:
        # Note: `with sqlite3.connect()` only commits — closing() actually releases the file.
        with closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'seeded_on'").fetchone()
        return date.fromisoformat(row[0]) if row else None
    except sqlite3.Error:
        return None


def ensure_fresh(db_path: Path, facts: Facts) -> bool:
    """Reseeds if the DB is missing or was generated on a previous day. Returns True if rebuilt."""
    today = company_today(facts)
    if seeded_on(db_path) == today:
        return False
    build_database(db_path, facts, today)
    return True
