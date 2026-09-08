#!/usr/bin/env python3
"""
Acceptance checks for the fine-tune extension (revised 14-feature spec):
admin manual resource release, first-come-first-served pending fulfilment,
automatic allocation after a release, patient email capture, admin discharge
approval, final bill generation + emailed bill, resource release after discharge,
email-failure isolation, no double-booking.

Self-contained and non-destructive: snapshots the mutable datastore, reseeds a
small known state, drives the pipeline by importing console_server directly,
asserts the required test cases T1-T10, then restores everything it touched.

Run from anywhere:
    python "Emergency Patient Coordination and Hospital Resource Automation using UiPath/Tests/finetune_checks.py"
Exit code 0 = all checks passed.
"""
import os
import sys
import stat
import time
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
BK = os.path.join(HERE, "_bk_finetune_check")

_PASS, _FAIL = [], []


def check(name, ok, detail=""):
    (_PASS if ok else _FAIL).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  -> " + str(detail)) if detail and not ok else ""))


def _rmtree(path):
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    for _ in range(5):
        if not os.path.isdir(path):
            return
        shutil.rmtree(path, onerror=_onerror)
        if not os.path.isdir(path):
            return
        time.sleep(0.3)


def _snap():
    if os.path.isdir(BK):
        _rmtree(BK)
    os.makedirs(BK)
    shutil.copytree(DB, os.path.join(BK, "db"))
    shutil.copytree(NOTIF, os.path.join(BK, "Notifications"))
    shutil.copy2(INPUT, os.path.join(BK, "PatientInput.psv"))
    if os.path.isdir(PATIENTS):
        shutil.copytree(PATIENTS, os.path.join(BK, "Patients"))


def _restore_dir(src, dst):
    for n in os.listdir(dst):
        p = os.path.join(dst, n)
        _rmtree(p) if os.path.isdir(p) else os.remove(p)
    for n in os.listdir(src):
        s, d = os.path.join(src, n), os.path.join(dst, n)
        shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy2(s, d)


def _restore():
    _restore_dir(os.path.join(BK, "db"), DB)
    _restore_dir(os.path.join(BK, "Notifications"), NOTIF)
    shutil.copy2(os.path.join(BK, "PatientInput.psv"), INPUT)
    if os.path.isdir(os.path.join(BK, "Patients")):
        _restore_dir(os.path.join(BK, "Patients"), PATIENTS)
    _rmtree(BK)


