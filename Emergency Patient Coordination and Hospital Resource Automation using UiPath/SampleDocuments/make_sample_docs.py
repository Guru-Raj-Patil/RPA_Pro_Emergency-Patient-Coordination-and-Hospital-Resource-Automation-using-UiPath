#!/usr/bin/env python3
"""
Generate dummy patient documents for the Emergency Coordination console intake form.

Produces real, openable PDFs (no third-party libraries) for the four upload slots:
    ID_Proof  |  Insurance  |  Consent_Form  |  Medical_Report

How the console uses them (for reference):
  * On submit, each file is saved as  Patients/P<id>/<SlotName>.<ext>  and a row is
    written to Data/db/DOCUMENTS.psv (Present + path).
  * The console then READS the text of each document and extracts the labelled
    "Key: Value" lines below into Data/db/PATIENT_DOCUMENT_DATA.psv, cross-checks a
    few of them against the intake form, and fills gaps (e.g. blood units) from the
    medical report when the form left them blank. Keep the "Key: Value" lines intact
    if you edit these - that is what the extractor keys on.
  * Extraction needs a text layer. These generated PDFs have one; scanned / image
    PDFs (and .png/.jpg) are still saved and presence-checked but yield no fields.
  * The 'Insurance' slot also drives a later stage: at discharge, ProcessDischarge
    builds an insurance claim packet only if Insurance is Present.

Edit PATIENTS below (or add rows) and re-run:  python make_sample_docs.py
Output: SampleDocuments/<pack>/<Slot>.pdf   plus each pack's index.txt
"""
import os
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------- tiny PDF writer
_PW, _PH = 595, 842  # A4 points
_STYLE = {  # font-index, size, gap-before
    "h1":   (2, 15, 0),
    "h2":   (2, 12, 20),
    "body": (1, 10.5, 15),
    "kv":   (1, 10.5, 14),
    "small":(1, 9, 13),
    "rule": (1, 1, 12),
    "gap":  (1, 1, 10),
}


def _esc(s):
    out = []
    for ch in str(s):
        if ch in "\\()":
            out.append("\\" + ch)
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append({"₹": "INR ", "–": "-", "—": "-",
                        "‘": "'", "’": "'", "“": '"', "”": '"'}.get(ch, "?"))
    return "".join(out)


def build_pdf(lines):
    """lines: list of (style, text). Returns PDF bytes."""
    content = ["BT", "%.1f %.1f Td" % (54, _PH - 60)]
    first = True
    for style, text in lines:
        fi, size, gap = _STYLE.get(style, _STYLE["body"])
        if not first:
            content.append("0 %.1f Td" % (-gap - size))
        first = False
        content.append("/F%d %.1f Tf" % (fi, size))
        if style == "rule":
            content.append("(%s) Tj" % ("_" * 78))
        else:
            content.append("(%s) Tj" % _esc(text))
    content.append("ET")
    stream = ("\n".join(content)).encode("latin-1", "replace")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
         "/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>" % (_PW, _PH)).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]

    buf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += ("%d 0 obj\n" % i).encode() + body + b"\nendobj\n"
    xref_at = len(buf)
    buf += ("xref\n0 %d\n" % (len(objs) + 1)).encode()
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += ("%010d 00000 n \n" % off).encode()
    buf += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
            % (len(objs) + 1, xref_at)).encode()
    return buf


# ----------------------------------------------------------------- document bodies
def medical_report(p):
    return [
        ("h1", "CITY GENERAL HOSPITAL  -  EMERGENCY DEPARTMENT"),
        ("small", "Administrative clinical summary provided to the coordination desk"),
        ("rule", ""),
        ("h2", "PATIENT"),
        ("kv", "Patient Name: %s" % p["name"]),
        ("kv", "Age: %s" % p["age"]),
        ("kv", "Gender: %s" % p["gender"]),
        ("kv", "Recorded: %s" % p["now"]),
        ("gap", ""),
        ("h2", "REFERRING TEAM SUMMARY"),
        ("kv", "Referring Physician: %s" % p["ref_doc"]),
        ("kv", "Presenting Complaint: %s" % p["complaint"]),
        ("kv", "Provisional Diagnosis: %s" % p["diagnosis"]),
        ("kv", "Emergency Category: %s" % p["etype"]),
        ("kv", "Department Requested: %s" % p["dept"]),
        ("kv", "Ventilator Support: %s" % p["vent"]),
        ("kv", "Blood Group: %s" % p["blood"]),
        ("kv", "Units Anticipated: %s" % p["units"]),
        ("kv", "Known Allergies: %s" % p["allergies"]),
        ("kv", "Investigations Advised: %s" % p["investigations"]),
        ("gap", ""),
        ("body", "Notes: %s" % p["notes"]),
        ("gap", ""),
        ("rule", ""),
        ("small", "FOR ADMINISTRATIVE COORDINATION ONLY - NOT A CLINICAL RECORD."),
        ("small", "All clinical decisions remain with the treating medical team."),
        ("gap", ""),
        ("kv", "Prepared By: %s" % p["ref_doc"]),
        ("body", "Signature: ____________________________"),
        ("small", "TEST DOCUMENT - generated by SampleDocuments/make_sample_docs.py"),
    ]


