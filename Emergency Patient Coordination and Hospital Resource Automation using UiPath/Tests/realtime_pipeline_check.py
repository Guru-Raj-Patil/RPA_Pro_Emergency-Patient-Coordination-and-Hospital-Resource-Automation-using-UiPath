#!/usr/bin/env python3
"""
End-to-end check for the real-time coordination layer (console_server.py):
immediate intake processing, criticality bed re-routing, pending-requirement
tracking, the availability monitor + transfer confirmation, blood auto-fulfil,
document reading (extract / cross-check / gap-fill) and the /api/state snapshot.

It is self-contained and non-destructive: it snapshots the mutable datastore
(Data/db, Data/PatientInput.psv, Data/Notifications, Patients), reseeds a small
known state, drives the pipeline by importing console_server directly, asserts
the outcomes, then restores everything it touched.

Run from anywhere:
    python "Emergency Patient Coordination and Hospital Resource Automation using UiPath/Tests/realtime_pipeline_check.py"
Exit code 0 = all checks passed.
"""
import os
import sys
import json
import shutil
import base64
import importlib

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
DASH = os.path.join(PROJ, "Data", "Dashboard")
DB = os.path.join(PROJ, "Data", "db")
NOTIF = os.path.join(PROJ, "Data", "Notifications")
INPUT = os.path.join(PROJ, "Data", "PatientInput.psv")
PATIENTS = os.path.join(PROJ, "Patients")
SAMPLE = os.path.join(PROJ, "SampleDocuments", "patient_A_rahul")
BK = os.path.join(HERE, "_bk_realtime_check")

_PASS, _FAIL = [], []


def check(name, ok, detail=""):
    (_PASS if ok else _FAIL).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  -> " + detail) if detail and not ok else ""))


# ---------------------------------------------------------------- snapshot / restore
def _snap():
    if os.path.isdir(BK):
        shutil.rmtree(BK)
    os.makedirs(BK)
    shutil.copytree(DB, os.path.join(BK, "db"))
    shutil.copytree(NOTIF, os.path.join(BK, "Notifications"))
    shutil.copy2(INPUT, os.path.join(BK, "PatientInput.psv"))
    if os.path.isdir(PATIENTS):
        shutil.copytree(PATIENTS, os.path.join(BK, "Patients"))


def _restore_dir(src, dst):
    for n in os.listdir(dst):
        p = os.path.join(dst, n)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    for n in os.listdir(src):
        s, d = os.path.join(src, n), os.path.join(dst, n)
        shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy2(s, d)


def _restore():
    _restore_dir(os.path.join(BK, "db"), DB)
    _restore_dir(os.path.join(BK, "Notifications"), NOTIF)
    shutil.copy2(os.path.join(BK, "PatientInput.psv"), INPUT)
    if os.path.isdir(os.path.join(BK, "Patients")):
        _restore_dir(os.path.join(BK, "Patients"), PATIENTS)
    shutil.rmtree(BK, ignore_errors=True)


