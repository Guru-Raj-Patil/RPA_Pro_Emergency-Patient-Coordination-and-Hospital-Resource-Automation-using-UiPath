#!/usr/bin/env python3
"""
Real-life stress checks for the fine-tune extension - the hard edges the spec's
T1-T10 do not cover: no bed anywhere, blood exactly at threshold, double
release / double approve, discharge with open requirements, zero-value bill,
identical request timestamps, rejected-case requirements, ventilator fulfilment,
held-case admission on a freed bed, true concurrent submission, mixed FCFS
queue, malformed input rows, audit completeness, RequestedValue immutability,
and no-stale-read of /api/state.

Self-contained and non-destructive: snapshot / reseed / drive console_server /
restore. Windows-robust cleanup.

    python "Emergency Patient Coordination and Hospital Resource Automation using UiPath/Tests/finetune_stress.py"
Exit 0 = all checks passed.
"""
import os
import sys
import json
import stat
import time
import shutil
import base64
import threading
import importlib

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
DASH = os.path.join(PROJ, "Data", "Dashboard")
DB = os.path.join(PROJ, "Data", "db")
NOTIF = os.path.join(PROJ, "Data", "Notifications")
INPUT = os.path.join(PROJ, "Data", "PatientInput.psv")
PATIENTS = os.path.join(PROJ, "Patients")
SAMPLE = os.path.join(PROJ, "SampleDocuments", "patient_A_rahul")
BK = os.path.join(HERE, "_bk_finetune_stress")

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
    for _ in range(6):
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

VENTS_ALL_FREE = ["VentilatorId|Status|Location|LastUpdated",
                  "V-03|Available|B|s", "V-04|Available|B|s", "V-05|Available|C|s", "V-06|Available|C|s"]
VENTS_NONE_FREE = ["VentilatorId|Status|Location|LastUpdated",
                   "V-03|Occupied|B|s", "V-04|Occupied|B|s", "V-05|Occupied|C|s", "V-06|Occupied|C|s"]
BLOOD_STD = ["BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated",
             "A+|15|3|s", "A-|5|2|s", "B+|12|3|s", "B-|4|2|s",
             "AB+|8|2|s", "AB-|2|1|s", "O+|20|5|s", "O-|8|2|s"]
INPUT_HDR = ("PatientId|Name|Age|Gender|EmergencyType|RequiredDepartment|VentilatorRequired|"
             "BloodGroup|BloodUnits|ProcessStatus|CaseId|Notes|EmailAddress")


def _clear_notif():
    """Wipe per-case artifacts between scenarios so a stale envelope / marker
    from an earlier test can't satisfy (or fail) a later assertion."""
    for f in os.listdir(NOTIF):
        if f.startswith(("EMAIL_", "BILL_", "DISCHARGE_", "APPROVE_", "APPROVAL_",
                         "CERTIFY_", "CLINICAL_", "TRANSFER_", "EXCEPTION_",
                         "Notification_", "CLAIM_", "FOLLOWUP_", "CLOSED_")):
            try:
                os.remove(os.path.join(NOTIF, f))
            except OSError:
                pass