def id_proof(p):
    return [
        ("h1", "GOVERNMENT OF INDIA  -  IDENTITY CARD"),
        ("small", "SPECIMEN / TEST DOCUMENT - NOT A VALID IDENTITY PROOF"),
        ("rule", ""),
        ("kv", "Name: %s" % p["name"]),
        ("kv", "Date Of Birth: %s" % p["dob"]),
        ("kv", "Gender: %s" % p["gender"]),
        ("kv", "ID Number: %s" % p["id_no"]),
        ("kv", "Address: %s" % p["address"]),
        ("kv", "Issued: %s" % p["id_issued"]),
        ("gap", ""),
        ("small", "This document is fabricated for software testing of the Emergency"),
        ("small", "Patient Coordination console. It has no legal validity."),
    ]


def insurance(p):
    return [
        ("h1", "MEDIASSIST HEALTH INSURANCE  -  MEMBER CARD"),
        ("small", "SPECIMEN - issued for coordination-system testing only"),
        ("rule", ""),
        ("kv", "Member: %s" % p["name"]),
        ("kv", "Insurer: MediAssist Health Insurance"),
        ("kv", "Policy Number: POL-%s" % p.get("policy", p["id_no"][-6:])),
        ("kv", "Plan: Emergency & Inpatient Care - Individual"),
        ("kv", "Sum Insured: INR %s" % p["sum_insured"]),
        ("kv", "Valid Till: %s" % p["policy_valid"]),
        ("kv", "Network Hospital: City General Hospital (cashless eligible)"),
        ("kv", "Helpline: 1800-000-000 (test)"),
        ("gap", ""),
        ("small", "Presence of this document triggers an administrative insurance claim"),
        ("small", "packet at discharge (ProcessDischarge). No clinical coding is performed."),
    ]


def consent_form(p):
    return [
        ("h1", "CONSENT FOR EMERGENCY ADMISSION AND TREATMENT"),
        ("small", "SAMPLE / TEST DOCUMENT"),
        ("rule", ""),
        ("body", "I, %s, consent to emergency admission and to the administrative" % p["consenter"]),
        ("body", "processing of this case (registration, bed allocation, resource"),
        ("body", "reservation, billing and discharge coordination) at City General Hospital."),
        ("gap", ""),
        ("kv", "Patient: %s" % p["name"]),
        ("kv", "Consent Given By: %s" % p["consenter"]),
        ("kv", "Relationship: %s" % p["relationship"]),
        ("kv", "Date: %s" % p["now"]),
        ("body", "Signature: ____________________________"),
        ("kv", "Witness: %s" % p["witness"]),
        ("gap", ""),
        ("small", "Clinical consent for specific procedures is taken separately by the"),
        ("small", "treating team and is not covered by this administrative form."),
    ]


SLOTS = {
    "Medical_Report": medical_report,
    "ID_Proof": id_proof,
    "Insurance": insurance,
    "Consent_Form": consent_form,
}

