#!/usr/bin/env python3
"""
Emergency Coordination Console - local companion server + real-time coordinator.

Serves the dashboard with LIVE data (re-read from Data/db/*.psv on every request),
processes each intake submission IMMEDIATELY (no batch wait), and runs a background
monitor that fulfils pending requirements (bed / doctor / blood / ventilator) the
moment a resource frees up.

- POST /api/submit   -> register + coordinate one patient now (mirrors Main.xaml +
                        Workflows/*.xaml, adds criticality-based ward re-routing).
- GET  /api/state    -> JSON snapshot for the no-reload live dashboards.
- POST /api/confirm-transfer -> authorised-staff confirm a temp-bed -> requested-ward move.
- POST /api/assign-doctor    -> force a doctor-assignment attempt for a case.
- POST /api/restore  -> rebuild the demo baseline from Data/HospitalDB.db.
- background monitor  -> auto-fulfils PENDING_REQUIREMENTS rows on availability change.

Run:  python console_server.py        (opens http://localhost:8000)
Stop: Ctrl+C
"""
import http.server
import socketserver
import json
import os
import re
import time
import errno
import base64
import zlib
import sqlite3
import datetime
import webbrowser
import threading
import urllib.parse
import urllib.request

# Serialises intake submissions + the auto-coordination pipeline so two patients
# hitting Submit at once can't interleave read-modify-write on the .psv datastore.
PROCESS_LOCK = threading.Lock()

# .NET DateTime.Ticks-compatible ids (AUDIT_LOG.LogId / RESOURCE_RESERVATIONS.ReservationId
# are sorted numerically by the dashboard, so console rows must share Main.xaml's scale).
_TICKS_EPOCH = datetime.datetime(1, 1, 1)
_tick_lock = threading.Lock()
_last_tick = [0]


def net_ticks():
    with _tick_lock:
        t = int((datetime.datetime.now() - _TICKS_EPOCH).total_seconds() * 10_000_000)
        if t <= _last_tick[0]:
            t = _last_tick[0] + 1
        _last_tick[0] = t
        return t

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
    "<!--RPA_PENDINGREQ-->": "PENDING_REQUIREMENTS.psv",
    "<!--RPA_DOCDATA-->": "PATIENT_DOCUMENT_DATA.psv",
    "<!--RPA_CONTACT-->": "PATIENT_CONTACT.psv",
}

BASELINE_INPUT = [
    "PatientId|Name|Age|Gender|EmergencyType|RequiredDepartment|VentilatorRequired|BloodGroup|BloodUnits|ProcessStatus|CaseId|Notes|EmailAddress",
    "P1024|Rahul Kumar|54|Male|Critical|ICU|Yes|O-|4|Pending||T1: Success scenario|rahul.kumar@gmail.com",
    "P1025|Ananya Singh|32|Female|Urgent|ICU|No|A+|2|Pending||T2: Missing Medical Report|ananya.singh@outlook.com",
    "P1026|Mohan Das|67|Male|Critical|ICU|Yes|B+|3|Pending||T3: Run TestSetup_T3 first|mohan.das@gmail.com",
    "P1027|Priya Sharma|45|Female|Critical|ICU|Yes|AB+|2|Pending||T4: Run TestSetup_T4 first|priya.sharma@gmail.com",
    "P1028|Arun Mehta|29|Male|Critical|ICU|Yes|O-|10|Pending||T5: Insufficient blood O-|arun.mehta@yahoo.com",
    "P1029|Kavitha Nair|38|Female|Standard|General|No|B-|2|Pending||T6: Batch scenario|kavitha.nair@gmail.com",
    "P1030|Suresh Patel|61|Male|Urgent|General|No|A-|1|Pending||T6: Batch scenario|suresh.patel@gmail.com",
    "P1031|Deepa Reddy|55|Female|Critical|Cardiology|No|AB-|1|Pending||T6: Batch scenario|deepa.reddy@gmail.com",
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
    # --- real-time coordination: persistent unmet-requirement tracking ---
    "PENDING_REQUIREMENTS": ["RequirementId", "CaseId", "PatientId", "Type", "RequestedValue",
                             "CurrentFallback", "Priority", "Status", "CreatedAt", "UpdatedAt", "ResolvedAt"],
    # --- data read out of the uploaded documents (one row per extracted field) ---
    "PATIENT_DOCUMENT_DATA": ["RecordId", "PatientId", "CaseId", "DocumentType",
                              "Field", "Value", "ExtractedAt"],
    # --- patient contact details captured at registration (email for the discharge bill) ---
    "PATIENT_CONTACT": ["PatientId", "CaseId", "EmailAddress", "Phone", "CapturedAt"],
}

# A patient's registered email lives in its own side table (PATIENT_CONTACT.psv) rather
# than a new PATIENTS.psv column, so none of the hand-parsed .xaml LINQ or the SQLite
# reseed path has to change. restore_baseline() writes it header-only when the seed DB
# has no such table, which is the correct empty state.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------- helpers
def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_text(path):
    """Read a UTF-8 file. A genuinely absent file -> "". A real read error
    (lock, permission, corruption) is retried briefly, then raised - it must
    never be mistaken for "empty file", which would let a caller rewrite a
    whole datastore table from scratch and silently lose every other row."""
    last = None
    for attempt in range(4):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
        except OSError as e:
            last = e
            time.sleep(0.12 * (attempt + 1))
    raise RuntimeError("could not read %s after retries: %s" % (path, last))


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
    email = clean_field(body.get("email", "") or body.get("emailAddress", ""))
    phone = clean_field(body.get("phone", ""))
    docs = body.get("docs", {}) or {}

    try:
        int(age)
    except ValueError:
        raise ValueError("Age must be a number.")
    try:
        int(units)
    except ValueError:
        raise ValueError("Blood units must be a number.")
    if email and not _EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address (e.g. patient@gmail.com).")

    num = next_patient_number()
    pid = "P%d" % num
    caseid = "ER%d" % num
    ts = now_str()

    append_line(INPUT_FILE, "|".join(
        [pid, name, age, gender, etype, dept, "Yes" if vent else "No", bg, units, "Pending", "", notes, email]))
    append_line(os.path.join(DB, "PATIENTS.psv"), "|".join(
        [pid, name, age, gender, etype, dept, "1" if vent else "0", bg, units, ts]))
    save_patient_contact(pid, caseid, email, phone)

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

    result = {
        "ok": True,
        "patientId": pid,
        "caseId": caseid,
        "email": email,
        "documentsOnFile": present,
        "documentsMissing": [d for d in REQUIRED_DOCS if d not in present],
        "message": "Case %s queued for %s. Run the coordination process to see it progress." % (caseid, name),
    }

    # Instant coordination: create the EMERGENCY_CASES row + run the checks now, so
    # the Admin / Operations dashboard reflects this patient without a Main.xaml run.
    if config_flag("AutoRouteOnIntake", True):
        try:
            result.update(process_case(pid, caseid, name, etype, dept, vent, bg, int(units)))
            result["ok"] = True
        except Exception as e:  # noqa: BLE001 - the intake write already succeeded; coordination failure must be loud, not silent
            result["ok"] = False
            result["caseState"] = "CoordinationFailed"
            result["message"] = ("Case %s saved for %s, but auto-coordination FAILED (%s: %s). "
                                 "The case is flagged for review; run Main.xaml or retry."
                                 % (caseid, name, type(e).__name__, e))
            try:
                audit(caseid, "COORDINATION_FAILED",
                      "Intake coordination aborted for %s (%s): %s" % (name, type(e).__name__, e))
                _hdr, _cases = load_table("EMERGENCY_CASES.psv")
                for _c in _cases:
                    if _c and _c[0].strip() == caseid and len(_c) >= 11:
                        _c[2] = "Error"
                        _c[8] = "Coordination failed at intake - needs review"
                        _c[10] = now_str()
                save_table("EMERGENCY_CASES.psv", _hdr, _cases)
            except Exception:  # noqa: BLE001 - best effort; the client already knows it failed
                pass
    return result


def clear_stale_notifications():
    """Delete the per-case demo artifacts so a deterministic CaseId from a
    previous run cannot silently re-authorise a new episode - especially the
    discharge-approval markers that ProcessDischarge / ApproveDischarge gate on."""
    folder = os.path.join(ROOT, "Data", "Notifications")
    patterns = ("DISCHARGE_APPROVED_", "APPROVE_DISCHARGE_", "DISCHARGE_APPROVAL_REQUEST_",
                "DISCHARGE_CLEARANCE_", "CLINICAL_CLEARANCE_", "CERTIFY_",
                "TRANSFER_REQUEST_", "TRANSFER_CONFIRM_", "EMAIL_RETRY_",
                "BILL_", "EMAIL_", "APPROVAL_ER", "EXCEPTION_ER", "Notification_ER",
                "DISCHARGE_SUMMARY_", "CLAIM_", "FOLLOWUP_", "CLOSED_")
    removed = 0
    try:
        for f in os.listdir(folder):
            if f.startswith(patterns):
                try:
                    os.remove(os.path.join(folder, f))
                    removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    return removed


def restore_baseline():
    os.makedirs(DB, exist_ok=True)
    cn = sqlite3.connect(SEED_DB)
    errored = []
    try:
        for table, cols in DB_SCHEMA.items():
            try:
                rows = cn.execute("SELECT %s FROM %s" % (",".join(cols), table)).fetchall()
            except sqlite3.Error as e:
                rows = []
                errored.append("%s (%s)" % (table, e))
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
    cleared = clear_stale_notifications()
    msg = ("Demo baseline restored: %d tables reseeded, intake queue reset to 8 cases, "
           "%d stale notification file(s) cleared." % (len(DB_SCHEMA), cleared))
    if errored:
        msg += "  WARNING - these tables came back EMPTY due to a seed-DB error and need attention: " \
               + "; ".join(errored)
    return {"ok": not errored, "message": msg, "erroredTables": errored}


# ============================================================================
# Intake auto-coordination
# ----------------------------------------------------------------------------
# Mirrors Main.xaml + Workflows/*.xaml for a SINGLE freshly-submitted patient so
# the case reaches the Operations dashboard instantly (no second Main.xaml run).
# The one behavioural addition over Main.xaml is criticality-based bed re-routing:
# if the requested ward is full the patient is placed in the next ward down the
# escalation chain instead of waiting in the queue.
# ============================================================================

# emergency type -> wards to fall back to (in order) when the requested ward is full
BED_ESCALATION = {
    "CRITICAL": ["ICU", "Cardiology", "General"],
    "URGENT":   ["General"],
    "STANDARD": ["General"],
}
DOC_EXTS = (".pdf", ".PDF", ".jpg", ".jpeg", ".png", ".docx")


def _int(v, default=0):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return default


