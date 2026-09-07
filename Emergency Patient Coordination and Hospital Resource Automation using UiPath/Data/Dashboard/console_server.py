#!/usr/bin/env python3
"""
Emergency Coordination Console - local companion server.

Serves the dashboard with LIVE data (re-read from Data/db/*.psv on every request)
and accepts patient-intake submissions that feed the UiPath process input files.

- Reads/serves only. The UiPath project and its workflows are never modified.
- Writes only: appends to Data/PatientInput.psv, Data/db/PATIENTS.psv,
  Data/db/DOCUMENTS.psv, and creates document files under Patients/<id>/.
- POST /api/restore rebuilds the demo baseline from Data/HospitalDB.db.

Run:  python console_server.py        (opens http://localhost:8000)
Stop: Ctrl+C
"""
import http.server
import socketserver
import json
import os
import re
import base64
import sqlite3
import datetime
import webbrowser
import threading
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))          # ...\<project>\Data\Dashboard
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))     # -> <project>
DB = os.path.join(ROOT, "Data", "db")
TEMPLATE = os.path.join(HERE, "dashboard_template.html")
INPUT_FILE = os.path.join(ROOT, "Data", "PatientInput.psv")
CONFIG_FILE = os.path.join(ROOT, "Data", "Config.psv")
SEED_DB = os.path.join(ROOT, "Data", "HospitalDB.db")
PATIENTS_DIR = os.path.join(ROOT, "Patients")
PORT = int(os.environ.get("CONSOLE_PORT", "8000"))

REQUIRED_DOCS = ["ID_Proof", "Insurance", "Consent_Form", "Medical_Report"]
ALLOWED_DOC_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_DOC_BYTES = 12 * 1024 * 1024
MAX_BODY_BYTES = 80 * 1024 * 1024

TOKENS = {
    "<!--RPA_CASES-->": "EMERGENCY_CASES.psv",
    "<!--RPA_PATIENTS-->": "PATIENTS.psv",
    "<!--RPA_BEDS-->": "BEDS.psv",
    "<!--RPA_VENTS-->": "VENTILATORS.psv",
    "<!--RPA_BLOOD-->": "BLOOD_INVENTORY.psv",
    "<!--RPA_RESV-->": "RESOURCE_RESERVATIONS.psv",
    "<!--RPA_AUDIT-->": "AUDIT_LOG.psv",
    "<!--RPA_DOCS-->": "DOCUMENTS.psv",
    "<!--RPA_TESTS-->": "TEST_RESULTS.psv",
    "<!--RPA_DEPTS-->": "DEPARTMENTS.psv",
    "<!--RPA_DOCTORS-->": "DOCTORS.psv",
    "<!--RPA_THEATRES-->": "OPERATING_THEATRES.psv",
    "<!--RPA_DOCASSIGN-->": "DOCTOR_ASSIGNMENTS.psv",
    "<!--RPA_OTSCHED-->": "OT_SCHEDULE.psv",
    "<!--RPA_ADM-->": "ADMISSIONS.psv",
    "<!--RPA_BILLING-->": "BILLING.psv",
    "<!--RPA_DISCH-->": "DISCHARGES.psv",
    "<!--RPA_CLAIMS-->": "INSURANCE_CLAIMS.psv",
}

BASELINE_INPUT = [
    "PatientId|Name|Age|Gender|EmergencyType|RequiredDepartment|VentilatorRequired|BloodGroup|BloodUnits|ProcessStatus|CaseId|Notes",
    "P1024|Rahul Kumar|54|Male|Critical|ICU|Yes|O-|4|Pending||T1: Success scenario",
    "P1025|Ananya Singh|32|Female|Urgent|ICU|No|A+|2|Pending||T2: Missing Medical Report",
    "P1026|Mohan Das|67|Male|Critical|ICU|Yes|B+|3|Pending||T3: Run TestSetup_T3 first",
    "P1027|Priya Sharma|45|Female|Critical|ICU|Yes|AB+|2|Pending||T4: Run TestSetup_T4 first",
    "P1028|Arun Mehta|29|Male|Critical|ICU|Yes|O-|10|Pending||T5: Insufficient blood O-",
    "P1029|Kavitha Nair|38|Female|Standard|General|No|B-|2|Pending||T6: Batch scenario",
    "P1030|Suresh Patel|61|Male|Urgent|General|No|A-|1|Pending||T6: Batch scenario",
    "P1031|Deepa Reddy|55|Female|Critical|Cardiology|No|AB-|1|Pending||T6: Batch scenario",
]