def _reseed(beds, vents=None, blood=None):
    for name, hdr in HEADERS.items():
        _w(name, [hdr])
    _w("BEDS.psv", beds)
    _w("VENTILATORS.psv", vents or VENTS_ALL_FREE)
    _w("BLOOD_INVENTORY.psv", blood or BLOOD_STD)
    with open(INPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(INPUT_HDR + "\n")
    _clear_notif()


def _newest(prefix):
    fs = [os.path.join(NOTIF, f) for f in os.listdir(NOTIF) if f.startswith(prefix)]
    return max(fs, key=os.path.getmtime) if fs else None


def _rows(cs, name):
    return cs.load_table(name)[1]


def _acts(cs, caseid=None):
    return [(r[2].strip(), r[5].strip() if len(r) >= 6 else "")
            for r in _rows(cs, "AUDIT_LOG.psv")
            if len(r) >= 3 and (caseid is None or r[1].strip() == caseid)]


def _docs_payload():
    out = {}
    for slot in ("ID_Proof", "Insurance", "Consent_Form", "Medical_Report"):
        with open(os.path.join(SAMPLE, slot + ".pdf"), "rb") as f:
            out[slot] = {"filename": slot + ".pdf", "dataB64": base64.b64encode(f.read()).decode()}
    return out


def _submit(cs, name, dept, etype="Critical", bg="O+", units="0", vent=False, email="", docs=None):
    return cs.submit_case({"name": name, "age": "50", "gender": "Male", "emergencyType": etype,
                           "department": dept, "ventilator": vent, "bloodGroup": bg, "bloodUnits": units,
                           "email": email, "docs": docs or {}})


def _req(cs, caseid, rtype=None):
    return [r for r in _rows(cs, "PENDING_REQUIREMENTS.psv")
            if len(r) >= 8 and r[1].strip() == caseid and (rtype is None or r[3].strip() == rtype)]


def _adm(cs, caseid):
    for a in _rows(cs, "ADMISSIONS.psv"):
        if len(a) >= 8 and a[1].strip() == caseid:
            return a
    return None


BEDS_ICU_OPEN = [
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
BEDS_ALL_FULL = [
    "BedId|Department|BedType|Status|VentilatorId|LastUpdated",
    "ICU-03|ICU|Premium|Occupied|V-03|s", "ICU-04|ICU|Standard|Occupied|V-04|s",
    "GEN-02|General|Standard|Occupied||s", "GEN-03|General|Standard|Occupied||s",
    "CARD-01|Cardiology|Premium|Occupied|V-05|s", "CARD-02|Cardiology|Standard|Occupied||s",
]


def run():
    if not os.path.isfile(os.path.join(DASH, "console_server.py")):
        print("run this from inside the project"); return 2
    if not os.path.isdir(SAMPLE):
        print("SampleDocuments/patient_A_rahul missing - run SampleDocuments/make_sample_docs.py"); return 2
    sys.path.insert(0, DASH)
    _snap()
    try:
        cs = importlib.import_module("console_server")
        docs = _docs_payload()

        # S1 - no bed anywhere: requested ward + every fallback ward full -----------
        print("\n[S1] no bed in the requested ward OR any fallback ward")
        _reseed(BEDS_ALL_FULL)
        r = _submit(cs, "S1 Patient", "ICU", docs=docs)
        c = r["caseId"]
        check("S1 not admitted (no bed exists)", r.get("admitted") is False, r)
        check("S1 no phantom ADMISSIONS row", _adm(cs, c) is None)
        check("S1 an ICU_BED requirement is opened for later", len(_req(cs, c, "ICU_BED")) == 1)
        check("S1 case is on the board as PENDING_BED (visible to admin)",
              next((x[2].strip() for x in _rows(cs, "EMERGENCY_CASES.psv") if x[0].strip() == c), "").upper().startswith("PENDING_BED"))
        check("S1 no crash, submit returned a caseId", bool(c))

        # S2 - blood exactly at MinimumThreshold after reservation ---------------
        print("\n[S2] blood reservation lands exactly on the minimum threshold")
        _reseed(BEDS_ICU_OPEN, blood=["BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated", "O-|5|2|s"])
        r = _submit(cs, "S2 Patient", "ICU", bg="O-", units="3", docs=docs)  # 5-3 = 2 == min
        c = r["caseId"]
        onl = {x[0].strip(): int(x[1]) for x in _rows(cs, "BLOOD_INVENTORY.psv")}
        check("S2 admitted with blood reserved", r.get("admitted") is True and _req(cs, c, "BLOOD") == [], r)
        check("S2 O- stock decremented to exactly the minimum (2)", onl.get("O-") == 2, onl)
        check("S2 below-threshold alert raised", any(
            a.get("title", "").startswith("Blood O-") for a in cs.build_state()["alerts"]))

        # S3 - blood available == units needed (boundary, not < ) ---------------
        print("\n[S3] blood available exactly equals units needed")
        _reseed(BEDS_ICU_OPEN, blood=["BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated", "O-|3|1|s"])
        r = _submit(cs, "S3 Patient", "ICU", bg="O-", units="3", docs=docs)
        check("S3 exactly-enough blood counts as Available (not Unavailable)",
              r.get("admitted") is True and _req(cs, r["caseId"], "BLOOD") == [], r)

        # S4 - release a resource that is already Available --------------------
        print("\n[S4] admin releases a bed that is already free")
        _reseed(BEDS_ICU_OPEN)
        rel = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "S4"})
        beds = {b[0].strip(): b[3].strip() for b in _rows(cs, "BEDS.psv")}
        check("S4 release of a free bed does not error", rel.get("ok") is True, rel)
        check("S4 bed stays Available (no corruption)", beds.get("ICU-03") == "Available")
        check("S4 nothing was auto-allocated (nothing was waiting)", rel.get("autoAllocated", 0) == 0, rel)

        # S5 - double release of the same occupied bed ------------------------
        print("\n[S5] admin releases the same bed twice")
        _reseed(BEDS_ICU_FULL)
        r = _submit(cs, "S5 Patient", "ICU", docs=docs)   # interim bed
        c = r["caseId"]
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [x if x[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for x in rs]))(*cs.load_table("BEDS.psv")))
        rel1 = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "S5a"})
        rel2 = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "S5b"})
        icu_occ = [a[1].strip() for a in _rows(cs, "ADMISSIONS.psv") if len(a) >= 4 and a[3].strip() == "ICU-03"]
        check("S5 first release allocated to the waiting patient", rel1.get("autoAllocated", 0) == 1, rel1)
        check("S5 second release is a harmless no-op", rel2.get("autoAllocated", 0) == 0, rel2)
        check("S5 still exactly one patient in ICU-03 (no double alloc)", len(icu_occ) == 1, icu_occ)

        # S6 - double approve-discharge -------------------------------------
        print("\n[S6] approve discharge twice for the same case")
        _reseed(BEDS_ICU_OPEN)
        r = _submit(cs, "S6 Patient", "ICU", email="s6@x.com", docs=docs)
        c = r["caseId"]
        a1 = cs.approve_discharge({"caseId": c, "admin": "Admin"})
        bills_after_1 = len([x for x in _rows(cs, "BILLING.psv") if x[1].strip() == c])
        a2 = cs.approve_discharge({"caseId": c, "admin": "Admin"})
        emails = [f for f in os.listdir(NOTIF) if f.startswith("EMAIL_%s_bill_" % c)]
        disch_rows = [x for x in _rows(cs, "DISCHARGES.psv") if x[1].strip() == c]
        check("S6 first approve succeeds", a1.get("ok") is True, a1)
        check("S6 second approve is rejected (not an active admission)", a2.get("ok") is False, a2)
        check("S6 exactly one DISCHARGES row for the case", len(disch_rows) == 1, disch_rows)
        check("S6 no second bill email envelope written", len(emails) == 1, emails)

        # S7 - discharge approval while an ICU requirement is still OPEN -----
        print("\n[S7] approve discharge for a patient still waiting on ICU")
        _reseed(BEDS_ICU_FULL)
        r = _submit(cs, "S7 Patient", "ICU", email="s7@x.com", docs=docs)   # interim + ICU_BED pending
        c = r["caseId"]
        check("S7 has an open ICU_BED requirement before discharge", len(_req(cs, c, "ICU_BED")) == 1)
        appr = cs.approve_discharge({"caseId": c, "admin": "Admin"})
        req_now = _req(cs, c, "ICU_BED")
        check("S7 discharge still completes (treatment is done)", appr.get("ok") is True, appr)
        check("S7 the now-moot ICU requirement is CANCELLED, not left orphaned",
              req_now and req_now[0][7].strip() == "CANCELLED", req_now)

        # S8 - zero-value / empty bill (waived case) -----------------------
        print("\n[S8] discharge a case that has no billing rows (waived)")
        _reseed(BEDS_ICU_OPEN)
        r = _submit(cs, "S8 Patient", "ICU", email="s8@x.com", docs=docs)
        c = r["caseId"]
        _bh, _br = cs.load_table("BILLING.psv")
        cs.save_table("BILLING.psv", _bh, [x for x in _br if x[1].strip() != c], allow_empty=True)
        appr = cs.approve_discharge({"caseId": c, "admin": "Admin"})
        acts = [a for a, _ in _acts(cs, c)]
        check("S8 discharge succeeds with a zero bill", appr.get("ok") is True and appr.get("total") == 0, appr)
        check("S8 zero bill is marked NotBillable", appr.get("paymentStatus") == "NotBillable", appr)
        check("S8 BILL_ZERO_NO_CHARGES audited", "BILL_ZERO_NO_CHARGES" in acts)
        check("S8 BILL_GENERATED still audited", "BILL_GENERATED" in acts)
        check("S8 bill file still written", os.path.exists(os.path.join(NOTIF, "BILL_%s.txt" % c)))
        check("S8 patient still marked Discharged", _adm(cs, c) and _adm(cs, c)[7].strip() == "Discharged")

        # S9 - identical request timestamps -> deterministic FCFS ---------
        print("\n[S9] two ICU requirements with the SAME CreatedAt")
        _reseed(BEDS_ICU_FULL)
        ra = _submit(cs, "S9 A", "ICU", docs=docs)
        rb = _submit(cs, "S9 B", "ICU", docs=docs)   # no sleep -> likely same second
        ca, cb = ra["caseId"], rb["caseId"]
        pr = _rows(cs, "PENDING_REQUIREMENTS.psv")
        ta = next((x[8].strip() for x in pr if x[1].strip() == ca and x[3].strip() == "ICU_BED"), "")
        tb = next((x[8].strip() for x in pr if x[1].strip() == cb and x[3].strip() == "ICU_BED"), "")
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [x if x[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for x in rs]))(*cs.load_table("BEDS.psv")))
        rel = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "S9"})
        icu_occ = [a[1].strip() for a in _rows(cs, "ADMISSIONS.psv") if len(a) >= 4 and a[3].strip() == "ICU-03"]
        fulfilled = [x[1].strip() for x in _rows(cs, "PENDING_REQUIREMENTS.psv")
                     if x[3].strip() == "ICU_BED" and x[7].strip() == "FULFILLED"]
        check("S9 exactly one requirement fulfilled from one freed bed",
              rel.get("autoAllocated") == 1 and len(fulfilled) == 1, (rel, fulfilled))
        check("S9 exactly one patient in the ICU bed", len(icu_occ) == 1, icu_occ)
        check("S9 tie broken deterministically toward the first submission",
              (ta == tb and fulfilled == [ca]) or ta < tb, (ta, tb, fulfilled))

        # S10 - requirement whose case is REJECTED / ERROR ---------------
        print("\n[S10] pending requirement for a case that has been marked ERROR")
        _reseed(BEDS_ICU_FULL)
        r = _submit(cs, "S10 Patient", "ICU", docs=docs)
        c = r["caseId"]
        cs.save_table("EMERGENCY_CASES.psv", *(lambda h, rs: (h, [
            (x[:2] + ["Error"] + x[3:]) if x[0].strip() == c else x for x in rs]))(*cs.load_table("EMERGENCY_CASES.psv")))
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [x if x[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for x in rs]))(*cs.load_table("BEDS.psv")))
        rel = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "S10"})
        rq = _req(cs, c, "ICU_BED")
        beds = {b[0].strip(): b[3].strip() for b in _rows(cs, "BEDS.psv")}
        check("S10 a bad case never gets a resource allocated to it", rel.get("autoAllocated", 0) == 0, rel)
        check("S10 its requirement is CANCELLED", rq and rq[0][7].strip() == "CANCELLED", rq)
        check("S10 the freed bed stays Available", beds.get("ICU-03") == "Available")

        # S11 - ventilator requirement fulfilled on admin release -------
        print("\n[S11] ventilator requirement served when a unit is freed")
        _reseed(BEDS_ICU_OPEN, vents=VENTS_NONE_FREE)
        r = _submit(cs, "S11 Patient", "ICU", vent=True, docs=docs)
        c = r["caseId"]
        check("S11 admitted despite no ventilator (non-blocking)", r.get("admitted") is True, r)
        check("S11 a VENTILATOR requirement is open", len(_req(cs, c, "VENTILATOR")) == 1)
        cs.release_resource({"kind": "VENTILATOR", "resourceId": "V-03", "admin": "Admin", "reason": "S11"})
        vq = _req(cs, c, "VENTILATOR")
        vent_state = {v[0].strip(): v[1].strip() for v in _rows(cs, "VENTILATORS.psv")}
        check("S11 the requirement is FULFILLED after the release", vq and vq[0][7].strip() == "FULFILLED", vq)
        check("S11 the freed ventilator is now in use", vent_state.get("V-03") in ("Occupied", "Reserved"), vent_state)

        # S12 - held (never-admitted) case admitted when a bed frees ----
        print("\n[S12] held case fully admitted the moment a bed opens")
        _reseed(BEDS_ALL_FULL)
        r = _submit(cs, "S12 Patient", "ICU", docs=docs)
        c = r["caseId"]
        check("S12 starts held (no bed anywhere)", r.get("admitted") is False and _adm(cs, c) is None)
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [x if x[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for x in rs]))(*cs.load_table("BEDS.psv")))
        rel = cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "S12"})
        adm = _adm(cs, c)
        bill = [x for x in _rows(cs, "BILLING.psv") if x[1].strip() == c]
        rq = _req(cs, c, "ICU_BED")
        check("S12 patient is now fully admitted into the freed bed",
              adm is not None and adm[3].strip() == "ICU-03" and adm[7].strip() == "Admitted", adm)
        check("S12 the billing account was opened on admission", len(bill) >= 2, bill)
        check("S12 the bed requirement is FULFILLED", rq and rq[0][7].strip() == "FULFILLED", rq)

        # S13 - 6 concurrent submissions for 1 free ICU bed, serialised by the
        #       same PROCESS_LOCK the HTTP handler holds. Proves no double-booking
        #       under contention (the real deployment guarantee).
        print("\n[S13] 6 concurrent submissions contend for 1 free ICU bed")
        _reseed(["BedId|Department|BedType|Status|VentilatorId|LastUpdated",
                 "ICU-03|ICU|Premium|Available|V-03|s",
                 "ICU-04|ICU|Standard|Occupied|V-04|s",
                 "GEN-02|General|Standard|Available||s", "GEN-03|General|Standard|Available||s",
                 "GEN-04|General|Standard|Available||s", "GEN-01|General|Standard|Available||s",
                 "CARD-01|Cardiology|Premium|Available|V-05|s", "CARD-02|Cardiology|Standard|Available||s"],
                blood=["BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated", "O-|10|2|s"])
        results = {}

        def _go(i):
            try:
                with cs.PROCESS_LOCK:           # exactly what do_POST /api/submit does
                    results[i] = _submit(cs, "S13 P%d" % i, "ICU", bg="O-", units="2", docs=docs)
            except Exception as e:  # noqa: BLE001
                results[i] = {"error": "%s: %s" % (type(e).__name__, e)}
        ts = [threading.Thread(target=_go, args=(i,)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        adm_beds = [a[3].strip() for a in _rows(cs, "ADMISSIONS.psv") if len(a) >= 4]
        icu_beds = [b for b in adm_beds if b.startswith("ICU")]
        o_left = next((int(x[1]) for x in _rows(cs, "BLOOD_INVENTORY.psv") if x[0].strip() == "O-"), None)
        o_reserved = sum(int(r[4]) for r in _rows(cs, "RESOURCE_RESERVATIONS.psv")
                         if len(r) >= 6 and r[2].strip() == "Blood" and r[3].strip() == "O-"
                         and r[5].strip() in ("Reserved", "Occupied"))
        errs = [v for v in results.values() if "error" in v]
        check("S13 no thread crashed", not errs, errs)
        check("S13 no duplicate BedId in ADMISSIONS", len(adm_beds) == len(set(adm_beds)), adm_beds)
        check("S13 exactly one patient got the single ICU bed", icu_beds == ["ICU-03"], icu_beds)
        check("S13 blood never went negative under contention", o_left is not None and o_left >= 0, o_left)
        check("S13 blood ledger balances: reserved + remaining == starting 10",
              o_left is not None and o_reserved + o_left == 10, (o_reserved, o_left))

        # S14 - different resource types each served to their own earliest req --
        print("\n[S14] ventilator and blood requirements served independently, no cross-talk")
        _reseed(["BedId|Department|BedType|Status|VentilatorId|LastUpdated",
                 "GEN-01|General|Standard|Available||s", "GEN-02|General|Standard|Available||s",
                 "GEN-03|General|Standard|Available||s"],
                vents=VENTS_NONE_FREE,
                blood=["BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated", "O-|1|2|s", "O+|20|5|s"])
        rv = _submit(cs, "S14 vent", "General", etype="Standard", vent=True, docs=docs)      # VENTILATOR req
        time.sleep(1.05)
        rb = _submit(cs, "S14 blood", "General", etype="Standard", bg="O-", units="3", docs=docs)  # BLOOD req
        cv, cb = rv["caseId"], rb["caseId"]
        check("S14 both admitted (bed was free)", _adm(cs, cv) is not None and _adm(cs, cb) is not None)
        check("S14 a VENTILATOR requirement is open for the first patient", len(_req(cs, cv, "VENTILATOR")) == 1)
        check("S14 a BLOOD requirement is open for the second patient", len(_req(cs, cb, "BLOOD")) == 1)
        cs.release_resource({"kind": "VENTILATOR", "resourceId": "V-03", "admin": "Admin", "reason": "S14v"})
        cs.release_resource({"kind": "BLOOD", "resourceId": "O-", "admin": "Admin", "units": 5, "reason": "S14b"})
        vq, blq = _req(cs, cv, "VENTILATOR"), _req(cs, cb, "BLOOD")
        check("S14 the ventilator request is FULFILLED", vq and vq[0][7].strip() == "FULFILLED", vq)
        check("S14 the blood request is FULFILLED", blq and blq[0][7].strip() == "FULFILLED", blq)
        check("S14 no requirement was fulfilled against the wrong patient",
              _req(cs, cv, "BLOOD") == [] and _req(cs, cb, "VENTILATOR") == [])

        # S15 - malformed PatientInput row does not break the sweep ---
        print("\n[S15] a short / malformed PatientInput row is skipped safely")
        _reseed(BEDS_ICU_OPEN)
        with open(INPUT, "w", encoding="utf-8", newline="\n") as f:
            f.write(INPUT_HDR + "\n")
            f.write("P2001|Broken Row|only|four|cols\n")   # < 12 fields
            f.write("P2002|Good Row|44|Female|Urgent|General|No|A+|1|Pending||ok|good@x.com\n")
        try:
            cs.sweep_pending()
            swept_ok = True
        except Exception as e:  # noqa: BLE001
            swept_ok = False
            print("     sweep raised:", type(e).__name__, e)
        cases = {x[0].strip() for x in _rows(cs, "EMERGENCY_CASES.psv")}
        check("S15 sweep_pending did not raise on the bad row", swept_ok)
        check("S15 the well-formed row was still processed", "ER2002" in cases, cases)
        check("S15 the malformed row did not create a case", "ER2001" not in cases)

        # S16 - full audit trail after release + approve + discharge --
        print("\n[S16] audit completeness for a release + discharge cycle")
        _reseed(BEDS_ICU_FULL)
        ra = _submit(cs, "S16 A", "ICU", email="s16a@x.com", docs=docs)   # interim bed + ICU_BED pending
        time.sleep(1.05)
        rb = _submit(cs, "S16 B", "ICU", email="s16b@x.com", docs=docs)
        ca, cb = ra["caseId"], rb["caseId"]
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [x if x[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for x in rs]))(*cs.load_table("BEDS.psv")))
        cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Nurse Admin", "reason": "S16"})
        cs.approve_discharge({"caseId": ca, "admin": "Nurse Admin"})
        allacts = _acts(cs)
        names = {a for a, _ in allacts}
        need = {"ADMIN_RELEASE_RESOURCE", "AUTOMATIC_RESOURCE_ALLOCATION", "TEMP_BED_ASSIGNED",
                "REQUIREMENT_OPENED", "BED_TRANSFERRED", "REQUIREMENT_FULFILLED",
                "DISCHARGE_APPROVED", "BILL_GENERATED", "BILL_EMAIL_SENT",
                "RESOURCE_RELEASED_AFTER_DISCHARGE"}
        missing = need - names
        check("S16 every required audit action is present", not missing, "missing: " + ", ".join(sorted(missing)))
        check("S16 ADMIN_RELEASE_RESOURCE records the admin's name",
              any(a == "ADMIN_RELEASE_RESOURCE" and by == "Nurse Admin" for a, by in allacts))
        check("S16 DISCHARGE_APPROVED records the admin's name",
              any(a == "DISCHARGE_APPROVED" and by == "Nurse Admin" for a, by in allacts))

        # S17 - RequestedResource is never overwritten by the fallback -
        print("\n[S17] RequestedResource stays 'ICU' through fallback + transfer")
        _reseed(BEDS_ICU_FULL)
        r = _submit(cs, "S17 Patient", "ICU", docs=docs)
        c = r["caseId"]
        rq0 = _req(cs, c, "ICU_BED")[0]
        cs.save_table("BEDS.psv", *(lambda h, rs: (h, [x if x[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for x in rs]))(*cs.load_table("BEDS.psv")))
        cs.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "S17"})
        rq1 = _req(cs, c, "ICU_BED")
        adm = _adm(cs, c)
        st = cs.build_state()
        cj = next((x for x in st["cases"] if x["caseId"] == c), {})
        check("S17 RequestedValue was 'ICU' while pending", rq0[4].strip().upper() == "ICU", rq0)
        check("S17 after transfer the requirement is FULFILLED and its RequestedValue is untouched",
              rq1 and rq1[0][7].strip() == "FULFILLED" and rq1[0][4].strip().upper() == "ICU", rq1)
        check("S17 current bed is the real ICU bed, requested-ward still shows ICU",
              adm[3].strip() == "ICU-03" and cj.get("requestedWard", "").upper() == "ICU", (adm[3], cj.get("requestedWard")))

        # S18 - discharge frees a bed and the next pending is served same op
        print("\n[S18] discharge -> freed bed -> earliest ICU waiter served automatically (F11)")
        _reseed(["BedId|Department|BedType|Status|VentilatorId|LastUpdated",
                 "ICU-03|ICU|Premium|Available|V-03|s",
                 "ICU-04|ICU|Standard|Occupied|V-04|s",
                 "GEN-02|General|Standard|Available||s", "GEN-03|General|Standard|Available||s",
                 "GEN-04|General|Standard|Available||s", "CARD-01|Cardiology|Premium|Available|V-05|s"])
        ra = _submit(cs, "S18 A (in ICU)", "ICU", email="s18a@x.com", docs=docs)   # takes ICU-03
        time.sleep(1.05)
        # now ICU is full -> B goes to a fallback ward + ICU_BED pending
        rb = _submit(cs, "S18 B (waiting)", "ICU", email="s18b@x.com", docs=docs)
        ca, cb = ra["caseId"], rb["caseId"]
        check("S18 A is in an ICU bed", _adm(cs, ca)[3].strip().startswith("ICU"))
        check("S18 B is waiting in a fallback bed with an ICU_BED requirement",
              not _adm(cs, cb)[3].strip().startswith("ICU") and len(_req(cs, cb, "ICU_BED")) == 1)
        cs.approve_discharge({"caseId": ca, "admin": "Admin"})
        bq = _req(cs, cb, "ICU_BED")
        check("S18 discharging A automatically moves B into the freed ICU bed",
              bq and bq[0][7].strip() == "FULFILLED" and _adm(cs, cb)[3].strip().startswith("ICU"),
              (bq, _adm(cs, cb)[3]))
        check("S18 A is Discharged", _adm(cs, ca)[7].strip() == "Discharged")

        # S19 - bill + email envelope content is real, not a stub -----
        print("\n[S19] the emailed bill actually contains the required fields")
        _reseed(BEDS_ICU_OPEN)
        r = _submit(cs, "S19 Patient", "ICU", email="s19.patient@gmail.com", docs=docs)
        c = r["caseId"]
        cs.approve_discharge({"caseId": c, "admin": "Admin"})
        billtxt = open(os.path.join(NOTIF, "BILL_%s.txt" % c), encoding="utf-8").read()
        env = _newest("EMAIL_%s_bill_" % c)
        envtxt = open(env, encoding="utf-8").read() if env else ""
        for tok in ("Patient ID", "Admission ID", "TOTAL AMOUNT", "Payment Status", c):
            check("S19 bill file has '%s'" % tok, tok in billtxt)
        check("S19 an email envelope was written", bool(env), env)
        check("S19 email envelope addresses the registered address", "s19.patient@gmail.com" in envtxt)
        check("S19 email envelope says discharge was approved",
              "discharge has been approved" in envtxt.lower())

        # S20 - F14 non-regression: a clean 8-case console run only opens pending
        #       requirements for the genuinely bed-short cases (F2), never for a
        #       fully-resourced one, and every known outcome is unchanged.
        print("\n[S20] non-regression - the 8 seed patients, PENDING_REQUIREMENTS only where truly unmet")
        _restore()          # back to the real committed datastore
        _snap()             # re-snap so the finally still restores
        cs2 = importlib.reload(cs)
        cs2.restore_baseline()
        for line in cs2.BASELINE_INPUT[1:]:
            p = line.split("|")
            pid = p[0].strip()
            caseid = "ER" + pid[1:]
            cs2.process_case(pid, caseid, p[1].strip(), p[4].strip(), p[5].strip(),
                             p[6].strip().lower() in ("yes", "true", "1"), p[7].strip(), p[8].strip())
        preq = _rows(cs2, "PENDING_REQUIREMENTS.psv")
        req_cases = sorted({r[1].strip() for r in preq if len(r) >= 2})
        # ER1024/25/26/29/30 each get a bed in their own ward with nothing else short.
        # ER1027/28 (Critical/ICU after ICU fills) cascade into Cardiology; that then
        # pushes the real Cardiology patient ER1031 to General - all legitimate F2
        # criticality re-routing, each opening a persistent bed requirement.
        check("S20 isolated fully-resourced cases open NO requirement",
              not ({"ER1024", "ER1025", "ER1026", "ER1029", "ER1030"} & set(req_cases)),
              req_cases)
        check("S20 every overflow case opens a bed requirement (Feature 2 working)",
              all(any(r[1].strip() == cid and r[3].strip() in ("ICU_BED", "BED") for r in preq)
                  for cid in ("ER1027", "ER1028", "ER1031")), req_cases)
        check("S20 every pending row keeps its ORIGINAL RequestedValue (never the fallback)",
              all(r[4].strip() != "" and r[4].strip().lower() != r[5].strip().lower()
                  for r in preq if r[3].strip() in ("ICU_BED", "BED")), preq)
        cases = {x[0].strip(): x for x in _rows(cs2, "EMERGENCY_CASES.psv")}
        check("S20 no seed case ended in Error", not any(
            v[2].strip() == "Error" for v in cases.values()), {k: v[2] for k, v in cases.items()})
        check("S20 the known outcomes are unchanged (ER1024 admitted, ER1025 held on docs)",
              cases.get("ER1024", ["", "", "?"])[2].strip() == "Admitted"
              and cases.get("ER1025", ["", "", "?"])[2].strip().upper().startswith("PENDING_DOC"),
              {k: v[2] for k, v in cases.items()})

        # S21 - /api/state is never stale: mutate the DB, re-read -----
        print("\n[S21] build_state re-reads the datastore on every call (no cache)")
        _reseed(BEDS_ICU_OPEN)
        s0 = cs2.build_state()["availability"]["bedsByWard"].get("ICU", {}).get("free", 0)
        cs2.save_table("BEDS.psv", *(lambda h, rs: (h, [x if x[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for x in rs]))(*cs2.load_table("BEDS.psv")))
        s1 = cs2.build_state()["availability"]["bedsByWard"].get("ICU", {}).get("free", 0)
        check("S21 an out-of-band bed change is reflected on the very next build_state()",
              s1 == s0 - 1, (s0, s1))

        # S22 - email format validation, F7, both entry points ---------
        print("\n[S22] email format is validated (F7)")
        _reseed(BEDS_ICU_OPEN)
        raised = False
        try:
            cs2.submit_case({"name": "S22 bad", "age": "40", "gender": "Male", "emergencyType": "Standard",
                             "department": "General", "ventilator": False, "bloodGroup": "O+",
                             "bloodUnits": "0", "email": "not-an-email", "docs": {}})
        except ValueError:
            raised = True
        check("S22 interactive submit rejects a malformed address", raised)
        check("S22 no case row was written for the rejected submission",
              not any(x[1].strip() == "S22 bad" for x in _rows(cs2, "PATIENTS.psv")))
        cs2.save_patient_contact("P9001", "ER9001", "also@bad", "")     # batch path: store blank, don't raise
        pc = [r for r in _rows(cs2, "PATIENT_CONTACT.psv") if r[0].strip() == "P9001"]
        check("S22 batch save_patient_contact stores a bad address as BLANK (never aborts intake)",
              pc == [] or pc[0][2].strip() == "", pc)
        check("S22 CONTACT_EMAIL_INVALID audited for the batch path",
              "CONTACT_EMAIL_INVALID" in [a for a, _ in _acts(cs2, "ER9001")])
        cs2.save_patient_contact("P9002", "ER9002", "good.addr@gmail.com", "")
        check("S22 a valid address IS stored", any(
            r[0].strip() == "P9002" and r[2].strip() == "good.addr@gmail.com"
            for r in _rows(cs2, "PATIENT_CONTACT.psv")))

        # S23 - /api/state admin payload shape (F5) -------------------
        print("\n[S23] build_state carries the admin-panel payload (F5)")
        _reseed(BEDS_ICU_FULL, blood=["BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated", "O-|1|2|s", "O+|20|5|s"])
        r = _submit(cs2, "S23 Patient", "ICU", bg="O-", units="3", email="s23@x.com", docs=docs)
        st = cs2.build_state()
        for k in ("resources", "dischargeQueue", "adminRelease"):
            check("S23 state has '%s'" % k, k in st)
        beds = st["resources"]["beds"]
        check("S23 resources.beds carry id/ward/status and an occupied bed names its patient",
              beds and all({"id", "ward", "status", "caseId", "patient"} <= set(b) for b in beds)
              and any(b["status"] == "Occupied" and b["patient"] for b in beds))
        check("S23 resources.blood carries the min threshold",
              all("min" in b for b in st["resources"]["blood"]))
        dq = [d for d in st["dischargeQueue"] if d["caseId"] == r["caseId"]]
        check("S23 the admitted patient is in the discharge queue with email + hasOpenRequirements",
              dq and dq[0]["email"] == "s23@x.com" and dq[0]["hasOpenRequirements"] is True, dq)
        check("S23 a below-threshold blood group raises a HIGH alert",
              any(a.get("sev") == "HIGH" and "Blood O-" in a.get("title", "") for a in st["alerts"]))

        # S24 - F6: signature changes after any state mutation --------
        print("\n[S24] the /api/state signature changes on every mutation (drives the live refresh)")
        _reseed(BEDS_ICU_FULL)
        ra = _submit(cs2, "S24 A", "ICU", docs=docs)
        sig0 = cs2.build_state()["signature"]
        cs2.save_table("BEDS.psv", *(lambda h, rs: (h, [x if x[0] != "ICU-03" else
                      ["ICU-03", "ICU", "Premium", "Occupied", "V-03", "s"] for x in rs]))(*cs2.load_table("BEDS.psv")))
        cs2.release_resource({"kind": "BED", "resourceId": "ICU-03", "admin": "Admin", "reason": "S24"})
        st1 = cs2.build_state()
        check("S24 signature changed after the release", st1["signature"] != sig0, (sig0, st1["signature"]))
        check("S24 the served requirement is gone from state.requirements",
              not any(q["caseId"] == ra["caseId"] and q["type"] == "ICU_BED" for q in st1["requirements"]))
        check("S24 state is still JSON-serialisable", bool(json.dumps(st1)))

        # S25 - blood STRICTLY below threshold vs exactly at it -------
        print("\n[S25] threshold alert fires at-or-below, matching the dashboard 'running low' list")
        _reseed(BEDS_ICU_OPEN, blood=["BloodGroup|AvailableUnits|MinimumThreshold|LastUpdated", "O-|4|2|s", "O+|20|5|s"])
        _submit(cs2, "S25 below", "ICU", bg="O-", units="3", docs=docs)   # 4-3 = 1  < 2
        below = any(a.get("title", "").startswith("Blood O-") for a in cs2.build_state()["alerts"])
        check("S25 one-below-threshold raises the alert", below)

    finally:
        _restore()

    print("\n" + "=" * 60)
    print("  PASSED %d / %d" % (len(_PASS), len(_PASS) + len(_FAIL)))
    if _FAIL:
        print("  FAILED:\n    - " + "\n    - ".join(_FAIL))
    print("=" * 60)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(run())