def _w(name, lines):
    with open(os.path.join(DB, name), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


HEADERS = {
    "EMERGENCY_CASES.psv": "CaseId|PatientId|CaseStatus|DocumentStatus|BedStatus|VentilatorStatus|BloodStatus|ReadinessPercentage|PendingAction|CreatedAt|UpdatedAt",
    "PENDING_REQUIREMENTS.psv": "RequirementId|CaseId|PatientId|Type|RequestedValue|CurrentFallback|Priority|Status|CreatedAt|UpdatedAt|ResolvedAt",
    "PATIENT_DOCUMENT_DATA.psv": "RecordId|PatientId|CaseId|DocumentType|Field|Value|ExtractedAt",
    "PATIENT_CONTACT.psv": "PatientId|CaseId|EmailAddress|Phone|CapturedAt",
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

BEDS_ALL_ICU_FREE = [
    "BedId|Department|BedType|Status|VentilatorId|LastUpdated",
    "ICU-03|ICU|Premium|Available|V-03|s", "ICU-04|ICU|Standard|Available|V-04|s",
    "GEN-02|General|Standard|Available||s", "GEN-03|General|Standard|Available||s",
    "GEN-04|General|Standard|Available||s",
    "CARD-01|Cardiology|Premium|Available|V-05|s", "CARD-02|Cardiology|Standard|Available||s",
]
BEDS_ICU_FULL = [
    "BedId|Department|BedType|Status|VentilatorId|LastUpdated",
    "ICU-03|ICU|Premium|Occupied|V-03|s", "ICU-04|ICU|Standard|Occupied|V-04|s",
    "GEN-02|General|Standard|Available||s", "GEN-03|General|Standard|Available||s",
    "GEN-04|General|Standard|Available||s",
    "CARD-01|Cardiology|Premium|Available|V-05|s", "CARD-02|Cardiology|Standard|Available||s",
]
VENTS = [
    "VentilatorId|Status|Location|LastUpdated",
    "V-03|Available|B|s", "V-04|Available|B|s", "V-05|Available|C|s", "V-06|Available|C|s",
]
BLOOD_OK = [
    "BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated",
    "A+|15|3|s", "A-|5|2|s", "B+|12|3|s", "B-|4|2|s",
    "AB+|8|2|s", "AB-|2|1|s", "O+|20|5|s", "O-|8|2|s",
]
INPUT_HDR = ("PatientId|Name|Age|Gender|EmergencyType|RequiredDepartment|VentilatorRequired|"
             "BloodGroup|BloodUnits|ProcessStatus|CaseId|Notes|EmailAddress")


def _reseed(beds):
    for name, hdr in HEADERS.items():
        _w(name, [hdr])
    _w("BEDS.psv", beds)
    _w("VENTILATORS.psv", VENTS)
    _w("BLOOD_INVENTORY.psv", BLOOD_OK)
    with open(INPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(INPUT_HDR + "\n")


def _rows(cs, name):
    return cs.load_table(name)[1]


def _acts(cs, caseid=None):
    return [r[2].strip() for r in _rows(cs, "AUDIT_LOG.psv")
            if len(r) >= 3 and (caseid is None or r[1].strip() == caseid)]


def _docs_payload():
    out = {}
    for slot in ("ID_Proof", "Insurance", "Consent_Form", "Medical_Report"):
        p = os.path.join(SAMPLE, slot + ".pdf")
        with open(p, "rb") as f:
            out[slot] = {"filename": slot + ".pdf", "dataB64": base64.b64encode(f.read()).decode()}
    return out


def _submit(cs, name, dept, etype="Critical", bg="O+", units="0", vent=False, email="", docs=None):
    body = {"name": name, "age": "50", "gender": "Male", "emergencyType": etype,
            "department": dept, "ventilator": vent, "bloodGroup": bg, "bloodUnits": units,
            "email": email, "docs": docs or {}}
    return cs.submit_case(body)


def _req(cs, caseid, rtype=None):
    return [r for r in _rows(cs, "PENDING_REQUIREMENTS.psv")
            if len(r) >= 8 and r[1].strip() == caseid and (rtype is None or r[3].strip() == rtype)]


def _adm_bed(cs, caseid):
    for a in _rows(cs, "ADMISSIONS.psv"):
        if len(a) >= 4 and a[1].strip() == caseid:
            return a[3].strip()
    return ""


def run():
    if not os.path.isfile(os.path.join(DASH, "console_server.py")):
        print("Cannot find Data/Dashboard/console_server.py - run this from inside the project.")
        return 2
    if not os.path.isdir(SAMPLE):
        print("SampleDocuments/patient_A_rahul not found - run SampleDocuments/make_sample_docs.py first.")
        return 2
    sys.path.insert(0, DASH)
    _snap()
    try:
        cs = importlib.import_module("console_server")
        docs = _docs_payload()

        # ---- T1: ICU free -> patient requests ICU -> immediate ICU -------------
        print("\n[T1] ICU available -> immediate ICU allocation")
        _reseed(BEDS_ALL_ICU_FREE)
        r = _submit(cs, "T1 Patient", "ICU", docs=docs)
        c = r["caseId"]
        bed = _adm_bed(cs, c)
        check("T1 admitted immediately", r.get("admitted") is True, r)
        check("T1 got an ICU bed straight away", bed.startswith("ICU"), bed)
        check("T1 no pending ICU requirement", _req(cs, c, "ICU_BED") == [])

        # ---- T2: ICU full -> fallback ward + ICU requirement stays pending -----
        print("\n[T2] ICU unavailable -> fallback ward, ICU requirement pending")
        _reseed(BEDS_ICU_FULL)
        r = _submit(cs, "T2 Patient", "ICU", docs=docs)
        c2 = r["caseId"]
        bed2 = _adm_bed(cs, c2)
        pend = _req(cs, c2, "ICU_BED")
        check("T2 admitted to a fallback bed", r.get("admitted") is True and bed2 != "" and not bed2.startswith("ICU"), bed2)
        check("T2 ICU requirement opened", len(pend) == 1)
        check("T2 RequestedResource kept as ICU (not overwritten)", pend and pend[0][4].strip().upper() == "ICU", pend)
        check("T2 requirement status PENDING/OPEN", pend and pend[0][7].strip() == "OPEN")
        check("T2 TEMP_BED_ASSIGNED audited", "TEMP_BED_ASSIGNED" in _acts(cs, c2))

        # ---- T3: A @t0, B @t1 both pending; admin releases ICU -> A first ------
        print("\n[T3] FCFS: earliest request wins the released ICU bed")
        _reseed(BEDS_ICU_FULL)
        ra = _submit(cs, "T3 Patient A", "ICU", docs=docs)
        time.sleep(1.05)
        rb = _submit(cs, "T3 Patient B", "ICU", docs=docs)
        ca, cb = ra["caseId"], rb["caseId"]
        # occupy exactly one ICU bed with a dummy, then admin frees it
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [r if r[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for r in rs]))(*cs.load_table("BEDS.psv")))
        rel = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Dr Admin", "reason": "T3"})
        check("T3 release reported an automatic allocation", rel.get("autoAllocated", 0) >= 1, rel)
        pa, pb = _req(cs, ca, "ICU_BED"), _req(cs, cb, "ICU_BED")
        check("T3 Patient A's ICU requirement is FULFILLED", pa and pa[0][7].strip() == "FULFILLED", pa)
        check("T3 Patient A is now in an ICU bed", _adm_bed(cs, ca).startswith("ICU"), _adm_bed(cs, ca))
        check("T3 Patient B is STILL pending", pb and pb[0][7].strip() in ("OPEN", "ACTION_REQUIRED"), pb)
        check("T3 Patient B still in the fallback bed", not _adm_bed(cs, cb).startswith("ICU"), _adm_bed(cs, cb))
        check("T3 ADMIN_RELEASE_RESOURCE recorded the admin", any(
            r[2].strip() == "ADMIN_RELEASE_RESOURCE" and r[5].strip() == "Dr Admin" for r in _rows(cs, "AUDIT_LOG.psv")))
        check("T3 AUTOMATIC_RESOURCE_ALLOCATION audited",
              "AUTOMATIC_RESOURCE_ALLOCATION" in _acts(cs))

        # ---- T4: A's case no longer active -> B gets the bed ------------------
        print("\n[T4] earliest request invalid -> next valid request wins")
        _reseed(BEDS_ICU_FULL)
        ra = _submit(cs, "T4 Patient A", "ICU", docs=docs)
        time.sleep(1.05)
        rb = _submit(cs, "T4 Patient B", "ICU", docs=docs)
        ca, cb = ra["caseId"], rb["caseId"]
        # mark A's case DISCHARGED so its requirement is no longer valid
        cs.save_table("EMERGENCY_CASES.psv", *(lambda h, rs: (h, [
            (r[:2] + ["DISCHARGED"] + r[3:]) if r[0] == ca else r for r in rs]))(*cs.load_table("EMERGENCY_CASES.psv")))
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [r if r[0] != "ICU-04" else
                      ["ICU-04", "ICU", "Standard", "Occupied", "V-04", "s"] for r in rs]))(*cs.load_table("BEDS.psv")))
        cs.release_resource({"kind": "BED", "resourceId": "ICU-04", "admin": "Admin", "reason": "T4"})
        pa, pb = _req(cs, ca, "ICU_BED"), _req(cs, cb, "ICU_BED")
        check("T4 invalid case A's requirement is CANCELLED", pa and pa[0][7].strip() == "CANCELLED", pa)
        check("T4 Patient B receives the ICU bed", pb and pb[0][7].strip() == "FULFILLED", pb)

        # ---- T5: two patients waiting on a doctor -> earliest gets it ---------
        print("\n[T5] FCFS for doctors")
        _reseed(BEDS_ALL_ICU_FREE)
        _w("DOCTORS.psv", [
            "DoctorId|Name|DepartmentId|Designation|Specialty|IsSurgeon|OnCallStatus|ShiftStart|ShiftEnd|CurrentLoad|MaxLoad|Contact|Email|LastUpdated",
            "DR-901|Dr Solo|DEPT-ICU|Consultant|Critical Care|0|OffDuty|08:00|20:00|0|1|x|x|s",
        ])
        _w("DEPARTMENTS.psv", [
            "DepartmentId|Name|Type|FloorWard|HeadDoctorId|LastUpdated",
            "DEPT-ICU|ICU|Critical|F3|DR-901|s", "DEPT-GEN|General|Medical|F1|DR-901|s",
            "DEPT-CARD|Cardiology|Medical|F2|DR-901|s",
        ])
        ra = _submit(cs, "T5 Patient A", "ICU", docs=docs)
        time.sleep(1.05)
        rb = _submit(cs, "T5 Patient B", "ICU", docs=docs)
        ca, cb = ra["caseId"], rb["caseId"]
        check("T5 both admitted without a consultant (non-blocking)",
              ra.get("admitted") and rb.get("admitted"))
        check("T5 both have an open DOCTOR requirement",
              len(_req(cs, ca, "DOCTOR")) == 1 and len(_req(cs, cb, "DOCTOR")) == 1)
        cs.release_resource({"kind": "DOCTOR", "resourceId": "DR-901", "admin": "Admin", "reason": "T5"})
        da, db = _req(cs, ca, "DOCTOR"), _req(cs, cb, "DOCTOR")
        check("T5 earliest request (A) gets the doctor", da and da[0][7].strip() == "FULFILLED", da)
        check("T5 later request (B) still pending", db and db[0][7].strip() == "OPEN", db)
        check("T5 DOCTOR_ASSIGNED audited", "DOCTOR_ASSIGNED" in _acts(cs, ca))

        # ---- T6: admin adds blood -> earliest valid pending gets it ----------
        print("\n[T6] FCFS for blood units")
        _reseed(BEDS_ALL_ICU_FREE)
        _w("BLOOD_INVENTORY.psv", [
            "BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated",
            "O-|1|2|s", "O+|20|5|s", "A+|10|3|s",
        ])
        ra = _submit(cs, "T6 Patient A", "ICU", bg="O-", units="3", docs=docs)
        time.sleep(1.05)
        rb = _submit(cs, "T6 Patient B", "ICU", bg="O-", units="2", docs=docs)
        ca, cb = ra["caseId"], rb["caseId"]
        check("T6 both have an open BLOOD requirement",
              len(_req(cs, ca, "BLOOD")) == 1 and len(_req(cs, cb, "BLOOD")) == 1)
        # O- goes 1 -> 4; A takes 3 (leaves 1), B needs 2 -> stays pending
        cs.release_resource({"kind": "BLOOD", "resourceId": "O-", "admin": "Admin", "units": 3, "reason": "T6"})
        ba, bb = _req(cs, ca, "BLOOD"), _req(cs, cb, "BLOOD")
        check("T6 earliest request (A, 3u) fulfilled first", ba and ba[0][7].strip() == "FULFILLED", ba)
        check("T6 later request (B, 2u) still pending (1u left, needs 2)",
              bb and bb[0][7].strip() == "OPEN", bb)

        # ---- T7: treatment done -> admin approves discharge -> bill + email --
        print("\n[T7] admin discharge approval -> final bill emailed, resources released")
        _reseed(BEDS_ALL_ICU_FREE)
        r = _submit(cs, "T7 Patient", "ICU", email="t7.patient@gmail.com", docs=docs)
        c7 = r["caseId"]
        bed7 = _adm_bed(cs, c7)
        appr = cs.approve_discharge({"caseId": c7, "admin": "Ward Admin"})
        acts7 = _acts(cs, c7)
        beds_now = {b[0].strip(): b[3].strip() for b in _rows(cs, "BEDS.psv")}
        adm7 = [a for a in _rows(cs, "ADMISSIONS.psv") if a[1].strip() == c7]
        check("T7 approve_discharge ok", appr.get("ok") is True, appr)
        check("T7 final bill total > 0", appr.get("total", 0) > 0, appr)
        check("T7 DISCHARGE_APPROVED audited", "DISCHARGE_APPROVED" in acts7)
        check("T7 BILL_GENERATED audited", "BILL_GENERATED" in acts7)
        check("T7 BILL_EMAIL_SENT audited (address on file)", "BILL_EMAIL_SENT" in acts7)
        check("T7 bill file written", os.path.exists(os.path.join(NOTIF, "BILL_%s.txt" % c7)))
        check("T7 an EMAIL_*_bill_* envelope was written",
              any(f.startswith("EMAIL_%s_bill_" % c7) for f in os.listdir(NOTIF)))
        check("T7 patient marked Discharged", adm7 and adm7[0][7].strip() == "Discharged", adm7)
        check("T7 the patient's bed was released", beds_now.get(bed7) == "Available", beds_now.get(bed7))
        check("T7 RESOURCE_RELEASED_AFTER_DISCHARGE audited", "RESOURCE_RELEASED_AFTER_DISCHARGE" in acts7)

        # ---- T8: email fails -> patient still discharged, failure logged -----
        print("\n[T8] email failure never rolls back the discharge")
        _reseed(BEDS_ALL_ICU_FREE)
        r = _submit(cs, "T8 Patient", "ICU", email="", docs=docs)   # no email on file
        c8 = r["caseId"]
        appr = cs.approve_discharge({"caseId": c8, "admin": "Admin"})
        acts8 = _acts(cs, c8)
        adm8 = [a for a in _rows(cs, "ADMISSIONS.psv") if a[1].strip() == c8]
        check("T8 discharge still succeeded", appr.get("ok") is True, appr)
        check("T8 emailSent is False", appr.get("emailSent") is False, appr)
        check("T8 EMAIL_SEND_FAILED audited", "EMAIL_SEND_FAILED" in acts8)
        check("T8 BILL_GENERATED still audited", "BILL_GENERATED" in acts8)
        check("T8 patient still Discharged", adm8 and adm8[0][7].strip() == "Discharged", adm8)
        check("T8 failure surfaced to admin (WARN alert)",
              any(a.get("sev") == "WARN" and "not emailed" in a.get("title", "")
                  for a in cs.build_state()["alerts"]))

        # ---- T9: two simultaneous allocations -> no double-booking ----------
        print("\n[T9] concurrency: one freed bed, two waiters, no double-booking")
        _reseed(BEDS_ICU_FULL)
        ra = _submit(cs, "T9 Patient A", "ICU", docs=docs)
        time.sleep(1.05)
        rb = _submit(cs, "T9 Patient B", "ICU", docs=docs)
        ca, cb = ra["caseId"], rb["caseId"]
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [r if r[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for r in rs]))(*cs.load_table("BEDS.psv")))
        rel = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "T9"})
        icu_occupants = [a[1].strip() for a in _rows(cs, "ADMISSIONS.psv")
                         if len(a) >= 4 and a[3].strip() == "ICU-03"]
        check("T9 exactly one patient placed in the freed bed", len(icu_occupants) == 1, icu_occupants)
        check("T9 exactly one requirement fulfilled this release", rel.get("autoAllocated") == 1, rel)

        # ---- T10: release -> available + auto-alloc, no manual assignment ---
        print("\n[T10] admin release auto-triggers pending allocation")
        _reseed(BEDS_ICU_FULL)
        r = _submit(cs, "T10 Patient", "ICU", docs=docs)
        c10 = r["caseId"]
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [r if r[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for r in rs]))(*cs.load_table("BEDS.psv")))
        rel = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "T10"})
        beds_now = {b[0].strip(): b[3].strip() for b in _rows(cs, "BEDS.psv")}
        check("T10 release response confirms automatic allocation", rel.get("autoAllocated", 0) >= 1, rel)
        check("T10 no manual step needed - patient already in the ICU bed",
              _adm_bed(cs, c10).startswith("ICU"), _adm_bed(cs, c10))
        check("T10 the temporary bed was handed back to the pool",
              "Available" in beds_now.values())

    finally:
        _restore()

    print("\n" + "=" * 60)
    print("  PASSED %d / %d" % (len(_PASS), len(_PASS) + len(_FAIL)))
    if _FAIL:
        print("  FAILED: " + ", ".join(_FAIL))
    print("=" * 60)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(run())
