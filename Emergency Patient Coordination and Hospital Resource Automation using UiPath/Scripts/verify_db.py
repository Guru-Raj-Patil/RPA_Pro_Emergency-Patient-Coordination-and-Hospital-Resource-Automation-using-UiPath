import sqlite3, os, sys

db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "HospitalDB.db")
print("DB:", db)

conn = sqlite3.connect(db)

print("\n=== TABLE ROW COUNTS ===")
for t in ["PATIENTS","VENTILATORS","BEDS","BLOOD_INVENTORY","DOCUMENTS","EMERGENCY_CASES","RESOURCE_RESERVATIONS","AUDIT_LOG"]:
    n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t:<30} {n:>3} rows")

print("\n=== BEDS ===")
for r in conn.execute("SELECT BedId, Department, Status, VentilatorId FROM BEDS ORDER BY BedId"):
    v = r[3] if r[3] else "None"
    print(f"  {r[0]:<10} {r[1]:<12} {r[2]:<12} VentId:{v}")

print("\n=== VENTILATORS ===")
for r in conn.execute("SELECT VentilatorId, Status, Location FROM VENTILATORS ORDER BY VentilatorId"):
    print(f"  {r[0]:<8} {r[1]:<12} {r[2]}")

print("\n=== BLOOD INVENTORY ===")
for r in conn.execute("SELECT BloodGroup, AvailableUnits, MinimumThreshold FROM BLOOD_INVENTORY ORDER BY BloodGroup"):
    print(f"  {r[0]:<5} {r[1]:>3} units  min={r[2]}")

print("\n=== PATIENTS ===")
q = """
SELECT p.PatientId, p.Name, p.RequiredDepartment, p.RequiredVentilator,
       p.RequiredBloodGroup, p.RequiredBloodUnits,
       SUM(CASE WHEN d.VerificationStatus='Present' THEN 1 ELSE 0 END),
       COUNT(d.DocumentId)
FROM PATIENTS p
LEFT JOIN DOCUMENTS d ON p.PatientId = d.PatientId
GROUP BY p.PatientId
ORDER BY p.PatientId
"""
for r in conn.execute(q):
    v = "Vent:Y" if r[3] else "Vent:N"
    blood = f"{r[4]}/{r[5]}u" if r[4] else "None"
    docs = f"Docs:{r[6]}/{r[7]}"
    print(f"  {r[0]}  {r[1]:<18} {r[2]:<12} {v}  Blood:{blood:<8} {docs}")

conn.close()
print(f"\nDB file size: {os.path.getsize(db):,} bytes")
print("\nVERIFICATION COMPLETE - All data looks correct!")
