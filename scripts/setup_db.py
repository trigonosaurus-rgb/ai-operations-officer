import sqlite3
import os

DB_PATH = 'logistics_data.sqlite'

def init_db():
    """Initializes the SQLite database with schema and seed data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Distribution Centers Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rdc_locations (
            id INTEGER PRIMARY KEY,
            name TEXT,
            address TEXT,
            operating_hours TEXT
        )
    ''')
    
    # 2. Shipping Rates Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shipping_rates (
            id INTEGER PRIMARY KEY,
            service_type TEXT,
            cost_usd REAL
        )
    ''')

    # 3. Gate Schedule Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gate_schedule (
            id INTEGER PRIMARY KEY,
            location_id INTEGER,
            date TEXT,
            time_slot TEXT,
            status TEXT
        )
    ''')

    # Clear tables for clean initialization
    cursor.execute('DELETE FROM rdc_locations')
    cursor.execute('DELETE FROM shipping_rates')
    cursor.execute('DELETE FROM gate_schedule')

    # --- Seed Data (Based on Baker Logistics Contract) ---
    
    locations = [
        (1, 'North William Howard Taft High School', '6530 W Bryn Mawr Ave', '07:00-19:00'),
        (2, 'Central John F. Kennedy High School', '6325 W 56th St', '07:00-19:00'),
        (3, 'West - Richard T. Crane Medical Prep High School', '2245 W Jackson Blvd', '07:00-19:00'),
        (4, 'South Gwendolyn Brooks College Prep', '250 E 111th St', '07:00-19:00')
    ]
    cursor.executemany('INSERT INTO rdc_locations VALUES (?, ?, ?, ?)', locations)

    rates = [
        (1, '5000 lb dedicated FTL', 385.00),
        (2, '10000 lb dedicated FTL', 485.00)
    ]
    cursor.executemany('INSERT INTO shipping_rates VALUES (?, ?, ?)', rates)

    schedules = [
        (101, 1, '2026-05-05', '08:00-09:00', 'available'),
        (102, 1, '2026-05-05', '09:00-10:00', 'booked')
    ]
    cursor.executemany('INSERT INTO gate_schedule VALUES (?, ?, ?, ?, ?)', schedules)

    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == "__main__":
    init_db()