def _san(v):
    return str(v if v is not None else "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def config_get(key, default=""):
    for line in read_text(CONFIG_FILE).splitlines()[1:]:
        p = line.split("|")
        if len(p) >= 2 and p[0].strip().lower() == key.strip().lower():
            return p[1].strip()
    return default


_FLAG_OFF = {"false", "no", "0", "off", "disabled", "n"}
_FLAG_ON = {"true", "yes", "1", "on", "enabled", "y"}


def config_flag(key, default=True):
    """A Config.psv boolean. Accepts false/no/0/off/disabled as OFF (so an
    admin setting `AdminManualRelease|no` actually disables it, not just the
    exact token `false`). An unrecognised value falls back to `default` with a
    stderr warning rather than silently reading as ON."""
    raw = config_get(key, "").strip().lower()
    if raw == "":
        return default
    if raw in _FLAG_OFF:
        return False
    if raw in _FLAG_ON:
        return True
    print("  [config] %s = %r is not a recognised boolean; using default %s" % (key, raw, default))
    return default


def load_table(name):
    """Return (header_list, [row_list, ...]) for Data/db/<name>; ([],[]) if absent/empty."""
    lines = [l for l in read_text(os.path.join(DB, name)).splitlines() if l.strip()]
    if not lines:
        return [], []
    return lines[0].split("|"), [l.split("|") for l in lines[1:]]


def save_table(name, header, rows, allow_empty=False):
    """Atomically rewrite Data/db/<name> (temp file + os.replace) so concurrent
    dashboard GETs never see a half-written table.

    read_text() now raises (rather than returning "") on a real read error, so
    load_table can only hand back ([],[]) for a genuinely empty file - which
    removes the "spurious empty read -> rebuild from a bare header -> every other
    row lost" hazard at its source. This function additionally LOGS (loud, but
    non-fatal - a per-case ledger can legitimately drain to zero) when it is
    asked to write an empty table over a file that still had data rows.
    """
    if not header:
        raise ValueError("refusing to write %s with no header" % name)
    path = os.path.join(DB, name)
    if not rows and not allow_empty and os.path.exists(path):
        try:
            existing = [l for l in read_text(path).splitlines() if l.strip()]
        except RuntimeError:
            existing = []
        if len(existing) > 1:
            print("  [save_table] WARNING: writing %s as header-only; %d data row(s) were on disk. "
                  "If this was not intended, an upstream read failed." % (name, len(existing) - 1))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("|".join(header) + "\n")
        for r in rows:
            f.write("|".join(_san(c) for c in r) + "\n")
    # os.replace is atomic, but on Windows it raises PermissionError (WinError 5/32)
    # if the target is momentarily held open by a reader / AV scanner. Retry briefly.
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if attempt == 7:
                raise
            time.sleep(0.08 * (attempt + 1))


def append_row(name, fields):
    append_line(os.path.join(DB, name), "|".join(_san(c) for c in fields))


def audit(caseid, action, description, performed_by="Bot"):
    append_row("AUDIT_LOG.psv",
               [str(net_ticks()), caseid, action, _san(description), now_str(), performed_by])


def save_patient_contact(pid, caseid, email, phone=""):
    """Persist the patient's email/phone in PATIENT_CONTACT.psv (idempotent per patient).

    A malformed email is stored blank + audited rather than raised - the batch
    intake path (PatientInput.psv column 13, sweep_pending) must never let a
    contact-field typo block an emergency admission. The interactive form
    (submit_case) still rejects a bad address before it gets here."""
    email = (email or "").strip()
    if email and not _EMAIL_RE.match(email):
        audit(caseid or "", "CONTACT_EMAIL_INVALID",
              "Email '%s' for %s is not a valid address - stored blank; the discharge bill "
              "cannot be emailed until a valid address is recorded." % (email, pid))
        email = ""
    if not (email or phone):
        return
    hdr, rows = load_table("PATIENT_CONTACT.psv")
    if not hdr:
        hdr = DB_SCHEMA["PATIENT_CONTACT"]
    rows = [r for r in rows if not (r and r[0].strip() == pid)]
    rows.append([pid, caseid, email, phone, now_str()])
    save_table("PATIENT_CONTACT.psv", hdr, rows)


def patient_email(pid, caseid=None):
    """The patient's registered email. Prefers a row matching this episode's
    CaseId (column 1) so a re-admission can't mail a stale address; falls back
    to the newest row for the PatientId."""
    _, rows = load_table("PATIENT_CONTACT.psv")
    if caseid:
        for r in rows:
            if len(r) >= 3 and r[1].strip() == caseid and r[2].strip():
                return r[2].strip()
    hit = ""
    for r in rows:
        if len(r) >= 3 and r[0].strip() == pid and r[2].strip():
            hit = r[2].strip()
    return hit


def docs_on_file(pid):
    """Mirror VerifyDocuments.xaml: a doc counts as present if Patients/<pid>/<Type><ext> exists."""
    folder = os.path.join(PATIENTS_DIR, pid)
    return [d for d in REQUIRED_DOCS
            if any(os.path.exists(os.path.join(folder, d + e)) for e in DOC_EXTS)]


def bed_chain(requested, etype):
    """[requested ward] + criticality fallback wards, de-duplicated, order preserved."""
    key = etype.strip().upper()
    tail = BED_ESCALATION.get(key, BED_ESCALATION["STANDARD"])
    chain = [requested]
    for ward in tail:
        if ward.lower() not in [c.lower() for c in chain]:
            chain.append(ward)
    return chain


def assign_care_team(caseid, dept_name):
    """Mirror AssignCareTeam.xaml (attending only - the fallback wards are non-surgical)."""
    _, deps = load_table("DEPARTMENTS.psv")
    dept_id = next((r[0].strip() for r in deps
                    if len(r) >= 2 and r[1].strip().lower() == dept_name.strip().lower()), "")
    hdr, docs = load_table("DOCTORS.psv")
    cand = [r for r in docs if len(r) >= 11 and r[2].strip() == dept_id
            and r[6].strip() == "OnCall" and _int(r[9]) < _int(r[10])]
    if not cand:
        return "", "", "Unavailable", "No on-call %s consultant available (all off-duty or at capacity)" % dept_name
    cand.sort(key=lambda r: _int(r[9]))
    d = cand[0]
    att_id, att_name, att_spec = d[0].strip(), d[1].strip(), d[4].strip()
    now = now_str()
    append_row("DOCTOR_ASSIGNMENTS.psv",
               ["DA-%s-ATT" % caseid, caseid, att_id, "Attending", att_spec, now, "Assigned"])
    for r in docs:
        if r[0].strip() == att_id and len(r) >= 10:
            r[9] = str(_int(r[9]) + 1)
            if len(r) >= 14:
                r[13] = now
    save_table("DOCTORS.psv", hdr, docs)
    return att_id, att_name, "Assigned", "Attending: %s (%s) [%s]" % (att_name, att_spec, att_id)


def reserve_resources(caseid, bed_id, vent_id, vent_reserved, blood_group, blood_units, vent_floating):
    """Mirror ReserveResources.xaml happy path (resources were pre-checked by process_case)."""
    now = now_str()
    hdr_b, beds = load_table("BEDS.psv")
    for b in beds:
        if b and b[0].strip() == bed_id and len(b) >= 6:
            b[3] = "Reserved"
            if vent_floating and vent_id:
                b[4] = vent_id          # attach the portable ventilator to this bed
            b[5] = now
    save_table("BEDS.psv", hdr_b, beds)

    if vent_reserved and vent_id and vent_id != "N/A":
        hdr_v, vents = load_table("VENTILATORS.psv")
        for v in vents:
            if v and v[0].strip() == vent_id and len(v) >= 4:
                v[1] = "Reserved"
                v[3] = now
        save_table("VENTILATORS.psv", hdr_v, vents)

    if blood_units > 0:
        hdr_bl, blood = load_table("BLOOD_INVENTORY.psv")
        for r in blood:
            if r and r[0].strip() == blood_group.strip() and len(r) >= 4:
                r[1] = str(max(0, _int(r[1]) - blood_units))
                r[3] = now
        save_table("BLOOD_INVENTORY.psv", hdr_bl, blood)

    append_row("RESOURCE_RESERVATIONS.psv", [str(net_ticks()), caseid, "Bed", bed_id, "1", "Reserved", now])
    if vent_reserved and vent_id and vent_id != "N/A":
        append_row("RESOURCE_RESERVATIONS.psv",
                   [str(net_ticks()), caseid, "Ventilator", vent_id, "1", "Reserved", now])
    if blood_units > 0:
        append_row("RESOURCE_RESERVATIONS.psv",
                   [str(net_ticks()), caseid, "Blood", blood_group, str(blood_units), "Reserved", now])


def confirm_admission(caseid, pid, bed_id, att_id, etype, vent_id, vent_reserved):
    """Mirror ConfirmAdmission.xaml: ADMISSIONS row, bed/vent -> Occupied, opening BILLING."""
    now = now_str()
    hdr_b, beds = load_table("BEDS.psv")
    bed_type = "Standard"
    for b in beds:
        if b and b[0].strip() == bed_id and len(b) >= 3:
            bed_type = b[2].strip() or "Standard"
    rate = 8000 if bed_type.upper() == "PREMIUM" else 4000
    et = etype.strip().upper()
    stay = 7 if et == "CRITICAL" else (4 if et == "URGENT" else 3)
    adm_id = "ADM-" + caseid

    append_row("ADMISSIONS.psv",
               [adm_id, caseid, pid, bed_id, att_id, now, str(stay), "Admitted", ""])
    for b in beds:
        if b and b[0].strip() == bed_id and len(b) >= 6:
            b[3] = "Occupied"
            b[5] = now
    save_table("BEDS.psv", hdr_b, beds)

    if vent_reserved and vent_id and vent_id != "N/A":
        hdr_v, vents = load_table("VENTILATORS.psv")
        for v in vents:
            if v and v[0].strip() == vent_id and len(v) >= 4:
                v[1] = "Occupied"
                v[3] = now
        save_table("VENTILATORS.psv", hdr_v, vents)

    append_row("BILLING.psv", ["BIL-%s-REG" % caseid, caseid, "Registration",
                               "Emergency admission registration", "1", "500", "500", now])
    append_row("BILLING.psv", ["BIL-%s-BED1" % caseid, caseid, "BedDay",
                               "Bed %s (%s) - day 1" % (bed_id, bed_type), "1", str(rate), str(rate), now])
    return adm_id, ("Admitted to bed %s (%s) under %s; expected stay %dd; billing opened (reg 500 + bed day-1 %d INR)"
                    % (bed_id, bed_type, att_id, stay, rate))


def update_case(caseid, pid, status, doc_s, bed_s, vent_s, blood_s, score, pending):
    hdr, rows = load_table("EMERGENCY_CASES.psv")
    now = now_str()
    for r in rows:
        if r and r[0].strip() == caseid:
            created = r[9] if len(r) >= 10 and r[9].strip() else now
            r[:] = [caseid, pid, status, doc_s, bed_s, vent_s, blood_s, str(score), _san(pending), created, now]
    save_table("EMERGENCY_CASES.psv", hdr, rows)


def mark_input_processed(pid, caseid, outcome):
    """Flip this patient's PatientInput.psv row off 'Pending' so a later Main.xaml
    run won't re-process it, and stamp the CaseId column."""
    txt = read_text(INPUT_FILE)
    out = []
    for i, line in enumerate(txt.splitlines()):
        p = line.split("|")
        if i > 0 and line.strip() and p and p[0].strip() == pid and len(p) >= 12:
            p[9] = outcome
            p[10] = caseid
            out.append("|".join(p))
        else:
            out.append(line)
    with open(INPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")


def write_approval_artifact(caseid, name, dept, etype, score, status, pending, bed_id, bed_dept, interim):
    """Mirror RequestHumanApproval.xaml's APPROVAL_<case>.txt - the human-gate artifact."""
    d = os.path.join(ROOT, "Data", "Notifications")
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "APPROVAL_%s.txt" % caseid), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join([
                "ACTION REFERENCE - intake console auto-coordination",
                "Case: %s" % caseid,
                "Patient: %s   Emergency: %s   Requested dept: %s" % (name, etype, dept),
                "Created: %s" % now_str(),
                "Readiness: %d%%   Status: %s" % (score, status),
                "Bed: %s%s" % (bed_id or "none", (" (interim - in %s)" % bed_dept) if interim else ""),
                "Pending: %s" % pending,
                "",
                "[Auto-approved when ready: AutoApproveWhenReady=True. In production this is a "
                "UiPath Action Center task.]",
            ]) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- document reading
# The bot reads the text of each uploaded document, pulls the labelled "Key: Value"
# lines into PATIENT_DOCUMENT_DATA.psv, cross-checks a few against the intake form,
# and fills blank form fields (e.g. blood units) from the medical report.
# Extraction needs a text layer: works on text PDFs (raw or FlateDecode) and .txt;
# scanned / image files are saved + presence-checked but yield no fields.

_KV_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /&()\-]*?)\s*[:.…]{1,}\s*(.+?)\s*$")

DOC_FIELDS = {
    "Medical_Report": {
        "referring_physician": "ReferringPhysician",
        "presenting_complaint": "PresentingComplaint",
        "provisional_diagnosis": "ProvisionalDiagnosis",
        "emergency_category": "EmergencyCategory",
        "department_requested": "DepartmentRequested",
        "ventilator_support": "VentilatorSupport",
        "blood_group": "BloodGroup",
        "units_anticipated": "UnitsAnticipated",
        "known_allergies": "KnownAllergies",
        "investigations_advised": "InvestigationsAdvised",
    },
    "Insurance": {
        "insurer": "Insurer", "policy_number": "PolicyNumber",
        "sum_insured": "SumInsured", "valid_till": "ValidTill", "member": "Member",
    },
    "ID_Proof": {
        "name": "IdName", "date_of_birth": "DateOfBirth",
        "id_number": "IdNumber", "gender": "IdGender",
    },
    "Consent_Form": {
        "consent_given_by": "ConsentGivenBy", "relationship": "Relationship",
        "patient": "ConsentPatient",
    },
}
_DOC_FIELD_LABEL = {
    "ReferringPhysician": "Referring physician", "PresentingComplaint": "Presenting complaint",
    "ProvisionalDiagnosis": "Provisional diagnosis", "EmergencyCategory": "Emergency category",
    "DepartmentRequested": "Department requested", "VentilatorSupport": "Ventilator support",
    "BloodGroup": "Blood group", "UnitsAnticipated": "Units anticipated",
    "KnownAllergies": "Known allergies", "InvestigationsAdvised": "Investigations advised",
    "Insurer": "Insurer", "PolicyNumber": "Policy number", "SumInsured": "Sum insured",
    "ValidTill": "Valid till", "Member": "Member", "IdName": "Name on ID",
    "DateOfBirth": "Date of birth", "IdNumber": "ID number", "IdGender": "Gender on ID",
    "ConsentGivenBy": "Consent given by", "Relationship": "Relationship",
    "ConsentPatient": "Patient (consent form)",
}