# ----------------------------------------------------------------- sample patients
_NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
PATIENTS = [
    dict(pack="patient_A_rahul", name="Rahul Kumar", age="54", gender="Male",
         dob="1971-04-12", etype="Critical", dept="ICU", vent="Required", blood="O-", units="4",
         complaint="Acute chest pain, breathlessness since 2 hours",
         diagnosis="Suspected acute coronary syndrome (to be confirmed by cardiology)",
         ref_doc="Dr. A. Sharma, Consultant Physician",
         allergies="None reported", investigations="ECG, Troponin, CBC, cross-match O-",
         notes="Brought by family. Vitals recorded on arrival chart.",
         id_no="TEST-1122-3344-5566", policy="778812", address="14 MG Road, Bengaluru 560001",
         id_issued="2016-08-01", sum_insured="500000", policy_valid="2027-03-31",
         consenter="Sunita Kumar", relationship="spouse", witness="ED Nurse (on duty)"),
    dict(pack="patient_B_ananya", name="Ananya Singh", age="32", gender="Female",
         dob="1993-11-05", etype="Urgent", dept="ICU", vent="Not required", blood="A+", units="2",
         complaint="High-grade fever with altered sensorium",
         diagnosis="Sepsis - source evaluation in progress",
         ref_doc="Dr. R. Nair, Emergency Medicine",
         allergies="Penicillin", investigations="Blood culture, CBC, lactate, CXR",
         notes="Referred from a peripheral clinic. Clinic notes attached separately.",
         id_no="TEST-7788-9900-1122", policy="443019", address="221 Park Street, Kolkata 700016",
         id_issued="2018-02-20", sum_insured="300000", policy_valid="2026-12-31",
         consenter="Ananya Singh", relationship="self", witness="Registration Desk"),
    dict(pack="patient_C_minor", name="Meera R", age="16", gender="Female",
         dob="2009-06-22", etype="Critical", dept="ICU", vent="Required", blood="O-", units="3",
         complaint="Road traffic injury, reduced consciousness",
         diagnosis="Polytrauma - neurosurgical and orthopaedic review requested",
         ref_doc="Dr. S. Kamath, Trauma & Emergency Surgery",
         allergies="Unknown", investigations="CT head/cervical, FAST, cross-match O-, coagulation",
         notes="Minor - guardian consent required. Guardian present at ED.",
         id_no="TEST-3344-5566-7788", policy="662255", address="7 Lake View, Pune 411001",
         id_issued="2022-09-15", sum_insured="400000", policy_valid="2028-01-31",
         consenter="Rekha R", relationship="mother / guardian", witness="ED Social Worker"),
]


def main():
    made = 0
    for base in PATIENTS:
        p = dict(base, now=_NOW)
        outdir = os.path.join(HERE, p["pack"])
        os.makedirs(outdir, exist_ok=True)
        for slot, builder in SLOTS.items():
            path = os.path.join(outdir, slot + ".pdf")
            with open(path, "wb") as f:
                f.write(build_pdf(builder(p)))
            made += 1
        with open(os.path.join(outdir, "index.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join([
                "Sample intake documents for: %s (%s, %s, %s)" % (p["name"], p["age"], p["gender"], p["etype"]),
                "",
                "Upload on the console 'Patient Intake' tab, one file per slot:",
                "  ID proof       -> ID_Proof.pdf",
                "  Insurance      -> Insurance.pdf",
                "  Consent form   -> Consent_Form.pdf",
                "  Medical report -> Medical_Report.pdf",
                "",
                "Match the form fields to this patient:",
                "  Name=%s  Age=%s  Gender=%s" % (p["name"], p["age"], p["gender"]),
                "  Emergency type=%s  Department=%s" % (p["etype"], p["dept"]),
                "  Blood group=%s  Units=%s  Ventilator=%s" % (p["blood"], p["units"], p["vent"]),
                "",
                "Scenario ideas:",
                "  * Upload all 4  -> documents Complete (25% readiness) -> can admit.",
                "  * Skip Medical_Report -> PENDING_DOCUMENTATION hold (like test T2).",
                "  * Skip Insurance -> admitted fine, but NO insurance claim packet at discharge.",
                "  * Leave 'Blood units required' as 0 on the form -> the bot reads",
                "    'Units Anticipated' from the medical report and uses it.",
                "  * Change 'Blood Group' in Medical_Report.pdf to a different group than",
                "    the form -> the bot raises a document-mismatch warning (does not block).",
                "",
                "The console reads the 'Key: Value' lines from each PDF into",
                "Data/db/PATIENT_DOCUMENT_DATA.psv, cross-checks blood group / department /",
                "emergency category / name against the form, and fills blank form fields",
                "(e.g. blood units) from the medical report.",
            ]) + "\n")
    print("Wrote %d PDFs across %d packs under %s" % (made, len(PATIENTS), HERE))
    for base in PATIENTS:
        print("  %s/  (%s)" % (base["pack"], base["name"]))


if __name__ == "__main__":
    main()