DB_SCHEMA = {
    "PATIENTS": ["PatientId", "Name", "Age", "Gender", "EmergencyType", "RequiredDepartment",
                 "RequiredVentilator", "RequiredBloodGroup", "RequiredBloodUnits", "CreatedAt"],
    "VENTILATORS": ["VentilatorId", "Status", "Location", "LastUpdated"],
    "BEDS": ["BedId", "Department", "BedType", "Status", "VentilatorId", "LastUpdated"],
    "BLOOD_INVENTORY": ["BloodGroup", "AvailableUnits", "MinimumThreshold", "LastUpdated"],
    "DOCUMENTS": ["DocumentId", "PatientId", "DocumentType", "FilePath", "VerificationStatus", "VerifiedAt"],
    "EMERGENCY_CASES": ["CaseId", "PatientId", "CaseStatus", "DocumentStatus", "BedStatus",
                        "VentilatorStatus", "BloodStatus", "ReadinessPercentage", "PendingAction",
                        "CreatedAt", "UpdatedAt"],
    "RESOURCE_RESERVATIONS": ["ReservationId", "CaseId", "ResourceType", "ResourceId", "Quantity",
                              "Status", "ReservedAt"],
    "AUDIT_LOG": ["LogId", "CaseId", "Action", "Description", "Timestamp", "PerformedBy"],
    # --- episode extension: care team, theatre, admission, billing, discharge ---
    "DEPARTMENTS": ["DepartmentId", "Name", "Type", "FloorWard", "HeadDoctorId", "LastUpdated"],
    "DOCTORS": ["DoctorId", "Name", "DepartmentId", "Designation", "Specialty", "IsSurgeon",
                "OnCallStatus", "ShiftStart", "ShiftEnd", "CurrentLoad", "MaxLoad", "Contact",
                "Email", "LastUpdated"],
    "OPERATING_THEATRES": ["TheatreId", "Name", "DepartmentAffinity", "Status", "LastUpdated"],
    "DOCTOR_ASSIGNMENTS": ["AssignmentId", "CaseId", "DoctorId", "Role", "Specialty", "AssignedAt", "Status"],
    "OT_SCHEDULE": ["SlotId", "TheatreId", "CaseId", "SurgeonId", "AnaesthetistId",
                    "ScheduledStart", "ScheduledEnd", "Status"],
    "ADMISSIONS": ["AdmissionId", "CaseId", "PatientId", "BedId", "AttendingDoctorId",
                   "AdmittedAt", "ExpectedStayDays", "Status", "DischargeReadyAt"],
    "BILLING": ["ChargeId", "CaseId", "Category", "Description", "Quantity", "UnitPrice", "Amount", "PostedAt"],
    "DISCHARGES": ["DischargeId", "CaseId", "PatientId", "ClinicalClearanceBy", "ClinicalClearanceAt",
                   "FinalBillAmount", "PaymentStatus", "FollowUpDate", "DischargeSummaryPath", "DischargedAt"],
    "INSURANCE_CLAIMS": ["ClaimId", "CaseId", "Insurer", "PolicyNumber", "ClaimAmount",
                         "PacketPath", "Status", "SubmittedAt"],
}


# ---------------------------------------------------------------- helpers
def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def clean_field(v):
    return str(v).replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def hospital_name():
    for line in read_text(CONFIG_FILE).splitlines()[1:]:
        p = line.split("|")
        if len(p) >= 2 and p[0].strip().lower() == "hospitalname":
            return p[1].strip()
    return "City General Hospital"


def data_rows(name):
    txt = read_text(os.path.join(DB, name))
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    return [l.split("|") for l in lines[1:]] if len(lines) > 1 else []


def next_patient_number():
    nums = [1031]
    for src in (data_rows("PATIENTS.psv"), [l.split("|") for l in read_text(INPUT_FILE).splitlines()[1:] if l.strip()]):
        for r in src:
            if r and re.match(r"^P\d+$", r[0].strip()):
                nums.append(int(r[0].strip()[1:]))
    return max(nums) + 1


def render_page():
    html = read_text(TEMPLATE)
    if not html:
        return "<h1>dashboard_template.html not found next to console_server.py</h1>"
    cases = data_rows("EMERGENCY_CASES.psv")
    meta = "\n".join([
        "key|value",
        "hospital|" + hospital_name(),
        "generatedAt|" + now_str(),
        "totalCases|" + str(len(cases)),
        "mode|live",
    ])
    html = html.replace("<!--RPA_META-->", meta)
    html = html.replace("<!--RPA_INPUT-->", read_text(INPUT_FILE).replace("</", "< /"))
    for token, fname in TOKENS.items():
        html = html.replace(token, read_text(os.path.join(DB, fname)).replace("</", "< /"))
    return html


# ---------------------------------------------------------------- writes
def append_line(path, line):
    existing = read_text(path)
    sep = "" if (not existing or existing.endswith("\n")) else "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(sep + line + "\n")