def _pdf_text(raw):
    """Best-effort text layer from a PDF: pull (...) Tj / TJ operands from every
    content stream, inflating FlateDecode streams with stdlib zlib."""
    out = []
    for m in re.finditer(rb"<<([^<>]*)>>\s*stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        hdr, body = m.group(1), m.group(2)
        if b"/FlateDecode" in hdr:
            try:
                body = zlib.decompress(body)
            except zlib.error:
                continue
        for tm in re.finditer(rb"\(((?:[^()\\]|\\.)*)\)\s*T[jJ]", body):
            s = tm.group(1)
            s = s.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
            s = s.replace(b"\\n", b" ").replace(b"\\r", b" ").replace(b"\\t", b" ")
            out.append(s.decode("latin-1", "replace"))
    return "\n".join(out)


def _extract_text(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return ""
    except OSError as e:
        # a file that EXISTS but can't be read must not be reported as "scanned /
        # no text layer" - that silently skips document-driven gap-fill.
        raise RuntimeError("could not read document %s: %s" % (os.path.basename(path), e))
    if raw[:5] == b"%PDF-" or raw[:4] == b"%PDF":
        return _pdf_text(raw)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", "replace")


def _norm_key(k):
    return re.sub(r"[^a-z0-9]+", "_", k.strip().lower()).strip("_")


def parse_doc_fields(text, doctype):
    want = DOC_FIELDS.get(doctype, {})
    out = {}
    for line in text.splitlines():
        m = _KV_RE.match(line)
        if not m:
            continue
        canon = want.get(_norm_key(m.group(1)))
        if not canon or canon in out:
            continue
        val = m.group(2).strip().strip("_").strip()
        if val and set(val) != {"_"}:
            out[canon] = val
    return out


def extract_documents(pid, caseid, form):
    """Read every uploaded document for this patient, persist the fields, cross-check
    against the form, and return (per_doc_fields, mismatches, gap_fill)."""
    if not config_flag("ExtractDocumentData", True):
        return {}, [], {}
    folder = os.path.join(PATIENTS_DIR, pid)
    hdr, rows = load_table("PATIENT_DOCUMENT_DATA.psv")
    if not hdr:
        hdr = DB_SCHEMA["PATIENT_DOCUMENT_DATA"]
    rows = [r for r in rows if not (len(r) >= 3 and r[2].strip() == caseid)]   # re-extract is idempotent
    now = now_str()

    per_doc, flat = {}, {}
    for slot in REQUIRED_DOCS:
        path = next((os.path.join(folder, slot + e) for e in DOC_EXTS
                     if os.path.exists(os.path.join(folder, slot + e))), None)
        if not path:
            continue
        try:
            text = _extract_text(path)
        except RuntimeError as e:
            audit(caseid, "DOC_READ_FAILED",
                  "%s could not be read (%s). Fields NOT extracted; if the form's blood units "
                  "were left blank they will not be gap-filled - verify manually." % (slot, e))
            continue
        fields = parse_doc_fields(text, slot)
        if not fields:
            audit(caseid, "DOC_READ", "%s: no readable text layer (image / scanned / unsupported)" % slot)
            continue
        per_doc[slot] = fields
        for k, v in fields.items():
            flat.setdefault(k, v)
            rows.append(["DD-%d" % net_ticks(), pid, caseid, slot, k, v, now])
        audit(caseid, "DOC_READ", "%s: read %d field(s) [%s]" % (slot, len(fields), ", ".join(fields)))

    # cross-checks vs the intake form - warnings only, never a hard stop
    mism = []

    def _cmp(label, doc_val, form_val, loose=False):
        if not doc_val or not (form_val or "").strip():
            return
        a, b = doc_val.strip().lower(), str(form_val).strip().lower()
        ok = (a in b or b in a) if loose else (a == b)
        if not ok:
            mism.append((label, str(form_val), doc_val))
            rows.append(["DD-%d" % net_ticks(), pid, caseid, "_check", label,
                         "form='%s' vs document='%s'" % (form_val, doc_val), now])
            audit(caseid, "DOC_MISMATCH", "%s: form='%s' vs document='%s'" % (label, form_val, doc_val))

    _cmp("Blood group", flat.get("BloodGroup"), form.get("bloodGroup"))
    _cmp("Department", flat.get("DepartmentRequested"), form.get("department"), loose=True)
    _cmp("Emergency category", flat.get("EmergencyCategory"), form.get("emergencyType"))
    _cmp("Patient name", flat.get("IdName") or flat.get("ConsentPatient"), form.get("name"), loose=True)

    save_table("PATIENT_DOCUMENT_DATA.psv", hdr, rows)

    # gap-fill: the form wins where the user gave a value; the document fills blanks
    gap = {}
    ua = flat.get("UnitsAnticipated", "")
    if _int(form.get("bloodUnits") or 0) <= 0 and ua.isdigit() and int(ua) > 0:
        gap["bloodUnits"] = int(ua)
        audit(caseid, "DOC_DATA_APPLIED",
              "Blood units %s taken from the medical report (form left blank)." % ua)
    return per_doc, mism, gap


def process_case(pid, caseid, name, etype, dept, vent_req, blood_group, blood_units):
    """Run the coordination pipeline for one intake submission. Returns an outcome dict."""
    reqd = (dept or "General").strip()
    etype = (etype or "Standard").strip()
    blood_group = (blood_group or "O+").strip()
    blood_units = _int(blood_units)

    hdr_c, cases = load_table("EMERGENCY_CASES.psv")
    if any(r and r[0].strip() == caseid for r in cases):
        return {"caseState": "AlreadyProcessed", "message": "Case %s already exists on the board." % caseid}

    # 1. create the case row
    now = now_str()
    cases.append([caseid, pid, "Open", "Pending", "Pending", "Pending", "Pending", "0",
                  "Queued via intake console", now, now])
    save_table("EMERGENCY_CASES.psv", hdr_c, cases)
    audit(caseid, "CASE_CREATED",
          "Case %s for %s (%s), dept %s, emergency %s [intake console]" % (caseid, pid, name, reqd, etype))

    # 2. documents
    present = docs_on_file(pid)
    missing = [d for d in REQUIRED_DOCS if d not in present]
    doc_status = "Complete" if not missing else "Incomplete"
    doc_summary = ("%d/%d documents present" % (len(present), len(REQUIRED_DOCS))
                   + ((". Missing: " + ", ".join(missing)) if missing else ""))
    hdr_d, drows = load_table("DOCUMENTS.psv")
    for r in drows:
        if len(r) >= 6 and r[1].strip() == pid and r[2].strip() in REQUIRED_DOCS:
            on = r[2].strip() in present
            r[4] = "Present" if on else "Missing"
            r[5] = now if on else ""
    if hdr_d:
        save_table("DOCUMENTS.psv", hdr_d, drows)
    audit(caseid, "DOC_CHECKED", doc_summary)

    # 2b. read the documents: extract labelled fields, cross-check vs the form,
    #     fill blank form fields (blood units) from the medical report
    doc_extracted, doc_mismatches, doc_gap = extract_documents(
        pid, caseid, {"name": name, "department": reqd, "emergencyType": etype,
                      "bloodGroup": blood_group, "bloodUnits": blood_units})
    if "bloodUnits" in doc_gap:
        blood_units = doc_gap["bloodUnits"]

    # 3. bed - requested ward first, then criticality fallback
    _, beds = load_table("BEDS.psv")
    _, vents = load_table("VENTILATORS.psv")
    chain = bed_chain(reqd, etype)
    bed_row, bed_dept = None, ""
    for ward in chain:
        hit = [b for b in beds if len(b) >= 4 and b[1].strip().lower() == ward.lower()
               and b[3].strip() == "Available"]
        if not hit:
            continue
        if vent_req:
            with_vent = [b for b in hit if b[4].strip() and any(
                len(v) >= 2 and v[0].strip() == b[4].strip() and v[1].strip() == "Available" for v in vents)]
            bed_row = (with_vent or hit)[0]
        else:
            bed_row = hit[0]
        bed_dept = ward
        break
    bed_id = bed_row[0].strip() if bed_row else ""
    bed_status = "Available" if bed_row else "Unavailable"
    interim = bool(bed_row) and bed_dept.lower() != reqd.lower()
    if bed_row:
        route_note = "routed to %s (%s bed %s)" % (bed_dept, "interim" if interim else "requested", bed_id)
    else:
        route_note = "no bed in " + " / ".join(chain)
    audit(caseid, "BED_CHECKED",
          "Bed search dept=%s ventReq=%s -> %s; %s" % (reqd, vent_req, bed_status, route_note))

    # 4. ventilator
    vent_id, vent_status, vent_floating = "", "Not_Required", False
    if vent_req:
        if bed_row:
            linked = bed_row[4].strip()
            if linked and any(len(v) >= 2 and v[0].strip() == linked and v[1].strip() == "Available" for v in vents):
                vent_id, vent_status = linked, "Available"
            else:
                free = next((v for v in vents if len(v) >= 2 and v[1].strip() == "Available"), None)
                if free:
                    vent_id, vent_status, vent_floating = free[0].strip(), "Available", True
                else:
                    vent_status = "Unavailable"
        else:
            vent_status = "Unavailable"
    audit(caseid, "VENT_CHECKED", "Ventilator: %s%s" % (
        vent_status, (" (%s%s)" % (vent_id, ", portable" if vent_floating else "")) if vent_id else ""))

    # 5. blood
    _, blood = load_table("BLOOD_INVENTORY.psv")
    brow = next((r for r in blood if r and r[0].strip() == blood_group), None)
    avail = _int(brow[1]) if brow else 0
    min_thr = _int(brow[2], 3) if brow and len(brow) >= 3 else 3
    blood_status = "Available" if avail >= blood_units else "Unavailable"
    below_thr = (avail >= blood_units) and ((avail - blood_units) < min_thr)
    audit(caseid, "BLOOD_CHECKED", "Blood %s: available %d, needed %d -> %s%s" % (
        blood_group, avail, blood_units, blood_status,
        " (below threshold after reservation)" if below_thr else ""))

    # 6. care team - staffed by the ward the patient is actually placed in.
    #    A missing consultant is NOT a blocker (vision sec 5): admit, track, auto-fill.
    att_id, att_name, ct_status, ct_summary = assign_care_team(caseid, bed_dept or reqd)
    doctor_pending = ct_status != "Assigned"
    audit(caseid, "DOCTOR_PENDING" if doctor_pending else "CARE_TEAM_ASSIGNED", ct_summary)

    prio = priority_of(etype)

    # 7. readiness (CalculateReadiness.xaml)
    ok_doc = doc_status == "Complete"
    ok_bed = bed_status in ("Available", "Reserved")
    ok_vent = vent_status in ("Available", "Not_Required", "Reserved")
    ok_blood = blood_status in ("Available", "Reserved")
    score = 25 * ok_doc + 25 * ok_bed + 25 * ok_vent + 25 * ok_blood
    if score == 100 and not doctor_pending:
        final_status = "READY_FOR_APPROVAL"
    elif bed_status == "Unavailable":
        final_status = "PENDING_BED"
    elif vent_status == "Unavailable":
        final_status = "PENDING_VENTILATOR"
    elif blood_status == "Unavailable":
        final_status = "PENDING_BLOOD"
    elif doc_status == "Incomplete":
        final_status = "PENDING_DOCUMENTATION"
    elif doctor_pending:
        final_status = "PENDING_DOCTOR"
    else:
        final_status = "PENDING"
    pend_items = [t for t, ok in (
        ("Complete document verification", ok_doc),
        ("Locate available bed", ok_bed),
        ("Locate available ventilator", ok_vent),
        ("Secure blood inventory", ok_blood),
        ("Assign on-call consultant", not doctor_pending),
    ) if not ok]
    pending_action = "; ".join(pend_items) if pend_items else "None"
    audit(caseid, "READINESS_CALC",
          "Readiness %d%% - %s | pending: %s" % (score, final_status, pending_action))

    # 8. approval + reservation.  Admit as soon as there is a bed + documents;
    #    doctor / blood / ventilator still being sourced become PENDING_REQUIREMENTS
    #    rows that the background monitor fulfils automatically - never a queue.
    auto = config_flag("AutoApproveWhenReady", True)
    write_approval_artifact(caseid, name, reqd, etype, score, final_status,
                            pending_action, bed_id, bed_dept, interim)
    admit_now = auto and bed_row is not None and doc_status == "Complete"

    if admit_now:
        blood_reserved = blood_status == "Available"
        vent_reserved = vent_req and vent_status == "Available"
        reserve_resources(caseid, bed_id, vent_id, vent_reserved, blood_group,
                          blood_units if blood_reserved else 0, vent_floating)
        adm_id, adm_summary = confirm_admission(caseid, pid, bed_id, att_id, etype, vent_id, vent_reserved)

        outstanding = []
        if interim:
            audit(caseid, "TEMP_BED_ASSIGNED",
                  "Temporary bed %s in %s (requested %s); ward-transfer requirement opened."
                  % (bed_id, bed_dept, reqd))
            register_requirement(caseid, pid, "ICU_BED" if reqd.upper() == "ICU" else "BED",
                                 reqd, bed_dept, prio)
            outstanding.append("in a temporary %s bed - transfer to %s pending" % (bed_dept, reqd))
        if doctor_pending:
            register_requirement(caseid, pid, "DOCTOR", (bed_dept or reqd), "", prio)
            outstanding.append("on-call %s consultant pending" % (bed_dept or reqd))
        if not blood_reserved and blood_units > 0:
            register_requirement(caseid, pid, "BLOOD", "%s x%d" % (blood_group, blood_units), "", prio)
            outstanding.append("blood %s short (%d/%d) - cross-match in progress"
                               % (blood_group, avail, blood_units))
        if vent_req and not vent_reserved:
            register_requirement(caseid, pid, "VENTILATOR", "ventilator", "", prio)
            outstanding.append("ventilator being sourced")

        pa = "; ".join(outstanding) if outstanding else "None"
        update_case(caseid, pid, "Admitted", doc_status, "Reserved",
                    "Reserved" if vent_reserved else vent_status,
                    "Reserved" if blood_reserved else blood_status, score, pa)
        audit(caseid, "RESOURCES_RESERVED",
              "Reserved bed %s%s, vent %s, blood %s x%d, attending %s"
              % (bed_id, " (interim " + bed_dept + ")" if interim else "", vent_id or "N/A",
                 blood_group, blood_units if blood_reserved else 0, att_name or "PENDING"))
        audit(caseid, "ADMISSION_CONFIRMED", "%s: %s" % (adm_id, adm_summary))
        state, admitted = "Admitted", True
        if interim:
            msg = ("%s admitted to a temporary %s bed (%s) - %s was full; the system will transfer "
                   "the patient automatically when a bed frees." % (caseid, bed_dept, bed_id, reqd))
        else:
            msg = "%s admitted to bed %s in %s." % (caseid, bed_id, bed_dept)
        extra = [o for o in outstanding if "temporary" not in o]
        if extra:
            msg += " Being sourced: " + "; ".join(extra) + "."
    else:
        held = final_status if auto else "READY_FOR_APPROVAL"
        pa = pending_action
        if bed_status == "Unavailable":
            register_requirement(caseid, pid, "ICU_BED" if reqd.upper() == "ICU" else "BED", reqd, "", prio)
        if doctor_pending:
            register_requirement(caseid, pid, "DOCTOR", (bed_dept or reqd), "", prio)
        if bed_row is not None and interim:
            pa = (pa + "; " if pa != "None" else "") + "interim %s bed identified" % bed_dept
        update_case(caseid, pid, held, doc_status, bed_status, vent_status, blood_status, score, pa)
        state, admitted, adm_id = held, False, ""
        msg = "%s registered - %s (%d%%). Coordinating: %s" % (caseid, held, score, pending_action)

    audit(caseid, "CASE_CLOSED",
          "Intake processing complete. Score %d%% %s admitted=%s" % (score, final_status, admitted))
    mark_input_processed(pid, caseid, state)

    return {
        "caseState": state, "readiness": score, "admitted": admitted,
        "admissionId": adm_id if admit_now else "",
        "bedId": bed_id, "bedWard": bed_dept, "requestedWard": reqd, "interimBed": interim,
        "doctorPending": doctor_pending, "pendingAction": pa, "message": msg,
    }


# ============================================================================
# Pending-requirement tracking + automatic fulfilment (vision sec 7-9)
# ============================================================================
PRIORITY = {"CRITICAL": "HIGH", "URGENT": "MEDIUM", "STANDARD": "LOW"}
_PRIO_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def priority_of(etype):
    return PRIORITY.get((etype or "").strip().upper(), "LOW")


def ward_label(ward, bed_type, bed_id):
    """Patient-facing name for a bed. A Premium bed in General reads as 'Private Ward'."""
    if not bed_id:
        return "-"
    w = (ward or "").strip()
    if w.lower() == "general" and (bed_type or "").strip().lower() == "premium":
        return "Private Ward - %s" % bed_id
    if w.lower() == "icu":
        return "ICU - %s" % bed_id
    return "%s Ward - %s" % (w, bed_id) if w else bed_id


def register_requirement(caseid, pid, rtype, requested, fallback, priority):
    """Open a persistent unmet-requirement row (idempotent per case+type)."""
    hdr, rows = load_table("PENDING_REQUIREMENTS.psv")
    if not hdr:
        hdr = DB_SCHEMA["PENDING_REQUIREMENTS"]
    for r in rows:
        if len(r) >= 8 and r[1].strip() == caseid and r[3].strip() == rtype \
                and r[7].strip() in ("OPEN", "ACTION_REQUIRED"):
            return r[0].strip()
    now = now_str()
    rid = "REQ-%d" % net_ticks()
    rows.append([rid, caseid, pid, rtype, requested, fallback, priority, "OPEN", now, now, ""])
    save_table("PENDING_REQUIREMENTS.psv", hdr, rows)
    audit(caseid, "REQUIREMENT_OPENED",
          "%s requirement opened (requested %s, priority %s)" % (rtype, requested or "-", priority))
    return rid


def set_requirement_status(rid, status):
    hdr, rows = load_table("PENDING_REQUIREMENTS.psv")
    now = now_str()
    for r in rows:
        if r and r[0].strip() == rid and len(r) >= 11:
            r[7] = status
            r[9] = now
            if status in ("FULFILLED", "CANCELLED"):
                r[10] = now
    save_table("PENDING_REQUIREMENTS.psv", hdr, rows)


def open_requirements():
    _, rows = load_table("PENDING_REQUIREMENTS.psv")
    return [r for r in rows if len(r) >= 8 and r[7].strip() in ("OPEN", "ACTION_REQUIRED")]


def _adm_row_for(caseid):
    hdr, rows = load_table("ADMISSIONS.psv")
    for r in rows:
        if len(r) >= 8 and r[1].strip() == caseid:
            return hdr, rows, r
    return hdr, rows, None


def _case_ward(caseid):
    """The ward the patient is currently physically in (from ADMISSIONS.BedId -> BEDS)."""
    _, _, a = _adm_row_for(caseid)
    if not a:
        return "", "", ""
    bed_id = a[3].strip()
    _, beds = load_table("BEDS.psv")
    for b in beds:
        if b and b[0].strip() == bed_id and len(b) >= 3:
            return bed_id, b[1].strip(), b[2].strip()
    return bed_id, "", ""


def transfer_bed(req_row):
    """Move an admitted patient from their temporary bed into a now-free bed in the
    requested ward. Concurrency-safe: re-checks availability immediately before writing."""
    rid, caseid, pid, _rtype, requested = (req_row[0].strip(), req_row[1].strip(),
                                           req_row[2].strip(), req_row[3].strip(), req_row[4].strip())
    hdr_a, adm_rows, a = _adm_row_for(caseid)
    if not a:
        return False, "no admission row"
    old_bed = a[3].strip()

    hdr_b, beds = load_table("BEDS.psv")
    old = next((b for b in beds if b and b[0].strip() == old_bed), None)
    old_vent = old[4].strip() if old and len(old) >= 5 else ""
    vent_needed = old_vent and any(
        len(v) >= 2 and v[0].strip() == old_vent and v[1].strip() in ("Reserved", "Occupied")
        for v in load_table("VENTILATORS.psv")[1])

    # pick a free bed in the requested ward (prefer one with its own available vent if needed)
    cands = [b for b in beds if len(b) >= 4 and b[1].strip().lower() == requested.lower()
             and b[3].strip() == "Available"]
    if not cands:
        return False, "no free bed in %s yet" % requested
    hdr_v, vents = load_table("VENTILATORS.psv")
    if vent_needed:
        withv = [b for b in cands if b[4].strip() and any(
            len(v) >= 2 and v[0].strip() == b[4].strip() and v[1].strip() == "Available" for v in vents)]
        target = (withv or cands)[0]
    else:
        target = cands[0]
    new_bed = target[0].strip()
    now = now_str()

    # target bed -> Occupied; free the old bed
    for b in beds:
        if b[0].strip() == new_bed and len(b) >= 6:
            b[3] = "Occupied"
            if vent_needed and not b[4].strip():
                b[4] = old_vent
            b[5] = now
        elif b[0].strip() == old_bed and len(b) >= 6:
            b[3] = "Available"
            b[4] = "" if vent_needed else b[4]
            b[5] = now
    save_table("BEDS.psv", hdr_b, beds)

    # if the target bed has its own linked vent, use it and release the portable one
    if vent_needed:
        linked = target[4].strip()
        for v in vents:
            if len(v) < 4:
                continue
            if linked and v[0].strip() == linked and linked != old_vent:
                v[1] = "Occupied"; v[3] = now
            elif linked and linked != old_vent and v[0].strip() == old_vent:
                v[1] = "Available"; v[3] = now
        save_table("VENTILATORS.psv", hdr_v, vents)

    # ADMISSIONS -> new bed
    for r in adm_rows:
        if r[1].strip() == caseid and len(r) >= 4:
            r[3] = new_bed
    save_table("ADMISSIONS.psv", hdr_a, adm_rows)

    # reservation ledger
    append_row("RESOURCE_RESERVATIONS.psv", [str(net_ticks()), caseid, "Bed", new_bed, "1", "Reserved", now])
    hdr_rr, rr = load_table("RESOURCE_RESERVATIONS.psv")
    for r in rr:
        if len(r) >= 6 and r[1].strip() == caseid and r[2].strip() == "Bed" \
                and r[3].strip() == old_bed and r[5].strip() in ("Reserved", "Occupied"):
            r[5] = "Released"
    save_table("RESOURCE_RESERVATIONS.psv", hdr_rr, rr)

    # EMERGENCY_CASES pending-action: drop the transfer note; recompute
    hdr_c, cases = load_table("EMERGENCY_CASES.psv")
    for r in cases:
        if r and r[0].strip() == caseid and len(r) >= 11:
            others = [p for p in _split_pa(r[8]) if "temporary" not in p.lower() and "transfer to" not in p.lower()]
            r[8] = "; ".join(others) if others else "None"
            r[10] = now
    save_table("EMERGENCY_CASES.psv", hdr_c, cases)

    set_requirement_status(rid, "FULFILLED")
    _delete_signal("TRANSFER_CONFIRM_%s.txt" % caseid)
    _delete_signal("TRANSFER_REQUEST_%s.txt" % caseid)
    audit(caseid, "BED_TRANSFERRED",
          "Moved from temporary bed %s to %s bed %s." % (old_bed, requested, new_bed))
    audit(caseid, "TEMP_BED_RELEASED", "Temporary bed %s released back to the pool." % old_bed)
    audit(caseid, "REQUIREMENT_FULFILLED",
          "%s bed requirement %s fulfilled: %s now in %s bed %s." % (requested, rid, caseid, requested, new_bed))
    if requested.upper() == "ICU":
        audit(caseid, "ICU_ALLOCATED", "ICU bed %s allocated; requirement closed." % new_bed)
    return True, new_bed


def fulfil_doctor(req_row):
    """Assign an on-call consultant that has become available; fill ADMISSIONS + close."""
    rid, caseid, pid, ward = (req_row[0].strip(), req_row[1].strip(),
                              req_row[2].strip(), req_row[4].strip())
    att_id, att_name, ct_status, ct_summary = assign_care_team(caseid, ward)
    if ct_status != "Assigned":
        return False, "still no on-call %s consultant" % ward
    hdr_a, rows, a = _adm_row_for(caseid)
    if a and len(a) >= 5:
        a[4] = att_id
        save_table("ADMISSIONS.psv", hdr_a, rows)
    set_requirement_status(rid, "FULFILLED")
    audit(caseid, "DOCTOR_ASSIGNED", "%s (auto-assigned when consultant became available)." % ct_summary)
    _recompute_pending(caseid)
    return True, att_name


def fulfil_blood(req_row):
    rid, caseid = req_row[0].strip(), req_row[1].strip()
    m = re.match(r"\s*([A-Za-z+-]+)\s*x\s*(\d+)", req_row[4])
    if not m:
        return False, "bad requirement value"
    bg, units = m.group(1), int(m.group(2))
    hdr_bl, blood = load_table("BLOOD_INVENTORY.psv")
    row = next((r for r in blood if r and r[0].strip() == bg), None)
    if not row or _int(row[1]) < units:
        return False, "%s still short" % bg
    now = now_str()
    for r in blood:
        if r and r[0].strip() == bg and len(r) >= 4:
            r[1] = str(max(0, _int(r[1]) - units))
            r[3] = now
    save_table("BLOOD_INVENTORY.psv", hdr_bl, blood)
    append_row("RESOURCE_RESERVATIONS.psv", [str(net_ticks()), caseid, "Blood", bg, str(units), "Reserved", now])
    hdr_c, cases = load_table("EMERGENCY_CASES.psv")
    for r in cases:
        if r and r[0].strip() == caseid and len(r) >= 11:
            r[6] = "Reserved"
            r[10] = now_str()
    save_table("EMERGENCY_CASES.psv", hdr_c, cases)
    set_requirement_status(rid, "FULFILLED")
    audit(caseid, "REQUIREMENT_FULFILLED", "Blood %s x%d reserved (stock replenished)." % (bg, units))
    _recompute_pending(caseid)
    return True, "%s x%d" % (bg, units)


def fulfil_vent(req_row):
    rid, caseid = req_row[0].strip(), req_row[1].strip()
    _, vents = load_table("VENTILATORS.psv")
    free = next((v for v in vents if len(v) >= 2 and v[1].strip() == "Available"), None)
    if not free:
        return False, "no ventilator free"
    vid = free[0].strip()
    bed_id, _, _ = _case_ward(caseid)
    now = now_str()
    hdr_v, vents = load_table("VENTILATORS.psv")
    for v in vents:
        if v[0].strip() == vid and len(v) >= 4:
            v[1] = "Occupied"; v[3] = now
    save_table("VENTILATORS.psv", hdr_v, vents)
    if bed_id:
        hdr_b, beds = load_table("BEDS.psv")
        for b in beds:
            if b[0].strip() == bed_id and len(b) >= 6 and not b[4].strip():
                b[4] = vid; b[5] = now
        save_table("BEDS.psv", hdr_b, beds)
    append_row("RESOURCE_RESERVATIONS.psv", [str(net_ticks()), caseid, "Ventilator", vid, "1", "Reserved", now])
    hdr_c, cases = load_table("EMERGENCY_CASES.psv")
    for r in cases:
        if r and r[0].strip() == caseid and len(r) >= 11:
            r[5] = "Reserved"; r[10] = now
    save_table("EMERGENCY_CASES.psv", hdr_c, cases)
    set_requirement_status(rid, "FULFILLED")
    audit(caseid, "REQUIREMENT_FULFILLED", "Ventilator %s allocated." % vid)
    _recompute_pending(caseid)
    return True, vid


def _split_pa(s):
    return [p.strip() for p in str(s or "").split(";") if p.strip() and p.strip().lower() != "none"]


def _recompute_pending(caseid):
    """Rebuild EMERGENCY_CASES.PendingAction from the case's still-open requirements."""
    open_for = [r for r in open_requirements() if r[1].strip() == caseid]
    labels = {"ICU_BED": "ICU bed transfer pending", "BED": "ward transfer pending",
              "DOCTOR": "on-call consultant pending", "BLOOD": "blood cross-match pending",
              "VENTILATOR": "ventilator pending"}
    items = [labels.get(r[3].strip(), r[3].strip()) for r in open_for]
    hdr_c, cases = load_table("EMERGENCY_CASES.psv")
    for r in cases:
        if r and r[0].strip() == caseid and len(r) >= 11:
            r[8] = "; ".join(items) if items else "None"
            r[10] = now_str()
    save_table("EMERGENCY_CASES.psv", hdr_c, cases)


def _signal_path(fname):
    return os.path.join(ROOT, "Data", "Notifications", fname)


def _signal_exists(fname):
    return os.path.exists(_signal_path(fname))


def _delete_signal(fname):
    try:
        os.remove(_signal_path(fname))
    except OSError:
        pass


def monitor_tick(auto_confirm=False):
    """One pass of the availability monitor. Earliest valid request first. Never allocates
    more beds than are actually free (this tick or across ticks); admits held patients
    straight into a freed bed; routes temp->requested-ward moves through the confirm
    gate; reverts an ACTION_REQUIRED flag if the bed is taken before it is confirmed.

    auto_confirm=True is used right after an admin release / discharge approval: the admin
    is the human authorisation, so the follow-on bed transfer runs immediately instead of
    raising a second ACTION_REQUIRED gate (revised spec Feature 3 - fully automatic)."""
    reqs = open_requirements()
    if not reqs:
        return 0
    # Revised spec: EARLIEST VALID REQUEST FIRST - order by RequirementCreatedAt (r[8]),
    # priority only as a tie-breaker. Set PendingAllocationOrder|priority to flip it back.
    if config_get("PendingAllocationOrder", "fifo").strip().lower() == "priority":
        reqs.sort(key=lambda r: (_PRIO_RANK.get(r[6].strip(), 3), r[8], r[0]))
    else:
        reqs.sort(key=lambda r: (r[8], _PRIO_RANK.get(r[6].strip(), 3), r[0]))
    require_confirm = config_flag("RequireTransferConfirmation", True)
    auto_doc = config_flag("AutoAssignDoctorWhenFree", True)
    acted = 0
    committed = {}   # ward(lower) -> beds spoken-for during this tick
    _, _cases = load_table("EMERGENCY_CASES.psv")
    case_status = {c[0].strip(): c[2].strip() for c in _cases if len(c) >= 3}

    for r in reqs:
        rtype, status, caseid, rid = r[3].strip(), r[7].strip(), r[1].strip(), r[0].strip()
        cstat = case_status.get(caseid, "").upper()
        if cstat in ("DISCHARGED", "CLOSED", "ERROR", "REJECTED"):
            set_requirement_status(rid, "CANCELLED")
            continue
        if caseid not in case_status:
            # No case row seen this pass - a transient read glitch or a genuine
            # orphan. NEVER allocate a resource (bed / blood / doctor / vent) to a
            # case that doesn't exist; leave the row OPEN for a later pass rather
            # than cancelling what might be a live patient mid-write.
            print("  [monitor] %s: no EMERGENCY_CASES row this pass; %s left OPEN" % (caseid, rid))
            continue
        try:
            if rtype in ("ICU_BED", "BED"):
                ward = r[4].strip()
                _, beds = load_table("BEDS.psv")
                free_now = sum(1 for b in beds if len(b) >= 4 and b[1].strip().lower() == ward.lower()
                               and b[3].strip() == "Available")
                free_left = free_now - committed.get(ward.lower(), 0)
                if free_left <= 0:
                    if status == "ACTION_REQUIRED" and not _signal_exists("TRANSFER_CONFIRM_%s.txt" % caseid):
                        set_requirement_status(rid, "OPEN")
                        audit(caseid, "REQUIREMENT_REOPENED",
                              "%s bed no longer free before confirmation; back to monitoring." % ward)
                    continue
                admitted = _adm_row_for(caseid)[2] is not None
                if not admitted:
                    if _admit_held_into_ward(r):
                        committed[ward.lower()] = committed.get(ward.lower(), 0) + 1
                        acted += 1
                    continue
                if status == "ACTION_REQUIRED" and _signal_exists("TRANSFER_CONFIRM_%s.txt" % caseid):
                    ok, _i = transfer_bed(r)
                    if ok:
                        committed[ward.lower()] = committed.get(ward.lower(), 0) + 1
                        acted += 1
                elif status == "OPEN" and (auto_confirm or not require_confirm):
                    ok, _i = transfer_bed(r)
                    if ok:
                        committed[ward.lower()] = committed.get(ward.lower(), 0) + 1
                        acted += 1
                elif status == "ACTION_REQUIRED" and auto_confirm:
                    ok, _i = transfer_bed(r)
                    if ok:
                        committed[ward.lower()] = committed.get(ward.lower(), 0) + 1
                        acted += 1
                elif status == "OPEN" and require_confirm:
                    set_requirement_status(rid, "ACTION_REQUIRED")
                    _write_signal_request(caseid, ward)
                    audit(caseid, "ICU_AVAILABLE_ACTION_REQUIRED",
                          "%s bed available; authorised-staff confirmation required for transfer." % ward)
                    committed[ward.lower()] = committed.get(ward.lower(), 0) + 1
                    acted += 1
                else:   # ACTION_REQUIRED, still waiting on a human -> hold the bed for it
                    committed[ward.lower()] = committed.get(ward.lower(), 0) + 1
            elif rtype == "DOCTOR" and auto_doc:
                ok, _i = fulfil_doctor(r)
                acted += 1 if ok else 0
            elif rtype == "BLOOD":
                ok, _i = fulfil_blood(r)
                acted += 1 if ok else 0
            elif rtype == "VENTILATOR":
                ok, _i = fulfil_vent(r)
                acted += 1 if ok else 0
        except Exception as e:  # noqa: BLE001 - one bad requirement must not stop the pass, but it must be LOUD
            print("  [monitor] %s %s: %s" % (caseid, rtype, e))
            try:
                audit(caseid, "AUTOMATIC_ALLOCATION_FAILED",
                      "Auto-allocation of %s for %s errored and was left for the next pass: %s: %s"
                      % (rtype, caseid, type(e).__name__, e))
            except Exception:  # noqa: BLE001
                pass
    return acted


def _admit_held_into_ward(req_row):
    """A held (never-admitted) case whose requested ward now has a free bed: complete
    the admission into it right now. Any still-missing doctor / blood / ventilator
    become their own PENDING_REQUIREMENTS rows."""
    rid, caseid, pid, ward = (req_row[0].strip(), req_row[1].strip(),
                              req_row[2].strip(), req_row[4].strip())
    hdr_c, cases = load_table("EMERGENCY_CASES.psv")
    crow = next((r for r in cases if r and r[0].strip() == caseid), None)
    if not crow or crow[2].strip() in ("Admitted", "IN_TREATMENT", "FIT_FOR_DISCHARGE", "DISCHARGED", "CLOSED"):
        return False
    _, pats = load_table("PATIENTS.psv")
    prow = next((r for r in pats if r and r[0].strip() == pid), None)
    if not prow or len(prow) < 9:
        return False
    etype = prow[4].strip() or "Standard"
    vent_req = prow[6].strip() in ("1", "Yes", "yes", "True", "true")
    bg, units = prow[7].strip() or "O+", _int(prow[8])

    hdr_b, beds = load_table("BEDS.psv")
    _, vents = load_table("VENTILATORS.psv")
    cands = [b for b in beds if len(b) >= 4 and b[1].strip().lower() == ward.lower()
             and b[3].strip() == "Available"]
    if not cands:
        return False
    if vent_req:
        withv = [b for b in cands if b[4].strip() and any(
            len(v) >= 2 and v[0].strip() == b[4].strip() and v[1].strip() == "Available" for v in vents)]
        target = (withv or cands)[0]
    else:
        target = cands[0]
    bed_id = target[0].strip()

    vent_id, vent_status, vent_floating = "", "Not_Required", False
    if vent_req:
        linked = target[4].strip()
        if linked and any(len(v) >= 2 and v[0].strip() == linked and v[1].strip() == "Available" for v in vents):
            vent_id, vent_status = linked, "Available"
        else:
            free = next((v for v in vents if len(v) >= 2 and v[1].strip() == "Available"), None)
            if free:
                vent_id, vent_status, vent_floating = free[0].strip(), "Available", True
            else:
                vent_status = "Unavailable"

    _, blood = load_table("BLOOD_INVENTORY.psv")
    brow = next((r for r in blood if r and r[0].strip() == bg), None)
    blood_reserved = bool(brow) and _int(brow[1]) >= units
    att_id, att_name, ct_status, _s = assign_care_team(caseid, ward)
    doctor_pending = ct_status != "Assigned"
    vent_reserved = vent_req and vent_status == "Available"

    reserve_resources(caseid, bed_id, vent_id, vent_reserved, bg,
                      units if blood_reserved else 0, vent_floating)
    adm_id, adm_summary = confirm_admission(caseid, pid, bed_id, att_id, etype, vent_id, vent_reserved)
    set_requirement_status(rid, "FULFILLED")

    prio = priority_of(etype)
    if doctor_pending:
        register_requirement(caseid, pid, "DOCTOR", ward, "", prio)
    if not blood_reserved and units > 0:
        register_requirement(caseid, pid, "BLOOD", "%s x%d" % (bg, units), "", prio)
    if vent_req and not vent_reserved:
        register_requirement(caseid, pid, "VENTILATOR", "ventilator", "", prio)

    score = 25 + 25 + 25 * (vent_status in ("Available", "Not_Required")) + 25 * blood_reserved
    now = now_str()
    for r in cases:
        if r and r[0].strip() == caseid and len(r) >= 11:
            r[2] = "Admitted"
            r[4] = "Reserved"
            r[5] = "Reserved" if vent_reserved else vent_status
            r[6] = "Reserved" if blood_reserved else (r[6].strip() or "Pending")
            r[7] = str(score)
            r[10] = now
    save_table("EMERGENCY_CASES.psv", hdr_c, cases)
    audit(caseid, "ADMISSION_CONFIRMED",
          "%s: %s (admitted the moment a %s bed became available)." % (adm_id, adm_summary, ward))
    audit(caseid, "REQUIREMENT_FULFILLED",
          "%s bed requirement %s fulfilled: held case %s admitted into %s bed %s." % (ward, rid, caseid, ward, bed_id))
    _recompute_pending(caseid)
    return True


def _write_signal_request(caseid, ward):
    try:
        os.makedirs(os.path.join(ROOT, "Data", "Notifications"), exist_ok=True)
        with open(_signal_path("TRANSFER_REQUEST_%s.txt" % caseid), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join([
                "ACTION REQUIRED - authorised staff",
                "Case: %s" % caseid,
                "A %s bed is now available." % ward,
                "The patient is currently in a temporary bed.",
                "Confirm the transfer on the admin dashboard, or drop a file named",
                "  TRANSFER_CONFIRM_%s.txt" % caseid,
                "in this folder to authorise it.",
                "Raised: %s" % now_str(),
            ]) + "\n")
    except OSError:
        pass


MONITOR_STOP = threading.Event()


def monitor_loop():
    interval = max(2, _int(config_get("MonitorIntervalSeconds", "5"), 5))
    billing_every = _int(config_get("BillingAccrualEverySeconds", "0"), 0)
    last_bill = 0.0
    while not MONITOR_STOP.wait(interval):
        try:
            with PROCESS_LOCK:
                n = monitor_tick()
                if billing_every > 0 and (datetime.datetime.now().timestamp() - last_bill) >= billing_every:
                    accrue_stay_charges()
                    last_bill = datetime.datetime.now().timestamp()
            if n:
                print("  [monitor] fulfilled/advanced %d requirement(s)" % n)
        except Exception as e:  # noqa: BLE001
            print("  [monitor] tick error: %s: %s" % (type(e).__name__, e))


def accrue_stay_charges():
    """Optional in-stay billing tick (mirror of AccrueCharges.xaml). Off unless
    BillingAccrualEverySeconds > 0. Adds one bed-day + doctor fee per admitted case,
    capped at ExpectedStayDays."""
    hdr_a, adm = load_table("ADMISSIONS.psv")
    _, beds = load_table("BEDS.psv")
    _, billing = load_table("BILLING.psv")
    bed_type = {b[0].strip(): (b[2].strip() if len(b) >= 3 else "Standard") for b in beds if b}
    for a in adm:
        if len(a) < 8 or a[7].strip() != "Admitted":
            continue
        caseid = a[1].strip()
        days_billed = sum(1 for x in billing if len(x) >= 3 and x[1].strip() == caseid and x[2].strip() == "BedDay")
        expected = _int(a[6], 10)
        if days_billed >= expected:
            continue
        nxt = days_billed + 1
        rate = 8000 if bed_type.get(a[3].strip(), "Standard").upper() == "PREMIUM" else 4000
        now = now_str()
        append_row("BILLING.psv", ["BIL-%s-BED%d" % (caseid, nxt), caseid, "BedDay",
                                   "Bed %s - day %d" % (a[3].strip(), nxt), "1", str(rate), str(rate), now])
        append_row("BILLING.psv", ["BIL-%s-DF%d" % (caseid, nxt), caseid, "DoctorFee",
                                   "Attending review - day %d" % nxt, "1", "1500", "1500", now])
        audit(caseid, "CHARGES_ACCRUED", "Day %d charges posted (bed %d + doctor fee 1500)." % (nxt, rate))


# ============================================================================
# Live state snapshot for the no-reload dashboards  (GET /api/state)
# ============================================================================
def progressive_status(case_status, admitted, my_open_reqs):
    u = (case_status or "").strip().upper()
    named = {"IN_TREATMENT": "ADMITTED - IN TREATMENT", "FIT_FOR_DISCHARGE": "FIT FOR DISCHARGE",
             "DISCHARGED": "DISCHARGED", "CLOSED": "CASE CLOSED", "ERROR": "NEEDS ATTENTION"}
    if u in named:
        return named[u]
    types = {r["type"] for r in my_open_reqs}
    if admitted and any(r["type"] in ("ICU_BED", "BED") and r["status"] == "ACTION_REQUIRED"
                        for r in my_open_reqs):
        want = next(r["requested"] for r in my_open_reqs if r["type"] in ("ICU_BED", "BED"))
        return "%s AVAILABLE - ACTION REQUIRED" % want.upper()
    if admitted:
        if "ICU_BED" in types or "BED" in types:
            return "TEMPORARY BED ASSIGNED"
        if "DOCTOR" in types:
            return "ADMITTED - AWAITING DOCTOR"
        if types:
            return "ADMITTED - FINALISING RESOURCES"
        return "ADMITTED"
    if {"ICU_BED", "BED"} & types:
        return "PROCESSING - LOCATING BED"
    return "PROCESSING"


def build_state():
    """Everything the two live dashboards need, as plain JSON."""
    _, cases = load_table("EMERGENCY_CASES.psv")
    _, pats = load_table("PATIENTS.psv")
    _, adm = load_table("ADMISSIONS.psv")
    _, beds = load_table("BEDS.psv")
    _, vents = load_table("VENTILATORS.psv")
    _, blood = load_table("BLOOD_INVENTORY.psv")
    _, docs = load_table("DOCTORS.psv")
    _, billing = load_table("BILLING.psv")
    _, audit_rows = load_table("AUDIT_LOG.psv")
    _, dd_rows = load_table("PATIENT_DOCUMENT_DATA.psv")
    preq = open_requirements()

    doc_by_case, doc_checks = {}, []
    for r in dd_rows:
        if len(r) < 6:
            continue
        cid = r[2].strip()
        if r[3].strip() == "_check":
            doc_checks.append((cid, r[4].strip(), r[5].strip()))
        else:
            doc_by_case.setdefault(cid, {})[r[4].strip()] = r[5].strip()

    pat = {r[0].strip(): r for r in pats if r}
    adm_by_case = {r[1].strip(): r for r in adm if len(r) >= 8}
    bed_by_id = {r[0].strip(): r for r in beds if r}
    doc_name = {r[0].strip(): r[1].strip() for r in docs if len(r) >= 2}
    doc_spec = {r[0].strip(): (r[4].strip() if len(r) >= 5 else "") for r in docs if r}

    bill_by_case = {}
    for r in billing:
        if len(r) >= 7:
            bill_by_case[r[1].strip()] = bill_by_case.get(r[1].strip(), 0) + _int(r[6])

    tl = {}
    for r in sorted(audit_rows, key=lambda x: _int(x[0]) if x and x[0].strip().lstrip("-").isdigit() else 0):
        if len(r) >= 6:
            tl.setdefault(r[1].strip(), []).append(
                {"ts": r[4].strip(), "action": r[2].strip(), "desc": r[3].strip(), "by": r[5].strip()})

    reqs_json = [{"id": r[0].strip(), "caseId": r[1].strip(), "patientId": r[2].strip(),
                  "type": r[3].strip(), "requested": r[4].strip(), "fallback": r[5].strip(),
                  "priority": r[6].strip(), "status": r[7].strip(),
                  "createdAt": r[8].strip(), "updatedAt": r[9].strip()} for r in preq]
    reqs_by_case = {}
    for rj in reqs_json:
        reqs_by_case.setdefault(rj["caseId"], []).append(rj)

    cases_json = []
    for r in cases:
        if len(r) < 11:
            continue
        cid, pid, cs = r[0].strip(), r[1].strip(), r[2].strip()
        p = pat.get(pid, [])
        req_ward = p[5].strip() if len(p) >= 6 else ""
        etype = p[4].strip() if len(p) >= 5 else ""
        a = adm_by_case.get(cid)
        cur_bed = a[3].strip() if a else ""
        att = a[4].strip() if a and len(a) >= 5 else ""
        b = bed_by_id.get(cur_bed)
        cur_ward = b[1].strip() if b else ""
        my_reqs = reqs_by_case.get(cid, [])
        cases_json.append({
            "caseId": cid, "patientId": pid, "name": (p[1].strip() if len(p) >= 2 else pid),
            "age": (p[2].strip() if len(p) >= 3 else ""), "gender": (p[3].strip() if len(p) >= 4 else ""),
            "emergencyType": etype, "priority": priority_of(etype),
            "caseStatus": cs, "readiness": _int(r[7]), "pendingAction": r[8].strip(),
            "docStatus": r[3].strip(), "bedStatus": r[4].strip(),
            "ventStatus": r[5].strip(), "bloodStatus": r[6].strip(),
            "requestedWard": req_ward,
            "currentBed": cur_bed,
            "currentBedLabel": ward_label(cur_ward, (b[2].strip() if b and len(b) >= 3 else ""), cur_bed),
            "currentWard": cur_ward,
            "attendingDoctorId": att, "attendingDoctorName": doc_name.get(att, ""),
            "attendingSpecialty": doc_spec.get(att, ""),
            "admitted": bool(a),
            "bill": bill_by_case.get(cid, 0),
            "billStatus": "PENDING" if bill_by_case.get(cid, 0) else "-",
            "openRequirements": my_reqs,
            "progressiveStatus": progressive_status(cs, bool(a), my_reqs),
            "updatedAt": r[10].strip(),
            "timeline": tl.get(cid, [])[-50:],
            "docData": doc_by_case.get(cid, {}),
        })

    beds_by_ward = {}
    for b in beds:
        if len(b) >= 4:
            w = b[1].strip()
            beds_by_ward.setdefault(w, {"free": 0, "total": 0})
            beds_by_ward[w]["total"] += 1
            if b[3].strip() == "Available":
                beds_by_ward[w]["free"] += 1

    def _nm(pid):
        row = pat.get(pid)
        return row[1].strip() if row and len(row) >= 2 else pid

    alerts = []
    for rj in reqs_json:
        nm = _nm(rj["patientId"])
        if rj["status"] == "ACTION_REQUIRED":
            alerts.append({"sev": "ACTION", "caseId": rj["caseId"],
                           "title": "%s - %s bed available, confirmation required" % (rj["caseId"], rj["requested"]),
                           "body": "%s is in a temporary bed. Authorised staff must confirm the move to %s."
                                   % (nm, rj["requested"])})
        elif rj["priority"] == "HIGH":
            alerts.append({"sev": "HIGH", "caseId": rj["caseId"],
                           "title": "%s - %s not fulfilled" % (rj["caseId"], rj["type"].replace("_", " ")),
                           "body": "%s: requested %s unavailable. Monitoring; auto-fulfil on availability change."
                                   % (nm, rj["requested"] or rj["type"].replace("_", " ").lower())})
    for r in cases:
        if len(r) >= 9 and r[2].strip() == "Error":
            alerts.append({"sev": "ERROR", "caseId": r[0].strip(),
                           "title": "%s - processing error" % r[0].strip(), "body": r[8].strip()})
    for r in blood:
        # at-or-below the reserve threshold (matches the dashboard "running low" list).
        if len(r) >= 3 and _int(r[1]) <= _int(r[2]):
            alerts.append({"sev": "HIGH", "caseId": "",
                           "title": "Blood %s at/below threshold" % r[0].strip(),
                           "body": "%s units available, minimum %s. Restock this group first." % (r[1].strip(), r[2].strip())})
    for cid, label, detail in doc_checks:
        alerts.append({"sev": "WARN", "caseId": cid,
                       "title": "%s - document does not match the form" % cid,
                       "body": "%s: %s. The form value is used; please verify." % (label, detail)})
    # F13: a discharge whose bill could not be emailed - surfaced from the DURABLE
    # EMAIL_RETRY_<case>.txt marker (not a tail scan that scrolls away), so the
    # operator sees it until they actually retry.
    try:
        _notif = os.path.join(ROOT, "Data", "Notifications")
        for f in (os.listdir(_notif) if os.path.isdir(_notif) else []):
            if f.startswith("EMAIL_RETRY_") and f.endswith(".txt"):
                cid = f[len("EMAIL_RETRY_"):-4]
                alerts.append({"sev": "WARN", "caseId": cid,
                               "title": "%s - discharge bill not emailed" % (cid or "bill"),
                               "body": "The final bill could not be emailed. Discharge is complete; "
                                       "use the retry button (POST /api/retry-bill-email)."})
    except OSError:
        pass
    # a bed force-vacated by an admin without discharge paperwork - needs finishing.
    for r in adm:
        if len(r) >= 8 and r[7].strip() == "Vacated":
            alerts.append({"sev": "HIGH", "caseId": r[1].strip(),
                           "title": "%s - bed force-vacated, discharge not finalised" % r[1].strip(),
                           "body": "An admin freed this patient's bed without discharge paperwork. "
                                   "Approve discharge to generate the final bill and close the case."})

    doctors_json = [{"id": r[0].strip(), "name": r[1].strip(), "dept": r[2].strip(),
                     "onCall": r[6].strip(), "load": _int(r[9]), "max": _int(r[10]),
                     "free": r[6].strip() == "OnCall" and _int(r[9]) < _int(r[10])}
                    for r in docs if len(r) >= 11]

    # --- admin resource-release grid (Feature 1 / 5) ---
    name_by_case = {c["caseId"]: c["name"] for c in cases_json}
    bed_occ = {a[3].strip(): a[1].strip() for a in adm
               if len(a) >= 8 and a[7].strip() in ("Admitted", "FitForDischarge")}
    resources = {
        "beds": [{"id": b[0].strip(), "ward": b[1].strip(),
                  "type": (b[2].strip() if len(b) >= 3 else ""), "status": b[3].strip(),
                  "ventilator": (b[4].strip() if len(b) >= 5 else ""),
                  "caseId": bed_occ.get(b[0].strip(), ""),
                  "patient": name_by_case.get(bed_occ.get(b[0].strip(), ""), "")}
                 for b in beds if len(b) >= 4],
        "ventilators": [{"id": v[0].strip(), "status": v[1].strip(),
                         "location": (v[2].strip() if len(v) >= 3 else "")}
                        for v in vents if len(v) >= 2],
        "doctors": [{"id": r[0].strip(), "name": r[1].strip(), "dept": r[2].strip().replace("DEPT-", ""),
                     "onCall": r[6].strip(), "load": _int(r[9]), "max": _int(r[10]),
                     "atCapacity": (r[6].strip() != "OnCall") or _int(r[9]) >= _int(r[10])}
                    for r in docs if len(r) >= 11],
        "blood": [{"group": r[0].strip(), "units": _int(r[1]),
                   "min": (_int(r[2]) if len(r) >= 3 else 0)} for r in blood if r],
    }

    # --- discharge-approval queue (Feature 8): every active admission awaits admin sign-off.
    #     A force-Vacated bed also stays here so its billing can still be finalised. ---
    discharge_queue = []
    for a in adm:
        if len(a) >= 8 and a[7].strip() in ("Admitted", "FitForDischarge", "Vacated"):
            cid = a[1].strip()
            cj = next((c for c in cases_json if c["caseId"] == cid), None)
            discharge_queue.append({
                "caseId": cid, "patientId": a[2].strip(),
                "name": (cj["name"] if cj else a[2].strip()),
                "bed": a[3].strip(), "ward": (cj["currentWard"] if cj else ""),
                "attending": (cj["attendingDoctorName"] if cj else a[4].strip()) or a[4].strip(),
                "admittedAt": a[5].strip(), "bill": (cj["bill"] if cj else 0),
                "admissionStatus": a[7].strip(),
                "clinicallyCertified": a[7].strip() == "FitForDischarge",
                "email": patient_email(a[2].strip(), cid),
                "hasOpenRequirements": bool(cj and cj["openRequirements"]) if cj else False,
            })

    active = sum(1 for a in adm if len(a) >= 8 and a[7].strip() in ("Admitted", "FitForDischarge"))
    sig = "|".join([
        max([r[10].strip() for r in cases if len(r) >= 11] + ["-"]),
        str(len(reqs_json)),
        str(sum(1 for b in beds if len(b) >= 4 and b[3].strip() == "Available")),
        str(sum(_int(r[1]) for r in blood if r)),
        str(sum(1 for a in adm if len(a) >= 8)),
        str(len(cases_json)),
        str(len(dd_rows)),
        str(sum(1 for a in adm if len(a) >= 8 and a[7].strip() in ("Discharged", "Vacated"))),
        str(len(billing)),
        str(sum(_int(r[9]) for r in docs if len(r) >= 11)),
    ])

    return {
        "ok": True, "hospital": hospital_name(), "generatedAt": now_str(), "mode": "live",
        "signature": sig,
        "pollSeconds": max(2, _int(config_get("DashboardPollSeconds", "3"), 3)),
        "adminRelease": config_flag("AdminManualRelease", True),
        "cases": cases_json,
        "requirements": reqs_json,
        "alerts": alerts,
        "doctors": doctors_json,
        "resources": resources,
        "dischargeQueue": discharge_queue,
        "availability": {
            "bedsByWard": beds_by_ward,
            "ventilatorsFree": sum(1 for v in vents if len(v) >= 2 and v[1].strip() == "Available"),
            "blood": {r[0].strip(): _int(r[1]) for r in blood if r},
        },
        "metrics": {
            "cases": len(cases_json),
            "activeAdmissions": active,
            "pendingRequirements": len(reqs_json),
            "alerts": sum(1 for x in alerts if x["sev"] in ("HIGH", "ACTION", "ERROR")),
        },
    }


def confirm_transfer(caseid):
    """Authorised-staff confirmation for a temp-bed -> requested-ward move."""
    caseid = (caseid or "").strip()
    for r in open_requirements():
        if r[1].strip() == caseid and r[3].strip() in ("ICU_BED", "BED"):
            ok, info = transfer_bed(r)
            return {"ok": ok, "caseId": caseid,
                    "message": ("%s moved to %s bed %s." % (caseid, r[4].strip(), info)) if ok
                    else ("Cannot transfer %s yet: %s." % (caseid, info))}
    return {"ok": False, "message": "No open bed-transfer requirement for %s." % caseid}


def force_assign_doctor(caseid):
    caseid = (caseid or "").strip()
    for r in open_requirements():
        if r[1].strip() == caseid and r[3].strip() == "DOCTOR":
            ok, info = fulfil_doctor(r)
            return {"ok": ok, "caseId": caseid,
                    "message": ("Consultant %s assigned to %s." % (info, caseid)) if ok
                    else ("No on-call consultant for %s yet." % caseid)}
    return {"ok": False, "message": "No open doctor requirement for %s." % caseid}


# ============================================================================
# Admin manual resource release  (revised spec, Feature 1 / 3 / 4)
# ----------------------------------------------------------------------------
# An authorised admin frees an occupied/reserved resource from the admin panel.
# The state (.psv) is really mutated, the assignment/reservation is closed, the
# release is audited with the admin's name, and monitor_tick() runs immediately
# so the earliest valid pending request is served without a manual assignment.
# ============================================================================
RELEASABLE_KINDS = ("BED", "VENTILATOR", "DOCTOR", "BLOOD")


def _reservation_release(caseid, rtype, resource_id):
    hdr, rr = load_table("RESOURCE_RESERVATIONS.psv")
    hit = False
    for r in rr:
        if len(r) >= 6 and r[5].strip() in ("Reserved", "Occupied") \
                and r[2].strip().lower() == rtype.lower() \
                and (not caseid or r[1].strip() == caseid) \
                and (not resource_id or r[3].strip() == resource_id):
            r[5] = "Released"
            hit = True
    if hit:
        save_table("RESOURCE_RESERVATIONS.psv", hdr, rr)
    return hit


def release_resource(body):
    kind = str(body.get("kind", "")).strip().upper()
    rid = str(body.get("resourceId", "") or body.get("id", "")).strip()
    admin = _san(body.get("admin", "")) or "Admin"
    reason = _san(body.get("reason", "")) or "Manual release from admin panel"
    force = bool(body.get("force", False))
    add_units = _int(body.get("units", 0)) or _int(body.get("addUnits", 0))

    if not config_flag("AdminManualRelease", True):
        return {"ok": False, "message": "Admin manual release is disabled (AdminManualRelease=False)."}
    if kind not in RELEASABLE_KINDS:
        return {"ok": False, "message": "Unknown resource kind '%s' (use BED / VENTILATOR / DOCTOR / BLOOD)." % kind}
    if not rid:
        return {"ok": False, "message": "resourceId is required."}
    now = now_str()
    rel_case, label = "", "%s %s" % (kind.title(), rid)

    if kind == "BED":
        hdr, beds = load_table("BEDS.psv")
        b = next((x for x in beds if x and x[0].strip() == rid), None)
        if not b:
            return {"ok": False, "message": "Bed %s not found." % rid}
        prev = b[3].strip()
        _, adm = load_table("ADMISSIONS.psv")
        occ = next((a for a in adm if len(a) >= 8 and a[3].strip() == rid
                    and a[7].strip() in ("Admitted", "FitForDischarge")), None)
        if occ and not force:
            return {"ok": False, "needsForce": True, "resourceId": rid, "kind": kind,
                    "message": "Bed %s is occupied by %s (%s). Use 'Approve discharge' for that patient, "
                               "or re-send with force=true to vacate it without discharge paperwork."
                               % (rid, occ[1].strip(), occ[2].strip())}
        vent_link = b[4].strip() if len(b) >= 5 else ""
        for x in beds:
            if x[0].strip() == rid and len(x) >= 6:
                x[3] = "Available"
                x[5] = now
        save_table("BEDS.psv", hdr, beds)
        if occ:
            rel_case = occ[1].strip()
            occ_pid, occ_att = occ[2].strip(), (occ[4].strip() if len(occ) >= 5 else "")
            _, _p = load_table("PATIENTS.psv")
            _prow = next((r for r in _p if r and r[0].strip() == occ_pid), None)
            occ_etype = (_prow[4].strip() if _prow and len(_prow) >= 5 else "Standard")
            occ_dept = (_prow[5].strip() if _prow and len(_prow) >= 6 else b[1].strip())
            hdr_a, adm_rows = load_table("ADMISSIONS.psv")
            for a in adm_rows:
                if len(a) >= 9 and a[3].strip() == rid and a[7].strip() in ("Admitted", "FitForDischarge"):
                    a[7] = "Vacated"
                    a[8] = now
            save_table("ADMISSIONS.psv", hdr_a, adm_rows)
            hdr_c, cases = load_table("EMERGENCY_CASES.psv")
            for c in cases:
                if c and c[0].strip() == rel_case and len(c) >= 11:
                    c[2] = "FORCE_VACATED"
                    c[4] = "Released"
                    c[8] = "Bed force-freed by admin - approve discharge to finalise billing"
                    c[10] = now
            save_table("EMERGENCY_CASES.psv", hdr_c, cases)
            # close this patient's OTHER resources too (vent / blood / doctor) so a
            # forced eviction doesn't strand reservations or inflate doctor load,
            # and re-enter them into FCFS for a fresh bed.
            _release_after_discharge(rel_case, occ_pid, rid, occ_att)
            register_requirement(rel_case, occ_pid,
                                 "ICU_BED" if occ_dept.upper() == "ICU" else "BED",
                                 occ_dept, "", priority_of(occ_etype))
            audit(rel_case, "FORCE_VACATED",
                  "Bed %s force-freed by %s while occupied by %s (%s). Patient's other resources "
                  "released; a fresh %s bed requirement opened; billing must still be finalised via "
                  "'Approve discharge'." % (rid, admin, occ[1].strip(), occ_pid, occ_dept),
                  performed_by=admin)
        _reservation_release(rel_case, "Bed", rid)
        if vent_link:
            hdr_v, vents = load_table("VENTILATORS.psv")
            for v in vents:
                if v and v[0].strip() == vent_link and len(v) >= 4 and v[1].strip() in ("Reserved", "Occupied"):
                    v[1] = "Available"
                    v[3] = now
            save_table("VENTILATORS.psv", hdr_v, vents)
        detail = "Bed %s released by %s (was %s)%s. %s" % (
            rid, admin, prev, (" - force-vacated %s" % rel_case) if rel_case else "", reason)

    elif kind == "VENTILATOR":
        hdr, vents = load_table("VENTILATORS.psv")
        v = next((x for x in vents if x and x[0].strip() == rid), None)
        if not v:
            return {"ok": False, "message": "Ventilator %s not found." % rid}
        prev = v[1].strip()
        for x in vents:
            if x[0].strip() == rid and len(x) >= 4:
                x[1] = "Available"
                x[3] = now
        save_table("VENTILATORS.psv", hdr, vents)
        _reservation_release("", "Ventilator", rid)
        detail = "Ventilator %s released by %s (was %s). %s" % (rid, admin, prev, reason)

    elif kind == "DOCTOR":
        hdr, docs = load_table("DOCTORS.psv")
        d = next((x for x in docs if x and x[0].strip() == rid), None)
        if not d:
            return {"ok": False, "message": "Doctor %s not found." % rid}
        prev = "%s, load %s/%s" % (d[6].strip(), d[9].strip(), d[10].strip())
        for x in docs:
            if x[0].strip() == rid and len(x) >= 11:
                x[6] = "OnCall"
                if _int(x[9]) >= _int(x[10]) > 0:
                    x[9] = str(_int(x[10]) - 1)
                elif _int(x[9]) > 0:
                    x[9] = str(_int(x[9]) - 1)
                if len(x) >= 14:
                    x[13] = now
        save_table("DOCTORS.psv", hdr, docs)
        detail = "Doctor %s marked available by %s (was %s). %s" % (rid, admin, prev, reason)

    else:  # BLOOD  - "release" = restock available units
        add = add_units if add_units > 0 else 1
        hdr, blood = load_table("BLOOD_INVENTORY.psv")
        r = next((x for x in blood if x and x[0].strip() == rid), None)
        if not r:
            return {"ok": False, "message": "Blood group %s not found." % rid}
        prev = _int(r[1])
        for x in blood:
            if x[0].strip() == rid and len(x) >= 4:
                x[1] = str(_int(x[1]) + add)
                x[3] = now
        save_table("BLOOD_INVENTORY.psv", hdr, blood)
        label = "Blood %s (+%d)" % (rid, add)
        detail = "Blood %s: %d unit(s) added by %s (%d -> %d). %s" % (rid, add, admin, prev, prev + add, reason)

    audit(rel_case, "ADMIN_RELEASE_RESOURCE", detail, performed_by=admin)

    fulfilled = monitor_tick(auto_confirm=True)
    if fulfilled:
        audit(rel_case, "AUTOMATIC_RESOURCE_ALLOCATION",
              "%d pending requirement(s) actioned automatically after release of %s." % (fulfilled, label),
              performed_by="Bot")
    return {
        "ok": True, "kind": kind, "resourceId": rid, "autoAllocated": fulfilled,
        "message": "%s released by %s.%s" % (
            label, admin,
            (" %d pending requirement(s) actioned automatically." % fulfilled) if fulfilled
            else " No pending requirement was waiting on it."),
    }


# ============================================================================
# Admin discharge approval + final bill + emailed bill  (Feature 8 / 9 / 10 / 11 / 13)
# ----------------------------------------------------------------------------
# Treatment-complete never auto-discharges. The admin approves, and only then is
# the final bill built (from the EXISTING billing rows - no invented charges),
# written, emailed (simulated), and the resources freed. An email failure is
# logged and surfaced but never rolls back the discharge or the allocation.
# ============================================================================
def _sum_billing(caseid):
    _, billing = load_table("BILLING.psv")
    lines = [r for r in billing if len(r) >= 7 and r[1].strip() == caseid]
    return lines, sum(_int(r[6]) for r in lines)


def _write_bill_files(caseid, pid, name, adm, lines, subtotal, tax, total, pay_status, followup, att_id):
    notif = os.path.join(ROOT, "Data", "Notifications")
    os.makedirs(notif, exist_ok=True)
    hosp = hospital_name()
    _, docs = load_table("DOCTORS.psv")
    att_name = next((d[1].strip() for d in docs if d and d[0].strip() == att_id), att_id or "-")
    bed_id = adm[3].strip() if len(adm) >= 4 else "-"
    admitted_at = adm[5].strip() if len(adm) >= 6 else "-"
    _, beds = load_table("BEDS.psv")
    ward = next((b[1].strip() for b in beds if b and b[0].strip() == bed_id), "")
    now = now_str()
    rows = [
        "=" * 54, " FINAL HOSPITAL BILL", "=" * 54,
        " Hospital         : %s" % hosp,
        " Patient Name     : %s" % name,
        " Patient ID       : %s" % pid,
        " Admission ID     : ADM-%s" % caseid,
        " Case Reference   : %s" % caseid,
        " Admission Date   : %s" % admitted_at,
        " Discharge Date   : %s" % now,
        " Attending Doctor : %s" % att_name,
        " Ward / Bed       : %s / %s" % (ward or "-", bed_id or "-"),
        "-" * 54, " CHARGES", "-" * 54,
    ]
    for r in lines:
        desc = (r[3].strip() if len(r) >= 4 and r[3].strip() else r[2].strip())
        rows.append(" %-26s %3s x %8s = %10s" % (
            desc[:26], (r[4].strip() if len(r) >= 5 else "1"),
            (r[5].strip() if len(r) >= 6 else "0"), (r[6].strip() if len(r) >= 7 else "0")))
    if not lines:
        rows.append(" (no charges posted)")
    rows += [
        "-" * 54,
        " Subtotal         : INR %s" % "{:,}".format(subtotal),
        " Tax              : INR %s" % "{:,}".format(tax),
        " Discount         : INR 0",
        " TOTAL AMOUNT     : INR %s" % "{:,}".format(total),
        " Payment Status   : %s" % pay_status,
        " Follow-up Date   : %s" % followup,
        "=" * 54,
        " Administrative billing document. Clinical care and coding",
        " decisions remain with authorised hospital staff.",
        "=" * 54,
    ]
    text = "\n".join(rows)
    with open(os.path.join(notif, "BILL_%s.txt" % caseid), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    html = (
        "<html><head><meta charset='utf-8'><style>body{font-family:Segoe UI,Arial,sans-serif;"
        "background:#f4f6f9;padding:20px}.card{background:#fff;border-radius:8px;padding:24px;max-width:760px;"
        "margin:auto;box-shadow:0 2px 8px rgba(0,0,0,.1)}.hdr{background:#004687;color:#fff;padding:16px;"
        "border-radius:8px 8px 0 0;margin:-24px -24px 16px}pre{background:#f8f9fa;padding:14px;"
        "border-left:4px solid #004687;white-space:pre-wrap;font-size:13px}.ftr{margin-top:16px;font-size:11px;"
        "color:#6c757d;border-top:1px solid #dee2e6;padding-top:10px}</style></head><body><div class='card'>"
        "<div class='hdr'><h2 style='margin:0'>Discharge Bill</h2><p style='margin:4px 0 0'>%s | %s</p></div>"
        "<pre>%s</pre><div class='ftr'>Automated administrative billing document from %s RPA.</div>"
        "</div></body></html>" % (caseid, now, text.replace("&", "&amp;").replace("<", "&lt;"), hosp))
    html_path = os.path.join(notif, "BILL_%s.html" % caseid)
    with open(html_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    return html_path


def _send_bill_email(caseid, pid, name, email, total):
    """Simulated send: drop an EMAIL_<case>_bill_<ts>.html envelope in EmailOutputFolder.
    Raises on any condition that a real send would fail on, so the caller logs
    EMAIL_SEND_FAILED without unwinding the discharge."""
    if not email:
        raise RuntimeError("no email address on file for patient %s" % pid)
    if not config_flag("EmailSimulated", True):
        raise RuntimeError("real SMTP delivery is not configured (EmailSimulated=False)")
    folder = os.path.join(ROOT, "Data", "Notifications")
    os.makedirs(folder, exist_ok=True)
    subject = "%s - Patient %s" % (config_get("BillingEmailSubjectPrefix", "Hospital Discharge Bill"), pid)
    bill_text = read_text(os.path.join(folder, "BILL_%s.txt" % caseid)).replace("&", "&amp;").replace("<", "&lt;")
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    envelope = (
        "<html><body style='font-family:Segoe UI,Arial,sans-serif;background:#f4f6f9;padding:20px'>"
        "<div style='background:#fff;max-width:760px;margin:auto;border-radius:8px;padding:24px'>"
        "<p><b>To:</b> %s<br><b>From:</b> %s<br><b>Subject:</b> %s</p>"
        "<p>Dear %s,</p>"
        "<p>Your treatment/admission has been completed and your discharge has been approved. "
        "Please find your final hospital bill below.</p>"
        "<p><b>Patient ID:</b> %s<br><b>Admission ID:</b> ADM-%s<br><b>Total Amount:</b> INR %s</p>"
        "<pre style='background:#f8f9fa;padding:14px;border-left:4px solid #004687;white-space:pre-wrap;"
        "font-size:13px'>%s</pre>"
        "<p>Regards,<br>Hospital Administration</p></div></body></html>"
        % (esc(email), esc(config_get("SMTPFrom", "rpa-bot@hospital.local")), esc(subject), esc(name),
           pid, caseid, "{:,}".format(total), bill_text))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(folder, "EMAIL_%s_bill_%s.html" % (caseid, stamp))
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(envelope)
    return out


def _release_after_discharge(caseid, pid, bed_id, att_id):
    now = now_str()
    freed = []
    hdr_b, beds = load_table("BEDS.psv")
    for b in beds:
        if b and b[0].strip() == bed_id and len(b) >= 6:
            b[3] = "Available"
            b[5] = now
            freed.append("bed " + bed_id)
    save_table("BEDS.psv", hdr_b, beds)

    _, rr = load_table("RESOURCE_RESERVATIONS.psv")
    vent_ids = [r[3].strip() for r in rr if len(r) >= 6 and r[1].strip() == caseid
                and r[2].strip() == "Ventilator" and r[5].strip() in ("Reserved", "Occupied")]
    if vent_ids:
        hdr_v, vents = load_table("VENTILATORS.psv")
        for v in vents:
            if v and v[0].strip() in vent_ids and len(v) >= 4:
                v[1] = "Available"
                v[3] = now
                freed.append("ventilator " + v[0].strip())
        save_table("VENTILATORS.psv", hdr_v, vents)

    hdr_da, da = load_table("DOCTOR_ASSIGNMENTS.psv")
    rel_docs = []
    for r in da:
        if len(r) >= 7 and r[1].strip() == caseid and r[6].strip() == "Assigned":
            r[6] = "Released"
            rel_docs.append(r[2].strip())
    if rel_docs:
        save_table("DOCTOR_ASSIGNMENTS.psv", hdr_da, da)
    to_decrement = rel_docs or ([att_id] if att_id else [])
    if to_decrement:
        hdr_dc, docs = load_table("DOCTORS.psv")
        for x in docs:
            if x and x[0].strip() in to_decrement and len(x) >= 11:
                x[9] = str(max(0, _int(x[9]) - 1))
                if len(x) >= 14:
                    x[13] = now
        save_table("DOCTORS.psv", hdr_dc, docs)
        freed.append("doctor load -%d" % len(to_decrement))

    hdr_rr, rr2 = load_table("RESOURCE_RESERVATIONS.psv")
    for r in rr2:
        if len(r) >= 6 and r[1].strip() == caseid and r[5].strip() in ("Reserved", "Occupied"):
            r[5] = "Released"
    save_table("RESOURCE_RESERVATIONS.psv", hdr_rr, rr2)
    return freed


def _clinical_clearance_for(caseid):
    """Return (doctorId, at) from an existing DISCHARGES draft, or ("","") if none."""
    _, drows = load_table("DISCHARGES.psv")
    for r in drows:
        if r and r[0].strip() == "DIS-" + caseid and len(r) >= 5:
            return r[3].strip(), r[4].strip()
    return "", ""


def approve_discharge(body):
    caseid = str(body.get("caseId", "")).strip()
    admin = _san(body.get("admin", "")) or "Admin"
    if not caseid:
        return {"ok": False, "message": "caseId is required."}
    hdr_a, adm_rows, a = _adm_row_for(caseid)
    if not a:
        return {"ok": False, "message": "No admission found for %s." % caseid}
    adm_status = a[7].strip()
    if adm_status not in ("Admitted", "FitForDischarge", "Vacated"):
        return {"ok": False, "message": "%s is not an active admission (status: %s)." % (caseid, adm_status)}

    pid, bed_id, att_id, admitted_at = a[2].strip(), a[3].strip(), a[4].strip(), a[5].strip()
    _, pats = load_table("PATIENTS.psv")
    prow = next((r for r in pats if r and r[0].strip() == pid), None)
    name = prow[1].strip() if prow and len(prow) >= 2 else pid
    now = now_str()

    # ---- clinical gate: administrative approval NEVER substitutes for the
    #      attending doctor's fitness certification (HUMAN GATE 2). ----
    clr_by, clr_at = _clinical_clearance_for(caseid)
    if adm_status == "FitForDischarge" and clr_by:
        pass  # properly certified by CertifyDischarge
    elif config_flag("AutoCertifyDischarge", True):
        # demo path - auto-certify on the attending's behalf and SAY SO.
        clr_by, clr_at = (att_id or "attending"), now
        audit(caseid, "DISCHARGE_CERTIFIED",
              "Auto-certified fit for discharge on behalf of %s (Config AutoCertifyDischarge=True); "
              "no clinical assessment performed by the bot." % clr_by,
              performed_by="%s (auto)" % (att_id or "attending"))
    else:
        return {"ok": False, "needsCertification": True, "caseId": caseid,
                "message": "%s has not been certified fit for discharge by the attending doctor. "
                           "Run CertifyDischarge (HUMAN GATE 2) first, or set Config "
                           "AutoCertifyDischarge=True for a demo run." % caseid}

    audit(caseid, "DISCHARGE_APPROVED",
          "Discharge approved by %s for %s (%s); admitted %s, bed %s; clinical clearance by %s at %s."
          % (admin, name, pid, admitted_at, bed_id, clr_by or "-", clr_at or "-"),
          performed_by=admin)

    lines, subtotal = _sum_billing(caseid)
    raw_tax = config_get("BillingTaxPercent", "0") or "0"
    try:
        tax_pct = float(raw_tax)
    except ValueError:
        tax_pct = 0.0
        audit(caseid, "BILLING_CONFIG_WARNING",
              "BillingTaxPercent=%r is not a number; charging 0%% tax on this bill." % raw_tax)
    tax = int(round(subtotal * tax_pct / 100.0))
    total = subtotal + tax

    _, docs_tbl = load_table("DOCUMENTS.psv")
    insured = any(len(r) >= 5 and r[1].strip() == pid and r[2].strip() == "Insurance"
                  and r[4].strip() == "Present" for r in docs_tbl)
    if total == 0 and not lines:
        pay_status = "NotBillable"
        audit(caseid, "BILL_ZERO_NO_CHARGES",
              "No billable charges were posted for %s; final bill INR 0, marked NotBillable." % caseid)
    else:
        pay_status = "InsurancePending" if insured else "Invoiced"
    email = patient_email(pid, caseid)
    followup = (datetime.datetime.now() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        bill_path = _write_bill_files(caseid, pid, name, a, lines, subtotal, tax, total, pay_status, followup, att_id)
        audit(caseid, "BILL_GENERATED",
              "Final bill: subtotal %d + tax %d = %d INR across %d line item(s); payment %s."
              % (subtotal, tax, total, len(lines), pay_status), performed_by="Bot")

        email_ok, email_note = True, ""
        try:
            _send_bill_email(caseid, pid, name, email, total)
            audit(caseid, "BILL_EMAIL_SENT", "Final bill emailed to %s." % email, performed_by="Bot")
            _delete_signal("EMAIL_RETRY_%s.txt" % caseid)
        except Exception as e:  # noqa: BLE001 - email failure must NOT roll back the discharge (Feature 13)
            email_ok, email_note = False, str(e)
            audit(caseid, "EMAIL_SEND_FAILED",
                  "Bill NOT emailed (%s). Discharge, billing and resource release STAND; "
                  "retry from the admin panel (POST /api/retry-bill-email)." % e, performed_by="Bot")
            _write_retry_marker(caseid, pid, email, total, str(e))

        # commit the discharge STATUS before freeing beds, so the background
        # monitor can never hand a freed bed to another patient while this case
        # still reads "Admitted".
        hdr_d, drows = load_table("DISCHARGES.psv")
        if not hdr_d:
            hdr_d = DB_SCHEMA["DISCHARGES"]
        drows = [r for r in drows if not (r and r[0].strip() == "DIS-" + caseid)]
        drows.append(["DIS-" + caseid, caseid, pid, clr_by, clr_at, str(total), pay_status, followup,
                      os.path.relpath(bill_path, ROOT).replace(os.sep, "/"), now])
        save_table("DISCHARGES.psv", hdr_d, drows)

        for r in adm_rows:
            if r[1].strip() == caseid and len(r) >= 9:
                r[7] = "Discharged"
                r[8] = now
        save_table("ADMISSIONS.psv", hdr_a, adm_rows)

        hdr_c, cases = load_table("EMERGENCY_CASES.psv")
        for r in cases:
            if r and r[0].strip() == caseid and len(r) >= 11:
                r[2] = "DISCHARGED"
                r[4] = "Released"
                r[8] = "None"
                r[10] = now
        save_table("EMERGENCY_CASES.psv", hdr_c, cases)

        for r in open_requirements():
            if r[1].strip() == caseid:
                set_requirement_status(r[0].strip(), "CANCELLED")

        freed = _release_after_discharge(caseid, pid, bed_id, att_id)
        audit(caseid, "RESOURCE_RELEASED_AFTER_DISCHARGE",
              "Freed on discharge of %s: %s." % (caseid, ", ".join(freed) or "nothing"), performed_by="Bot")
    except Exception as e:  # noqa: BLE001 - a failure AFTER DISCHARGE_APPROVED must be LOUD, not a silent 500
        audit(caseid, "DISCHARGE_FAILED_MIDWAY",
              "Discharge of %s failed after approval (%s: %s). The case is flagged for review; "
              "state may be partially applied." % (caseid, type(e).__name__, e), performed_by="Bot")
        try:
            hdr_c, cases = load_table("EMERGENCY_CASES.psv")
            for r in cases:
                if r and r[0].strip() == caseid and len(r) >= 11:
                    r[2] = "Error"
                    r[8] = "Discharge failed after approval - needs review"
                    r[10] = now_str()
            save_table("EMERGENCY_CASES.psv", hdr_c, cases)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "caseId": caseid,
                "message": "Discharge of %s FAILED after approval (%s). Flagged for review." % (caseid, e)}

    fulfilled = monitor_tick(auto_confirm=True)
    if fulfilled:
        audit(caseid, "AUTOMATIC_RESOURCE_ALLOCATION",
              "%d pending requirement(s) actioned automatically after %s vacated bed %s."
              % (fulfilled, caseid, bed_id), performed_by="Bot")

    return {
        "ok": True, "caseId": caseid, "patientId": pid,
        "subtotal": subtotal, "tax": tax, "total": total, "paymentStatus": pay_status,
        "clinicalClearanceBy": clr_by,
        "emailSent": email_ok, "emailAddress": email, "emailError": "" if email_ok else email_note,
        "billPath": os.path.relpath(bill_path, ROOT).replace(os.sep, "/"),
        "autoAllocated": fulfilled,
        "message": "Discharge approved for %s. Final bill INR %s %s.%s" % (
            caseid, "{:,}".format(total),
            ("emailed to " + email) if email_ok else ("NOT emailed (" + email_note + ")"),
            (" %d pending requirement(s) actioned." % fulfilled) if fulfilled else ""),
    }


def _write_retry_marker(caseid, pid, email, total, reason):
    """Durable record that a discharge bill needs re-emailing - build_state turns
    the presence of this file into a WARN alert that does NOT scroll away."""
    try:
        folder = os.path.join(ROOT, "Data", "Notifications")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "EMAIL_RETRY_%s.txt" % caseid), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join([
                "DISCHARGE BILL EMAIL FAILED - retry required",
                "Case: %s   Patient: %s" % (caseid, pid),
                "Address on file: %s" % (email or "(none)"),
                "Bill total: INR %s" % "{:,}".format(total),
                "Reason: %s" % reason,
                "Raised: %s" % now_str(),
                "",
                "Retry: POST /api/retry-bill-email {\"caseId\": \"%s\"}  (or the admin dashboard button)." % caseid,
            ]) + "\n")
    except OSError as e:
        print("  [approve_discharge] could not write EMAIL_RETRY marker: %s" % e)


def retry_bill_email(body):
    """Re-send a discharge bill whose email previously failed. Clears the marker
    on success; the discharge itself is already complete and is untouched."""
    caseid = str(body.get("caseId", "")).strip()
    if not caseid:
        return {"ok": False, "message": "caseId is required."}
    _, drows = load_table("DISCHARGES.psv")
    d = next((r for r in drows if r and r[0].strip() == "DIS-" + caseid and len(r) >= 6), None)
    if not d:
        return {"ok": False, "message": "No completed discharge for %s to re-bill." % caseid}
    _, adm = load_table("ADMISSIONS.psv")
    arow = next((r for r in adm if len(r) >= 3 and r[1].strip() == caseid), None)
    pid = arow[2].strip() if arow else d[2].strip()
    _, pats = load_table("PATIENTS.psv")
    prow = next((r for r in pats if r and r[0].strip() == pid), None)
    name = prow[1].strip() if prow and len(prow) >= 2 else pid
    total = _int(d[5])
    email = patient_email(pid, caseid)
    try:
        _send_bill_email(caseid, pid, name, email, total)
        audit(caseid, "BILL_EMAIL_SENT", "Final bill re-emailed to %s (retry succeeded)." % email, performed_by="Bot")
        _delete_signal("EMAIL_RETRY_%s.txt" % caseid)
        return {"ok": True, "caseId": caseid, "emailAddress": email,
                "message": "Bill for %s re-emailed to %s." % (caseid, email)}
    except Exception as e:  # noqa: BLE001
        audit(caseid, "EMAIL_SEND_FAILED", "Retry also failed (%s)." % e, performed_by="Bot")
        _write_retry_marker(caseid, pid, email, total, str(e))
        return {"ok": False, "caseId": caseid, "emailError": str(e),
                "message": "Retry failed for %s: %s" % (caseid, e)}


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
            with PROCESS_LOCK:                       # serve a self-consistent multi-table snapshot
                page = render_page()
            self._send(200, page, "text/html; charset=utf-8")
        elif path == "/api/ping":
            self._send(200, json.dumps({"ok": True, "hospital": hospital_name(), "time": now_str()}))
        elif path == "/api/state":
            with PROCESS_LOCK:
                payload = build_state()
            self._send(200, json.dumps(payload))
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
                with PROCESS_LOCK:
                    payload = submit_case(body)
                self._send(200, json.dumps(payload))
            elif path == "/api/restore":
                with PROCESS_LOCK:
                    payload = restore_baseline()
                self._send(200, json.dumps(payload))
            elif path == "/api/confirm-transfer":
                with PROCESS_LOCK:
                    payload = confirm_transfer(body.get("caseId", ""))
                self._send(200, json.dumps(payload))
            elif path == "/api/assign-doctor":
                with PROCESS_LOCK:
                    payload = force_assign_doctor(body.get("caseId", ""))
                self._send(200, json.dumps(payload))
            elif path == "/api/release":
                with PROCESS_LOCK:
                    payload = release_resource(body)
                self._send(200, json.dumps(payload))
            elif path == "/api/approve-discharge":
                with PROCESS_LOCK:
                    payload = approve_discharge(body)
                self._send(200, json.dumps(payload))
            elif path == "/api/retry-bill-email":
                with PROCESS_LOCK:
                    payload = retry_bill_email(body)
                self._send(200, json.dumps(payload))
            else:
                self._send(404, json.dumps({"ok": False, "error": "not found"}))
        except ValueError as e:
            self._send(400, json.dumps({"ok": False, "error": str(e)}))
        except Exception as e:  # noqa: BLE001 - surface unexpected errors to the client
            self._send(500, json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}))


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