def _w(name, lines):
    with open(os.path.join(DB, name), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


HEADERS = {
    "EMERGENCY_CASES.psv": "CaseId|PatientId|CaseStatus|DocumentStatus|BedStatus|VentilatorStatus|BloodStatus|ReadinessPercentage|PendingAction|CreatedAt|UpdatedAt",
    "PENDING_REQUIREMENTS.psv": "RequirementId|CaseId|PatientId|Type|RequestedValue|CurrentFallback|Priority|Status|CreatedAt|UpdatedAt|ResolvedAt",
    "PATIENT_DOCUMENT_DATA.psv": "RecordId|PatientId|CaseId|DocumentType|Field|Value|ExtractedAt",
    "RESOURCE_RESERVATIONS.psv": "ReservationId|CaseId|ResourceType|ResourceId|Quantity|Status|ReservedAt",
    "AUDIT_LOG.psv": "LogId|CaseId|Action|Description|Timestamp|PerformedBy",
    "DOCTOR_ASSIGNMENTS.psv": "AssignmentId|CaseId|DoctorId|Role|Specialty|AssignedAt|Status",
    "ADMISSIONS.psv": "AdmissionId|CaseId|PatientId|BedId|AttendingDoctorId|AdmittedAt|ExpectedStayDays|Status|DischargeReadyAt",
    "BILLING.psv": "ChargeId|CaseId|Category|Description|Quantity|UnitPrice|Amount|PostedAt",
    "OT_SCHEDULE.psv": "SlotId|TheatreId|CaseId|SurgeonId|AnaesthetistId|ScheduledStart|ScheduledEnd|Status",
    "DISCHARGES.psv": "DischargeId|CaseId|PatientId|ClinicalClearanceBy|ClinicalClearanceAt|FinalBillAmount|PaymentStatus|FollowUpDate|DischargeSummaryPath|DischargedAt",
    "INSURANCE_CLAIMS.psv": "ClaimId|CaseId|Insurer|PolicyNumber|ClaimAmount|PacketPath|Status|SubmittedAt",
    "PATIENTS.psv": "PatientId|Name|Age|Gender|EmergencyType|RequiredDepartment|RequiredVentilator|RequiredBloodGroup|RequiredBloodUnits|CreatedAt",
    "DOCUMENTS.psv": "DocumentId|PatientId|DocumentType|FilePath|VerificationStatus|VerifiedAt",
}


def _reseed():
    for name, hdr in HEADERS.items():
        _w(name, [hdr])
    _w("BEDS.psv", [
        "BedId|Department|BedType|Status|VentilatorId|LastUpdated",
        "ICU-01|ICU|Premium|Occupied|V-01|s", "ICU-02|ICU|Premium|Occupied|V-02|s",
        "ICU-03|ICU|Premium|Available|V-03|s", "ICU-04|ICU|Standard|Available|V-04|s",
        "GEN-01|General|Standard|Occupied||s", "GEN-02|General|Standard|Available||s",
        "GEN-03|General|Standard|Available||s", "GEN-04|General|Standard|Available||s",
        "CARD-01|Cardiology|Premium|Available|V-05|s", "CARD-02|Cardiology|Standard|Available||s",
    ])
    _w("VENTILATORS.psv", [
        "VentilatorId|Status|Location|LastUpdated",
        "V-01|Occupied|A|s", "V-02|Occupied|A|s", "V-03|Available|B|s",
        "V-04|Available|B|s", "V-05|Available|C|s", "V-06|Available|C|s",
    ])
    _w("BLOOD_INVENTORY.psv", [
        "BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated",
        "A+|15|3|s", "A-|5|2|s", "B+|12|3|s", "B-|4|2|s",
        "AB+|8|2|s", "AB-|2|1|s", "O+|20|5|s", "O-|6|2|s",
    ])
    with open(INPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADERS["PATIENTS.psv"].replace("RequiredDepartment", "RequiredDepartment") + "\n"
                if False else
                "PatientId|Name|Age|Gender|EmergencyType|RequiredDepartment|VentilatorRequired|"
                "BloodGroup|BloodUnits|ProcessStatus|CaseId|Notes\n")
    # DEPARTMENTS / DOCTORS / OPERATING_THEATRES are reference data - keep the repo's copies


def _rows(cs, name):
    return cs.load_table(name)[1]


def _audit_actions(cs, caseid):
    return [r[2].strip() for r in _rows(cs, "AUDIT_LOG.psv") if len(r) >= 3 and r[1].strip() == caseid]


def _docs_payload():
    out = {}
    for slot in ("ID_Proof", "Insurance", "Consent_Form", "Medical_Report"):
        p = os.path.join(SAMPLE, slot + ".pdf")
        with open(p, "rb") as f:
            out[slot] = {"filename": slot + ".pdf", "dataB64": base64.b64encode(f.read()).decode()}
    return out


# ---------------------------------------------------------------- the checks
def run():
    if not os.path.isdir(DASH) or not os.path.isfile(os.path.join(DASH, "console_server.py")):
        print("Cannot find Data/Dashboard/console_server.py - run this from inside the project.")
        return 2
    if not os.path.isdir(SAMPLE):
        print("SampleDocuments/patient_A_rahul not found - run SampleDocuments/make_sample_docs.py first.")
        return 2

    sys.path.insert(0, DASH)
    _snap()
    try:
        _reseed()
        cs = importlib.import_module("console_server")
        docs = _docs_payload()

        # 1 - immediate processing + admission ------------------------------------
        print("\n[1] immediate intake processing")
        r = cs.submit_case({"name": "Rahul Kumar", "age": "54", "gender": "Male",
                            "emergencyType": "Critical", "department": "ICU", "ventilator": True,
                            "bloodGroup": "O-", "bloodUnits": "4", "docs": docs})
        c1 = r["caseId"]
        cases = {x[0].strip(): x for x in _rows(cs, "EMERGENCY_CASES.psv")}
        adm = [x for x in _rows(cs, "ADMISSIONS.psv") if x[1].strip() == c1]
        bill = [x for x in _rows(cs, "BILLING.psv") if x[1].strip() == c1]
        acts = _audit_actions(cs, c1)
        check("case row created", c1 in cases)
        check("case admitted immediately (no queue)", cases.get(c1, ["", "", ""])[2].strip() == "Admitted", cases.get(c1))
        check("ADMISSIONS row written", len(adm) == 1)
        check("billing opened (registration + bed-day)",
              any(b[2].strip() == "Registration" for b in bill) and any(b[2].strip() == "BedDay" for b in bill))
        for a in ("CASE_CREATED", "DOC_CHECKED", "BED_CHECKED", "VENT_CHECKED", "BLOOD_CHECKED",
                  "READINESS_CALC", "RESOURCES_RESERVED", "ADMISSION_CONFIRMED", "CASE_CLOSED"):
            check("audit event " + a, a in acts)
        inp = [l.split("|") for l in open(INPUT, encoding="utf-8").read().splitlines()[1:] if l.strip()]
        check("PatientInput row flipped off 'Pending'",
              all(p[9].strip() != "Pending" for p in inp if p[0].strip() == r["patientId"]))

        # 2 - document reading --------------------------------------------------
        print("\n[2] document reading")
        dd = [x for x in _rows(cs, "PATIENT_DOCUMENT_DATA.psv") if x[2].strip() == c1 and x[3].strip() != "_check"]
        fields = {x[4].strip(): x[5].strip() for x in dd}
        check("DOC_READ audit present", "DOC_READ" in acts)
        check("medical-report fields extracted",
              fields.get("ProvisionalDiagnosis", "").startswith("Suspected acute coronary"))
        check("blood group read from medical report", fields.get("BloodGroup") == "O-")
        check("insurance policy read", fields.get("PolicyNumber", "").startswith("POL-"))
        check("id name read", fields.get("IdName") == "Rahul Kumar")
        check("no false mismatch when form matches the report",
              not any(x[3].strip() == "_check" for x in _rows(cs, "PATIENT_DOCUMENT_DATA.psv") if x[2].strip() == c1))

        # 3 - cross-check + gap-fill ------------------------------------------------
        print("\n[3] cross-check + gap-fill")
        r = cs.submit_case({"name": "Rahul Kumar", "age": "54", "gender": "Male",
                            "emergencyType": "Critical", "department": "ICU", "ventilator": True,
                            "bloodGroup": "A+", "bloodUnits": "0", "docs": docs})   # wrong group, blank units
        c2 = r["caseId"]
        acts2 = _audit_actions(cs, c2)
        checks = [x for x in _rows(cs, "PATIENT_DOCUMENT_DATA.psv") if x[2].strip() == c2 and x[3].strip() == "_check"]
        check("DOC_MISMATCH raised for blood group", "DOC_MISMATCH" in acts2 and any("Blood group" in x[4] for x in checks))
        check("DOC_DATA_APPLIED (units gap-filled from report)", "DOC_DATA_APPLIED" in acts2)
        bchk = [d for a, d in [(x[2].strip(), x[3]) for x in _rows(cs, "AUDIT_LOG.psv") if x[1].strip() == c2]
                if a == "BLOOD_CHECKED"]
        check("blood check used the gap-filled units (4)", any("needed 4" in d for d in bchk), bchk)

        # 4 - criticality bed re-routing ----------------------------------------
        print("\n[4] criticality bed re-routing (ICU full -> fallback ward)")
        # ICU-03/04 now taken by c1/c2; a 3rd Critical/ICU must fall back
        r = cs.submit_case({"name": "Third Critical", "age": "40", "emergencyType": "Critical",
                            "department": "ICU", "ventilator": False, "bloodGroup": "O+",
                            "bloodUnits": "1", "docs": docs})
        c3 = r["caseId"]
        preq = [x for x in _rows(cs, "PENDING_REQUIREMENTS.psv")
                if x[1].strip() == c3 and x[3].strip() in ("ICU_BED", "BED")]
        check("3rd Critical/ICU still admitted (not queued)", r.get("caseState") == "Admitted", r.get("caseState"))
        check("routed to a fallback ward (interim)", r.get("interimBed") is True)
        check("PENDING_REQUIREMENTS row opened (ICU bed, HIGH)",
              len(preq) == 1 and preq[0][6].strip() == "HIGH" and preq[0][7].strip() == "OPEN")
        check("patient physically has a bed now",
              bool([a for a in _rows(cs, "ADMISSIONS.psv") if a[1].strip() == c3 and a[3].strip()]))

        # 5 - monitor raises ACTION_REQUIRED, only for one, then confirm ----------
        print("\n[5] availability monitor + transfer confirmation")
        hdr, beds = cs.load_table("BEDS.psv")
        for b in beds:
            if b[0].strip() == "ICU-03":
                b[3] = "Available"
                b[5] = cs.now_str()
        cs.save_table("BEDS.psv", hdr, beds)
        acted = cs.monitor_tick()
        ar = [x for x in cs.open_requirements() if x[7].strip() == "ACTION_REQUIRED"]
        check("monitor acted on the freed bed", acted >= 1)
        check("exactly one ACTION_REQUIRED for one free bed", len(ar) == 1, [x[1].strip() for x in ar])
        moved = None
        if ar:
            moved = ar[0][1].strip()
            res = cs.confirm_transfer(moved)
            check("confirm_transfer succeeded", res.get("ok") is True, res)
            a = [x for x in _rows(cs, "ADMISSIONS.psv") if x[1].strip() == moved]
            _, beds2 = cs.load_table("BEDS.psv")
            bward = {x[0].strip(): x[1].strip() for x in beds2}
            check("patient moved into an ICU bed", bool(a) and bward.get(a[0][3].strip()) == "ICU", a)
            check("bed-transfer requirement fulfilled",
                  all(x[7].strip() == "FULFILLED" for x in _rows(cs, "PENDING_REQUIREMENTS.psv")
                      if x[1].strip() == moved and x[3].strip() in ("ICU_BED", "BED")))
            check("BED_TRANSFERRED audit written", "BED_TRANSFERRED" in _audit_actions(cs, moved))

        # 6 - blood auto-fulfil -------------------------------------------------
        print("\n[6] blood shortage -> auto-fulfil on restock")
        r = cs.submit_case({"name": "Bleeder", "age": "50", "emergencyType": "Critical",
                            "department": "Cardiology", "ventilator": False, "bloodGroup": "O-",
                            "bloodUnits": "30", "docs": docs})   # far more than stock
        c6 = r["caseId"]
        breq = [x for x in _rows(cs, "PENDING_REQUIREMENTS.psv")
                if x[1].strip() == c6 and x[3].strip() == "BLOOD"]
        check("admitted despite blood shortage", r.get("caseState") == "Admitted")
        check("BLOOD requirement opened", len(breq) == 1 and breq[0][7].strip() == "OPEN")
        hdr, bl = cs.load_table("BLOOD_INVENTORY.psv")
        for x in bl:
            if x[0].strip() == "O-":
                x[1] = "40"
        cs.save_table("BLOOD_INVENTORY.psv", hdr, bl)
        cs.monitor_tick()
        check("BLOOD requirement fulfilled after restock",
              all(x[7].strip() == "FULFILLED" for x in _rows(cs, "PENDING_REQUIREMENTS.psv")
                  if x[1].strip() == c6 and x[3].strip() == "BLOOD"))

        # 7 - /api/state snapshot --------------------------------------------------
        print("\n[7] /api/state snapshot")
        st = cs.build_state()
        check("build_state ok", st.get("ok") is True)
        for k in ("cases", "requirements", "alerts", "doctors", "availability", "metrics", "signature", "pollSeconds"):
            check("state has '%s'" % k, k in st)
        one = next((x for x in st["cases"] if x["caseId"] == c1), None)
        check("case carries progressiveStatus", bool(one and one.get("progressiveStatus")))
        check("case carries docData", bool(one and one.get("docData")))
        check("case carries timeline", bool(one and one.get("timeline")))
        check("mismatch surfaced as a WARN alert",
              any(a.get("sev") == "WARN" for a in st["alerts"]))
        check("json-serialisable", isinstance(json.dumps(st), str))

    finally:
        _restore()

    print("\n" + "=" * 60)
    print("  PASSED %d / %d" % (len(_PASS), len(_PASS) + len(_FAIL)))
    if _FAIL:
        print("  FAILED:")
        for n in _FAIL:
            print("    - " + n)
    print("=" * 60)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(run())