def submit_case(body):
    name = clean_field(body.get("name", ""))
    if not name:
        raise ValueError("Patient name is required.")
    age = clean_field(body.get("age", "")) or "0"
    gender = clean_field(body.get("gender", "")) or "Unspecified"
    etype = clean_field(body.get("emergencyType", "")) or "Standard"
    dept = clean_field(body.get("department", "")) or "General"
    vent = bool(body.get("ventilator", False))
    bg = clean_field(body.get("bloodGroup", "")) or "O+"
    units = clean_field(body.get("bloodUnits", "")) or "0"
    notes = clean_field(body.get("notes", "")) or "Submitted from intake console"
    docs = body.get("docs", {}) or {}

    try:
        int(age)
    except ValueError:
        raise ValueError("Age must be a number.")
    try:
        int(units)
    except ValueError:
        raise ValueError("Blood units must be a number.")

    num = next_patient_number()
    pid = "P%d" % num
    caseid = "ER%d" % num
    ts = now_str()

    append_line(INPUT_FILE, "|".join(
        [pid, name, age, gender, etype, dept, "Yes" if vent else "No", bg, units, "Pending", "", notes]))
    append_line(os.path.join(DB, "PATIENTS.psv"), "|".join(
        [pid, name, age, gender, etype, dept, "1" if vent else "0", bg, units, ts]))

    existing_docs = data_rows("DOCUMENTS.psv")
    next_doc_id = max([int(r[0]) for r in existing_docs if r and r[0].strip().isdigit()] + [0]) + 1
    patient_folder = os.path.join(PATIENTS_DIR, pid)
    present = []
    for i, dt in enumerate(REQUIRED_DOCS):
        entry = docs.get(dt)
        saved_rel = ""
        if isinstance(entry, dict) and entry.get("dataB64"):
            try:
                blob = base64.b64decode(entry["dataB64"])
            except (ValueError, TypeError):
                blob = b""
            if 0 < len(blob) <= MAX_DOC_BYTES:
                ext = os.path.splitext(str(entry.get("filename", "")))[1].lower()
                if ext == ".jpeg":
                    ext = ".jpg"
                if ext not in ALLOWED_DOC_EXT:
                    ext = ".pdf"
                os.makedirs(patient_folder, exist_ok=True)
                with open(os.path.join(patient_folder, dt + ext), "wb") as f:
                    f.write(blob)
                saved_rel = "Patients/%s/%s%s" % (pid, dt, ext)
                present.append(dt)
        append_line(os.path.join(DB, "DOCUMENTS.psv"), "|".join([
            str(next_doc_id + i), pid, dt, saved_rel,
            "Present" if saved_rel else "Missing",
            ts if saved_rel else "",
        ]))

    return {
        "ok": True,
        "patientId": pid,
        "caseId": caseid,
        "documentsOnFile": present,
        "documentsMissing": [d for d in REQUIRED_DOCS if d not in present],
        "message": "Case %s queued for %s. Run the coordination process to see it progress."
                   % (caseid, name),
    }


def restore_baseline():
    os.makedirs(DB, exist_ok=True)
    cn = sqlite3.connect(SEED_DB)
    try:
        for table, cols in DB_SCHEMA.items():
            try:
                rows = cn.execute("SELECT %s FROM %s" % (",".join(cols), table)).fetchall()
            except sqlite3.Error:
                rows = []
            with open(os.path.join(DB, table + ".psv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("|".join(cols) + "\n")
                for r in rows:
                    f.write("|".join("" if v is None else clean_field(v) for v in r) + "\n")
    finally:
        cn.close()
    with open(INPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(BASELINE_INPUT) + "\n")
    with open(os.path.join(DB, "TEST_RESULTS.psv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("TestId|Scenario|Expected|Actual|Result\n")
    return {"ok": True, "message": "Demo baseline restored: %d tables reseeded, intake queue reset to 8 cases."
            % len(DB_SCHEMA)}


# ---------------------------------------------------------------- HTTP
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("  %s - %s" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, render_page(), "text/html; charset=utf-8")
        elif path == "/api/ping":
            self._send(200, json.dumps({"ok": True, "hospital": hospital_name(), "time": now_str()}))
        else:
            self._send(404, json.dumps({"ok": False, "error": "not found"}))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > MAX_BODY_BYTES:
            self._send(413, json.dumps({"ok": False, "error": "upload too large"}))
            return
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send(400, json.dumps({"ok": False, "error": "invalid JSON body"}))
            return
        try:
            if path == "/api/submit":
                self._send(200, json.dumps(submit_case(body)))
            elif path == "/api/restore":
                self._send(200, json.dumps(restore_baseline()))
            else:
                self._send(404, json.dumps({"ok": False, "error": "not found"}))
        except ValueError as e:
            self._send(400, json.dumps({"ok": False, "error": str(e)}))
        except Exception as e:  # noqa: BLE001 - surface unexpected errors to the client
            self._send(500, json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}))


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global PORT
    for candidate in range(PORT, PORT + 20):
        try:
            httpd = Server(("127.0.0.1", candidate), Handler)
            PORT = candidate
            break
        except OSError:
            continue
    else:
        print("No free port in range %d-%d" % (PORT, PORT + 20))
        return
    url = "http://localhost:%d/" % PORT
    print("=" * 60)
    print("  Emergency Coordination Console")
    print("  %s" % hospital_name())
    print("  %s" % url)
    print("  Project root: %s" % ROOT)
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