_BASELINE_PIDS = {row.split("|")[0].strip() for row in BASELINE_INPUT[1:]}


def sweep_pending():
    """On startup, coordinate any intake submissions that were queued while the
    console was down. The 8 baseline test patients (P1024-P1031) are left for
    Main.xaml; only console-originated rows (P1032+) are swept."""
    if not config_flag("AutoRouteOnIntake", True):
        return
    txt = read_text(INPUT_FILE)
    prefix = config_get("CaseIdPrefix", "ER")
    done = []
    for i, line in enumerate(txt.splitlines()):
        if i == 0 or not line.strip():
            continue
        p = line.split("|")
        if len(p) < 12 or p[9].strip() != "Pending" or p[0].strip() in _BASELINE_PIDS:
            continue
        pid = p[0].strip()
        caseid = prefix + re.sub(r"\D", "", pid)
        try:
            save_patient_contact(pid, caseid, p[12].strip() if len(p) >= 13 else "", "")
            out = process_case(pid, caseid, p[1].strip(), p[4].strip(), p[5].strip(),
                               p[6].strip().lower() in ("yes", "true", "1"), p[7].strip(), p[8].strip())
            done.append("%s -> %s" % (caseid, out.get("caseState", "?")))
        except Exception as e:  # noqa: BLE001 - one bad row must not stop the server
            done.append("%s -> ERROR %s: %s" % (caseid, type(e).__name__, e))
    if done:
        print("  Swept %d queued intake submission(s): %s" % (len(done), "; ".join(done)))


def already_running(port):
    """If a console server is already answering on `port`, return its URL; else None.

    Lets the UiPath bot fire this launcher on every run without ever stacking up
    a second server - a re-launch just re-opens the tab pointing at the live one.
    """
    url = "http://localhost:%d/" % port
    try:
        with urllib.request.urlopen(url + "api/ping", timeout=1.5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("ok"):
            return url
    except Exception:  # noqa: BLE001 - nothing (of ours) listening -> fall through to start
        return None
    return None


def main():
    global PORT
    running = already_running(PORT)
    if running:
        print("Emergency Coordination Console already running at %s - opening browser." % running)
        webbrowser.open(running)
        return
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
    try:
        with PROCESS_LOCK:
            sweep_pending()
    except Exception as e:  # noqa: BLE001 - startup sweep is best-effort
        print("  Intake sweep skipped: %s: %s" % (type(e).__name__, e))

    mon = threading.Thread(target=monitor_loop, name="requirement-monitor", daemon=True)
    mon.start()
    print("  Requirement monitor running every %s s." % config_get("MonitorIntervalSeconds", "5"))

    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        MONITOR_STOP.set()
        httpd.shutdown()


if __name__ == "__main__":
    main()
