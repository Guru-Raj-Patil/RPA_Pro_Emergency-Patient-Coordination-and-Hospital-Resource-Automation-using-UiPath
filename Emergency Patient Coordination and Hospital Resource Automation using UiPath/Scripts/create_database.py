#!/usr/bin/env python3
"""
create_database.py
Emergency Patient Coordination – Hospital RPA Project
Creates HospitalDB.db from the SQL schema and seeds all test data.
Run from the project root:
    python Scripts\create_database.py
"""

import sqlite3
import os
import sys
from datetime import datetime

# Resolve paths
script_dir   = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
db_path      = os.path.join(project_root, "Data", "HospitalDB.db")
sql_path     = os.path.join(project_root, "Scripts", "InitDB.sql")

print(f"Project root : {project_root}")
print(f"Database     : {db_path}")
print(f"SQL script   : {sql_path}")
print()

# Remove existing DB for clean creation
if os.path.exists(db_path):
    os.remove(db_path)
    print("Removed existing HospitalDB.db")

# Read SQL script (strip SQLite-specific PRAGMA journal_mode for executescript compat)
with open(sql_path, "r", encoding="utf-8") as f:
    sql_content = f.read()

# Create and populate the database
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA journal_mode = WAL")

try:
    # executescript handles multi-statement SQL
    conn.executescript(sql_content)
    conn.commit()
    print("Schema and seed data applied successfully.\n")
except sqlite3.Error as e:
    print(f"ERROR: {e}")
    conn.close()
    sys.exit(1)

# ── Verification ──────────────────────────────────────────────
print("=" * 55)
print(" DATABASE VERIFICATION")
print("=" * 55)

tables = [
    ("PATIENTS",        "SELECT COUNT(*) FROM PATIENTS"),
    ("VENTILATORS",     "SELECT COUNT(*) FROM VENTILATORS"),
    ("BEDS",            "SELECT COUNT(*) FROM BEDS"),
    ("BLOOD_INVENTORY", "SELECT COUNT(*) FROM BLOOD_INVENTORY"),
    ("DOCUMENTS",       "SELECT COUNT(*) FROM DOCUMENTS"),
    ("EMERGENCY_CASES", "SELECT COUNT(*) FROM EMERGENCY_CASES"),
]

for name, q in tables:
    cur = conn.execute(q)
    cnt = cur.fetchone()[0]
    print(f"  {name:<25} {cnt:>3} rows")

print()
print("─" * 55)
print(" BEDS STATUS")
print("─" * 55)
for row in conn.execute("SELECT BedId, Department, Status, VentilatorId FROM BEDS ORDER BY BedId"):
    vent = row[3] if row[3] else "—"
    print(f"  {row[0]:<10} {row[1]:<12} {row[2]:<12} Vent:{vent}")

print()
print("─" * 55)
print(" VENTILATORS STATUS")
print("─" * 55)
for row in conn.execute("SELECT VentilatorId, Status, Location FROM VENTILATORS ORDER BY VentilatorId"):
    print(f"  {row[0]:<8} {row[1]:<12} {row[2]}")

print()
print("─" * 55)
print(" BLOOD INVENTORY")
print("─" * 55)
for row in conn.execute("SELECT BloodGroup, AvailableUnits, MinimumThreshold FROM BLOOD_INVENTORY ORDER BY BloodGroup"):
    print(f"  {row[0]:<6} {row[1]:>3} units  (min threshold: {row[2]})")

print()
print("─" * 55)
print(" PATIENTS & DOCUMENT STATUS")
print("─" * 55)
query = """
    SELECT p.PatientId, p.Name, p.RequiredDepartment,
           p.RequiredVentilator, p.RequiredBloodGroup, p.RequiredBloodUnits,
           COUNT(CASE WHEN d.VerificationStatus='Present' THEN 1 END) as DocPresent,
           COUNT(d.DocumentId) as DocTotal
    FROM PATIENTS p
    LEFT JOIN DOCUMENTS d ON p.PatientId = d.PatientId
    GROUP BY p.PatientId
    ORDER BY p.PatientId
"""
for row in conn.execute(query):
    vent = "Vent:Yes" if row[3] else "Vent:No "
    blood = f"{row[4]} x{row[5]}" if row[4] else "None"
    docs  = f"Docs:{row[6]}/{row[7]}"
    print(f"  {row[0]}  {row[1]:<18} {row[2]:<12} {vent}  {blood:<8}  {docs}")

conn.close()
print()
print("=" * 55)
print(" DATABASE SETUP COMPLETE")
print("=" * 55)
print(f" File: {db_path}")
print(f" Size: {os.path.getsize(db_path):,} bytes")
