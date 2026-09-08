You are a senior UiPath RPA architect and developer. I need you to help me design and implement a complete, working UiPath Studio project from scratch.

The final project must be implemented as a genuine UiPath RPA solution. Do not replace UiPath with Python, Java, Node.js, Selenium, or another automation framework. External scripts are allowed only when they support the UiPath workflow and have a clear reason.

PROJECT TITLE

Emergency Patient Coordination and Hospital Resource Automation using UiPath

PROJECT OBJECTIVE

Build an RPA system for a single multi-specialty hospital ("City General Hospital") that automates the repetitive administrative coordination of an emergency patient's entire episode of care - from the moment an emergency request is received, through admission, to discharge and post-discharge follow-up.

The system should collect the emergency request, verify required documents, check hospital resources (bed / ventilator / blood), assign the care team (on-call consultant, and a surgeon + anaesthetist + operating-theatre slot when the case is surgical), calculate an administrative readiness status, obtain staff approval, reserve resources, confirm admission, accrue charges during the stay, obtain the attending doctor's discharge certification, then process the discharge (final bill, insurance claim packet, discharge summary, resource release, follow-up scheduling) - updating hospital records, notifying authorized staff, and logging an audit trail at every step.

The system must NOT make medical diagnoses, recommend treatment, replace doctors, or make clinical decisions. The bot performs administrative coordination only and follows predefined business rules. Two decisions stay with humans: (1) approval to admit / reserve resources, and (2) certification that the patient is clinically fit for discharge. Everything between and after those two gates is automated.

CORE PROBLEM

During emergency admissions, hospital staff need to coordinate several pieces of information:

1. Patient information
2. Required documents
3. Bed availability
4. Ventilator availability
5. Blood availability
6. Resource reservation
7. Database updates
8. Staff notifications

Each individual task is simple and might already be performed quickly by hospital staff.

The problem addressed by this project is repetitive administrative coordination and cross-checking.

For example, for every emergency case, staff repeatedly:

* Open patient records
* Check documents
* Check ICU/ward beds
* Check ventilator availability
* Check blood inventory
* Look up the on-call consultant for the required department; for surgical cases also find a free surgeon, an anaesthetist and an operating-theatre slot
* Identify missing requirements
* Update records across bed management, the duty roster, billing and the case file
* Notify staff
* During the stay: post daily bed charges, procedure and consultation fees
* At discharge: total the bill, assemble the insurance claim, write the discharge summary, free the bed and ventilator, release the doctors, and schedule the follow-up

The RPA bot performs this repetitive coordination consistently, across the whole episode, and keeps one consolidated case record with a full audit trail.

IMPORTANT DESIGN PRINCIPLE

Do not claim that the bot replaces hospital staff.

The bot acts as an administrative coordination assistant.

Human staff remain responsible for medical decisions and final approval where required.

PROJECT SCOPE

Keep the project focused.

The system should handle:

1. Emergency patient intake (the trigger - human-originated, RPA-assisted)
2. Patient document verification
3. Bed availability checking
4. Ventilator availability checking
5. Blood inventory checking
6. Care-team assignment - on-call consultant by department + load; surgeon, anaesthetist and operating-theatre slot for surgical cases
7. Emergency readiness calculation
8. Human approval to admit / reserve (HUMAN GATE 1)
9. Resource reservation (bed, ventilator, blood, doctor, OT slot) with rollback
10. Admission confirmation and opening of the billing account
11. Charge accrual during the stay (scheduled / unattended)
12. Discharge certification by the attending doctor (HUMAN GATE 2)
13. Discharge processing - final bill, insurance claim packet, discharge summary, resource release, follow-up scheduling
14. Post-discharge follow-up reminder, then case closure
15. Database update, staff notification, human-in-the-loop exception handling
16. Logging and audit trail across the whole episode

Do NOT add features outside administrative coordination, such as:

* Ambulance GPS tracking
* Disease prediction / AI diagnosis / clinical decision support
* Patient vital-sign monitoring
* Facial recognition
* Hospital-wide ERP or full HIS replacement
* Complex machine learning
* Online payment gateways / card processing (the bot totals and records charges; it does not take payment)
* Pharmacy stock management
* Outpatient appointment booking (only the single post-discharge follow-up date is set, by rule)

The objective is a strong end-to-end RPA project scoped to administrative coordination - not an oversized healthcare platform and not a clinical system.

SYSTEM ARCHITECTURE

Design the system around this architecture:

Emergency Request
↓
Patient Intake  (human-originated trigger; console form / Excel / queue)
↓
Create Emergency Case
↓
Document Verification
↓
Bed Availability Check
↓
Ventilator Availability Check
↓
Blood Availability Check
↓
Care-Team Assignment  (consultant; + surgeon / anaesthetist / OT slot if surgical)
↓
Emergency Readiness Calculation
↓
Generate Consolidated Status
↓
Human Approval to Admit / Reserve      <-- HUMAN GATE 1
↓
Reserve Resources  (bed + ventilator + blood + doctor + OT slot, with rollback)
↓
Confirm Admission  (open billing account, post day-1 charges)
↓
Accrue Charges During Stay  (scheduled / unattended)
↓
Discharge Certification by Attending Doctor   <-- HUMAN GATE 2
↓
Process Discharge  (final bill -> insurance claim packet -> discharge summary ->
                    release bed / ventilator / doctors -> set follow-up date)
↓
Post-Discharge Follow-Up  ->  Close Case
↓
Update Database / Notify Hospital Staff / Log Transaction  (at every step)
↓
Orchestrator Monitoring

TECHNOLOGY STACK

Primary platform:

UiPath Studio

Use appropriate UiPath components where suitable:

* UiPath Studio
* UiPath Orchestrator
* UiPath Queues
* UiPath Action Center
* UiPath Document Understanding
* OCR
* UiPath Database Activities
* Excel Activities
* Mail/Outlook activities
* Try Catch
* Retry Scope where appropriate
* Logging
* Config files

DATABASE

Use a relational database for the main hospital data.

For the prototype, SQLite or SQL Server is acceptable.

Prefer SQLite if it makes local development easier and does not reduce the UiPath demonstration value.

Design the database with separate tables.

Suggested tables:

PATIENTS

PatientId
Name
Age
Gender
EmergencyType
RequiredDepartment
RequiredVentilator
RequiredBloodGroup
RequiredBloodUnits
CreatedAt

DOCUMENTS

DocumentId
PatientId
DocumentType
FilePath
VerificationStatus
VerifiedAt

BEDS

BedId
Department
BedType
Status
VentilatorId
LastUpdated

VENTILATORS

VentilatorId
Status
Location
LastUpdated

BLOOD_INVENTORY

BloodGroup
AvailableUnits
MinimumThreshold
LastUpdated

EMERGENCY_CASES

CaseId
PatientId
CaseStatus
DocumentStatus
BedStatus
VentilatorStatus
BloodStatus
ReadinessPercentage
PendingAction
CreatedAt
UpdatedAt

RESOURCE_RESERVATIONS

ReservationId
CaseId
ResourceType
ResourceId
Status
ReservedAt

AUDIT_LOG

LogId
CaseId
Action
Description
Timestamp
PerformedBy

--- Episode-extension tables (Phase 2) ---

DEPARTMENTS
DepartmentId | Name | Type (Medical / Surgical / Critical / Surgical Support) | FloorWard | HeadDoctorId | LastUpdated

DOCTORS
DoctorId | Name | DepartmentId | Designation | Specialty | IsSurgeon (0/1) | OnCallStatus (OnCall / OffDuty / InTheatre / OnLeave) | ShiftStart | ShiftEnd | CurrentLoad | MaxLoad | Contact | Email | LastUpdated

OPERATING_THEATRES
TheatreId | Name | DepartmentAffinity | Status (Available / InUse / Cleaning / Maintenance) | LastUpdated

DOCTOR_ASSIGNMENTS
AssignmentId | CaseId | DoctorId | Role (Attending / Surgeon / Anaesthetist / Consulting) | Specialty | AssignedAt | Status (Assigned / HandedOver / Released)

OT_SCHEDULE
SlotId | TheatreId | CaseId | SurgeonId | AnaesthetistId | ScheduledStart | ScheduledEnd | Status (Booked / InProgress / Done / Cancelled)

ADMISSIONS
AdmissionId | CaseId | PatientId | BedId | AttendingDoctorId | AdmittedAt | ExpectedStayDays | Status (Admitted / InTreatment / FitForDischarge / Discharged) | DischargeReadyAt

BILLING
ChargeId | CaseId | Category (Registration / BedDay / DoctorFee / Procedure / OT / Investigation / Blood / Consumable) | Description | Quantity | UnitPrice | Amount | PostedAt

DISCHARGES
DischargeId | CaseId | PatientId | ClinicalClearanceBy (DoctorId) | ClinicalClearanceAt | FinalBillAmount | PaymentStatus (Settled / InsurancePending / Waived) | FollowUpDate | DischargeSummaryPath | DischargedAt

INSURANCE_CLAIMS
ClaimId | CaseId | Insurer | PolicyNumber | ClaimAmount | PacketPath | Status (Draft / Submitted / Approved / Rejected) | SubmittedAt

EMERGENCY_CASES gains: AssignedDoctorId, AdmissionId, DischargeId, and an extended CaseStatus lifecycle:
  PENDING_* -> READY_FOR_APPROVAL -> APPROVED -> ADMITTED -> IN_TREATMENT -> FIT_FOR_DISCHARGE -> DISCHARGED -> CLOSED
  (plus REJECTED / ERROR)

Reference tables (DEPARTMENTS, DOCTORS, OPERATING_THEATRES) are seeded from HospitalDB.db and Workflows/ResetDatastore.xaml. The rest are ledgers the bot writes during the run.

You may modify this schema if a better normalized design is appropriate.

Before implementing the database, explain the final schema and relationships.

SAMPLE HOSPITAL DATA

Create realistic test data.

Example beds:

ICU-01 | ICU | Occupied
ICU-02 | ICU | Occupied
ICU-03 | ICU | Available
ICU-04 | ICU | Available

Example ventilators:

V-01 | Available
V-02 | Occupied
V-03 | Available

Example blood:

A+ | 15
A- | 5
B+ | 12
B- | 4
AB+ | 8
AB- | 2
O+ | 20
O- | 6

Create enough test cases to demonstrate both successful and failed scenarios.

EMERGENCY INPUT

The system should receive:

Patient ID
Patient name
Age
Gender
Emergency type
Required department
Ventilator required
Blood group
Blood units

Example:

Patient ID: P1024
Name: Rahul Kumar
Age: 54
Gender: Male
Emergency Type: Critical
Required Department: ICU
Ventilator Required: Yes
Blood Group: O-
Blood Units: 4

The input method should initially be simple and reliable.

Use an Excel input file or UiPath form if this makes implementation easier.

Do not introduce UiPath Apps unless it adds clear value.

DOCUMENT VERIFICATION

Each patient should have a folder containing supporting documents.

Example:

Patients/
P1024/
ID_Proof.pdf
Insurance.pdf
Consent_Form.pdf
Medical_Report.pdf

Define required documents based on the emergency case.

For example:

Required:

ID Proof
Insurance
Consent Form
Medical Report

The bot should:

1. Read the patient folder
2. Identify available files
3. Classify documents
4. Verify required document presence
5. Record document status
6. Identify missing documents
7. Update the database

Use Document Understanding/OCR where appropriate.

Do not overcomplicate document extraction if simple document presence/classification is sufficient for the prototype.

The goal is to demonstrate meaningful document automation.

Example:

ID Proof: Present
Insurance: Present
Consent Form: Present
Medical Report: Missing

Result:

Document Status = INCOMPLETE

BED CHECKING

The bot should query the BEDS table.

Rules:

* Department must match required department.
* Bed status must be Available.
* If ventilator is required, the assigned ventilator must be Available.
* Do not reserve an occupied bed.
* Do not reserve a bed twice.

Example:

Patient requires:

ICU
Ventilator

Database:

ICU-01 = Occupied
ICU-02 = Occupied
ICU-03 = Available
ICU-03 ventilator = Available

Result:

Suitable bed = ICU-03

VENTILATOR CHECK

If the patient requires a ventilator:

Check whether the selected bed has an available ventilator.

If not:

Ventilator Status = UNAVAILABLE

Do not assign an unsuitable resource.

If a ventilator is not required:

Ventilator Status = NOT REQUIRED

BLOOD CHECKING

Check:

Required blood group
Required quantity
Available inventory
Minimum threshold

Example:

Required:
O-
4 units

Available:
6 units

Result:

Blood Available = YES

After reservation:

Remaining:
2 units

If requested quantity exceeds available quantity:

Blood Status = UNAVAILABLE

If available quantity is below the configured minimum threshold after reservation, flag the inventory as critical and notify authorized staff.

Do not make medical judgments about blood compatibility. The system uses the blood group supplied by authorized hospital staff.

EMERGENCY READINESS SCORE

Create a simple transparent scoring mechanism.

Do not use machine learning.

Suggested scoring:

Documents complete = 25%
Suitable bed available = 25%
Ventilator available/not required = 25%
Required blood available = 25%

Example:

Documents = Complete → 25
Bed = Available → 25
Ventilator = Available → 25
Blood = Available → 25

Readiness = 100%

Another example:

Documents = Missing → 0
Bed = Available → 25
Ventilator = Available → 25
Blood = Available → 25

Readiness = 75%

The score is an administrative readiness indicator.

It must NOT be described as a medical risk score.

FINAL STATUS

Generate a consolidated status.

Example:

Emergency Case: ER1024

Patient: Rahul Kumar

Department:
ICU

Bed:
ICU-03 AVAILABLE

Ventilator:
AVAILABLE

Blood:
O- AVAILABLE, 4 units

Documents:
3/4 COMPLETE

Readiness:
75%

Pending:
Medical Report

Status:
PENDING DOCUMENTATION

Another example:

Emergency Case: ER1025

Bed:
AVAILABLE

Ventilator:
AVAILABLE

Blood:
AVAILABLE

Documents:
COMPLETE

Readiness:
100%

Status:
READY FOR STAFF APPROVAL

HUMAN-IN-THE-LOOP

Do not allow the bot to independently make final clinical decisions.

Use UiPath Action Center where appropriate.

Suggested process:

Bot performs checks
↓
Bot generates status
↓
Authorized staff reviews
↓
Approve / Reject / Request Correction
↓
Bot performs approved administrative action

Human approval is especially useful before final resource reservation.

If Action Center setup is difficult in the local development environment, create the workflow so that the human approval stage is clearly represented and explain how it would be deployed through Orchestrator.

RESOURCE RESERVATION

After authorized approval:

1. Reserve suitable bed
2. Reserve ventilator if required
3. Reserve required blood units
4. Update resource status
5. Create reservation records
6. Write audit log

Use transactions carefully.

Avoid situations where:

Bed is reserved
but
Blood reservation fails

The workflow should detect partial failures.

Design an appropriate rollback or compensation mechanism.

For example:

If blood reservation fails after bed reservation:

Release the bed reservation
Record the failure
Create human-review task
Notify staff

EXCEPTION HANDLING

Create meaningful business exceptions.

Examples:

BUSINESS EXCEPTIONS

* Patient not found
* Required document missing
* No suitable bed
* No ventilator available
* Insufficient blood inventory
* Invalid patient input
* Duplicate emergency case

SYSTEM EXCEPTIONS

* Database unavailable
* File unavailable
* OCR failure
* Email failure
* Application timeout

Use Try Catch appropriately.

Do not surround the entire project with one giant Try Catch.

Handle exceptions at meaningful workflow boundaries.

RETRY LOGIC

Use retries only for temporary system failures.

For example:

Database timeout
Email service timeout
Temporary application failure

Do not retry business exceptions such as:

"No ICU bed available."

That is not a technical failure.

QUEUE DESIGN

Use UiPath Orchestrator Queue for emergency cases if appropriate.

Queue item fields could include:

CaseId
PatientId
EmergencyType
RequiredDepartment
VentilatorRequired
BloodGroup
BloodUnits

Each queue transaction should represent one emergency case.

Process:

New Emergency Case
↓
Add Queue Item
↓
Get Transaction Item
↓
Process Case
↓
Success / Business Exception / System Exception
↓
Log Result

Do not add unnecessary queue complexity if it does not improve the workflow.

CONFIGURATION

Create a Config.xlsx or configuration file.

Store values such as:

Database connection
Patient document root folder
Hospital name
Required document types
Blood minimum thresholds
Email addresses
Retry count
Timeout values

Do not hard-code paths throughout the workflow.

Use configuration variables.

WORKFLOW STRUCTURE

Create modular XAML workflows.

Suggested structure:

Main.xaml

Framework/Init.xaml
Framework/GetConfig.xaml

Workflows/ReceiveEmergencyCase.xaml
Workflows/VerifyDocuments.xaml
Workflows/CheckBedAvailability.xaml
Workflows/CheckVentilator.xaml
Workflows/CheckBloodInventory.xaml
Workflows/AssignCareTeam.xaml          (Phase 2 - consultant + surgeon / anaesthetist / OT)
Workflows/ScheduleTheatre.xaml         (Phase 2 - surgical branch)
Workflows/CalculateReadiness.xaml
Workflows/GenerateCaseStatus.xaml
Workflows/RequestHumanApproval.xaml    (HUMAN GATE 1 - approve admission / reservation)
Workflows/ReserveResources.xaml
Workflows/ConfirmAdmission.xaml        (Phase 2 - admission + open billing account)
Workflows/AccrueCharges.xaml          (Phase 2 - scheduled charge accrual during stay)
Workflows/CertifyDischarge.xaml       (Phase 2 - HUMAN GATE 2 - attending-doctor fitness sign-off)
Workflows/ProcessDischarge.xaml       (Phase 2 - final bill, claim, summary, release, follow-up)
Workflows/PostDischargeFollowUp.xaml  (Phase 2 - reminder + case closure)
Workflows/SubmitInsuranceClaim.xaml   (Phase 2 - optional: insurer-portal keying demo)
Workflows/UpdateDatabase.xaml
Workflows/SendNotification.xaml
Workflows/HandleException.xaml
Workflows/WriteAuditLog.xaml
Workflows/GenerateDashboard.xaml
Workflows/ResetDatastore.xaml
Workflows/CapturePatientContact.xaml   (Phase 3 - store the patient's EmailAddress at registration)
Workflows/RegisterRequirement.xaml    (Phase 3 - open a persistent PENDING_REQUIREMENTS row, FCFS timestamp)
Workflows/ReleaseResource.xaml        (Phase 3 - admin manual release of a bed / ventilator / doctor / blood unit)
Workflows/FulfilPendingRequirements.xaml (Phase 3 - earliest-valid-request-first allocation of a freed resource)
Workflows/ApproveDischarge.xaml       (Phase 3 - administrative discharge sign-off gate)
Workflows/EmailFinalBill.xaml         (Phase 3 - build the final bill from existing charges + email it, simulated)

Use Invoke Workflow File and arguments to keep workflows modular.

VARIABLES AND ARGUMENTS

Define variables and arguments clearly.

Prefer strongly typed variables.

Examples:

in_PatientId
in_CaseId
in_RequiredDepartment
in_VentilatorRequired
in_BloodGroup
in_BloodUnits

out_DocumentStatus
out_BedStatus
out_VentilatorStatus
out_BloodStatus
out_ReadinessScore
out_FinalStatus

Use DataTables or appropriate custom objects where they improve readability.

Avoid excessive global variables.

LOGGING

Use UiPath logging.

Log:

Case received
Patient identified
Documents checked
Missing documents
Bed search started
Suitable bed found
Ventilator checked
Blood checked
Readiness calculated
Approval requested
Reservation completed
Notification sent
Exception occurred

Do not log sensitive patient information unnecessarily.

Use CaseId or PatientId where possible.

EMAIL NOTIFICATION

Create a professional notification template.

Example:

Emergency Case: ER1024

Patient: Rahul Kumar

Department: ICU

Bed: ICU-03
Ventilator: Available
Blood: O-, 4 units available
Documents: 3/4 complete

Readiness: 75%

Pending Action:
Medical Report verification

Status:
Human review required

Do not send real medical information outside the simulated environment.

AUDIT TRAIL

Every important action should be recorded.

Example:

ER1024
08:30
Emergency case created

08:31
Documents checked

08:31
Medical report missing

08:32
ICU-03 identified

08:32
Ventilator V-03 available

08:33
O- blood availability confirmed

08:34
Human approval requested

08:36
Resources reserved

This should demonstrate traceability.

TEST SCENARIOS

Create at least these test cases.

TEST 1: Successful case

ICU available
Ventilator available
Blood available
All documents present

Expected:

Readiness = 100%
Status = Ready for approval

TEST 2: Missing document

Resources available
One document missing

Expected:

Readiness = 75%
Human review required

TEST 3: No ICU bed

Documents complete
No ICU bed

Expected:

Bed status = Unavailable
No reservation
Human escalation

TEST 4: No ventilator

ICU available
Ventilator required
No ventilator available

Expected:

Ventilator status = Unavailable
No reservation

TEST 5: Insufficient blood

ICU available
Ventilator available
Required blood quantity exceeds inventory

Expected:

Blood status = Unavailable
No reservation
Escalation

TEST 6: Multiple simultaneous cases

Create 5 to 10 emergency cases.

Process them through the queue.

Verify that each case gets an independent result.

TEST 7: Database failure

Temporarily make the database unavailable.

Expected:

System exception
Retry
Log failure
Do not corrupt existing reservations

TEST 8: Duplicate case

Submit the same CaseId twice.

Expected:

Duplicate detected
No duplicate reservation

TEST 9: Care-team assignment (medical case)

Required department has an on-call consultant with spare capacity.

Expected:

Attending doctor assigned, DOCTOR_ASSIGNMENTS row created, doctor CurrentLoad incremented.

TEST 10: Surgical case needs a theatre

Emergency type is surgical (e.g. Neurosurgery / Trauma).

Expected:

Surgeon + anaesthetist assigned, an Available OT booked in OT_SCHEDULE - all part of the same reservation transaction (rollback releases the OT slot too).

TEST 11: No on-call consultant

Every doctor in the required department is OffDuty / OnLeave / at MaxLoad.

Expected:

Business exception "No on-call <specialty> consultant available", no reservation, human escalation.

TEST 12: Admission and charge accrual

Approved 100% case is admitted.

Expected:

ADMISSIONS row (Status Admitted), bed flips Reserved -> Occupied, BILLING has registration + day-1 bed charge; a second AccrueCharges run adds another bed day.

TEST 13: Discharge processing

Attending doctor certifies fitness for discharge.

Expected:

Final bill totalled, discharge summary file produced, INSURANCE_CLAIMS packet drafted if insured, bed + ventilator released to Available, DOCTOR_ASSIGNMENTS Released and doctor load decremented, FollowUpDate set, CaseStatus DISCHARGED.

TEST 14: Discharge without certification

No clinical clearance recorded.

Expected:

ProcessDischarge does not run; case stays IN_TREATMENT; no resource release.

DEMO SCENARIO

The final demonstration should follow this story:

1. Submit emergency patient case.
2. Bot creates Case ID.
3. Bot reads patient information.
4. Bot checks documents.
5. Bot identifies missing or complete documents.
6. Bot checks ICU/ward bed.
7. Bot checks ventilator.
8. Bot checks blood inventory.
9. Bot assigns the care team - on-call consultant, and surgeon + anaesthetist + OT slot if surgical.
10. Bot calculates readiness.
11. Bot displays consolidated status.
12. Human approval to admit occurs (HUMAN GATE 1).
13. Bot reserves resources (bed, ventilator, blood, doctor, OT slot) with rollback on partial failure.
14. Bot confirms admission and opens the billing account (day-1 charges posted).
15. Bot accrues charges over the stay (scheduled run).
16. Attending doctor certifies the patient fit for discharge (HUMAN GATE 2).
17. Bot processes discharge - totals the bill, drafts the insurance claim, writes the discharge summary, releases the bed / ventilator / doctors, sets the follow-up date.
18. Bot sends the post-discharge follow-up reminder and closes the case.
19. Database updates and staff notifications happen at every step.
20. Audit log records the complete episode end to end.

IMPORTANT RPA PRINCIPLE

The project must demonstrate that RPA adds value even though humans already perform these tasks efficiently.

The justification is:

"The project does not replace existing hospital systems or hospital staff. It automates repetitive administrative coordination across those systems. Its value increases during repeated high-volume emergency workflows by providing consistent checks, automatic updates, structured exception handling, notifications, and auditability."

IMPLEMENTATION RULES

1. Do not build everything in one XAML file.
2. Use modular workflows.
3. Use meaningful workflow and variable names.
4. Avoid hard-coded values.
5. Use configuration.
6. Use proper exception handling.
7. Separate business exceptions from system exceptions.
8. Keep medical decisions outside the automation.
9. Keep the database consistent.
10. Add logs for important actions.
11. Make the project easy to demonstrate.
12. Prefer simple reliable implementation over unnecessary complexity.
13. Do not introduce AI unless it has a clear purpose.
14. Do not fabricate UiPath activities or APIs.
15. Verify UiPath package/activity compatibility before using an activity.
16. If an implementation depends on a UiPath feature unavailable in the local environment, provide a practical alternative.

HOW I WANT YOU TO WORK

Do not attempt to blindly generate the entire project in one step.

Work in phases.

PHASE 1:
Analyze requirements and produce:

* Final architecture
* Database schema
* Folder structure
* Workflow structure
* Variables
* Arguments
* Business rules
* Exception strategy
* Test cases

Then wait for confirmation.

PHASE 2:
Create the database and sample data.

Verify the schema and sample queries.

PHASE 3:
Create the UiPath project structure and configuration.

PHASE 4:
Implement patient intake.

PHASE 5:
Implement document verification.

PHASE 6:
Implement bed and ventilator checking.

PHASE 7:
Implement blood inventory checking.

PHASE 8:
Implement readiness calculation.

PHASE 9:
Implement human approval.

PHASE 10:
Implement resource reservation and database updates.

PHASE 11:
Implement notifications and audit logging.

PHASE 12:
Implement queue/orchestrator-related components.

PHASE 13:
Run all test scenarios.

PHASE 14:
Fix errors and improve reliability.

PHASE 15:
Prepare the final demo workflow and documentation.

--- PHASE 2: EPISODE EXTENSION (admission -> discharge) ---

E1. Add care-team data model: DEPARTMENTS, DOCTORS, OPERATING_THEATRES + seed data; ledger tables
    DOCTOR_ASSIGNMENTS, OT_SCHEDULE, ADMISSIONS, BILLING, DISCHARGES, INSURANCE_CLAIMS. Wire into
    HospitalDB.db, console_server.py and ResetDatastore.xaml.   [DONE]
E2. AssignCareTeam.xaml - consultant selection by department + on-call + load; surgeon + anaesthetist
    for surgical cases. Wire into Main.xaml after the resource checks.   [DONE]
E3. ScheduleTheatre.xaml (books an Available OT for surgical depts, writes OT_SCHEDULE) + extend
    ReserveResources.xaml rollback to release the OT slot AND the care-team assignments (doctor
    load decremented). Wired into Main.xaml reservation block; BE-008 if a surgical case has no OT.   [DONE]
E4. ConfirmAdmission.xaml - ADMISSIONS row (Status Admitted, ExpectedStayDays by emergency type),
    bed (and ventilator if reserved) Reserved -> Occupied, opens BILLING account with a Registration
    charge (500) + day-1 BedDay charge (Premium 8000 / Standard 4000). Runs in Main.xaml only when the
    reservation succeeded.   [DONE]
E5. AccrueCharges.xaml - standalone / scheduled Run File (not called by Main). Each run advances every
    ADMISSIONS row with Status=Admitted by one billing day: appends a BedDay charge (Premium 8000 /
    Standard 4000) + a DoctorFee "attending review" charge (1500), writes a CHARGES_ACCRUED audit row.
    Stops a case once its billed bed-days reach ExpectedStayDays (escalate for review beyond that).
    Demonstrates the unattended / schedule-triggered leg of the automation.   [DONE]
E6. CertifyDischarge.xaml - HUMAN GATE 2. Standalone Run File. Scans ADMISSIONS Status=Admitted; per case
    raises a DISCHARGE_CLEARANCE_<case>.txt request addressed to the attending doctor and then records the
    doctor's decision - Certified if a CERTIFY_<case>.txt file is present (real human path) OR Config
    AutoCertifyDischarge=True (demo path, mirrors AutoApproveWhenReady); otherwise Held. On certify: writes
    a DISCHARGES draft row (ClinicalClearanceBy=attending), sets ADMISSIONS.Status=FitForDischarge +
    DischargeReadyAt, writes a CLINICAL_CLEARANCE_<case>.txt certificate, audits DISCHARGE_CERTIFIED
    (PerformedBy the doctor). The bot never assesses clinical fitness itself.   [DONE]
E7. ProcessDischarge.xaml - standalone Run File. Consumes DISCHARGES rows that are certified
    (ClinicalClearanceBy set) but not yet processed (DischargedAt empty). Per case, all automated,
    per-case Try/Catch so one bad case does not abort the batch: totals BILLING -> FinalBillAmount;
    if the patient's Insurance doc is Present, appends an INSURANCE_CLAIMS row (Status Submitted) and
    writes a CLAIM_<case>.txt packet; writes a DISCHARGE_SUMMARY_<case>.txt (hospital, patient, dept,
    attending, LOS, resources, bill, payment status, follow-up + "administrative, not a clinical note"
    disclaimer); frees the bed (Occupied -> Available) and ventilator; releases DOCTOR_ASSIGNMENTS
    (Status Released, DOCTORS load--); closes the OT (theatre -> Available, OT_SCHEDULE -> Done) if any;
    marks RESOURCE_RESERVATIONS rows Released; sets FollowUpDate (+7d); fills the DISCHARGES row
    (FinalBillAmount, PaymentStatus, FollowUpDate, DischargeSummaryPath, DischargedAt); sets
    ADMISSIONS.Status = Discharged; audits DISCHARGE_COMPLETED.   [DONE]
E8. PostDischargeFollowUp.xaml - standalone / scheduled Run File. For each DISCHARGES row with
    DischargedAt set whose FollowUpDate has arrived (or in_ForceDueNow / Config FollowUpDemoMode=True)
    and whose ADMISSIONS.Status is not yet Closed: writes a FOLLOWUP_<case>.txt reminder (patient +
    referring physician), writes a CLOSED_<case>.txt episode-closure note, sets ADMISSIONS.Status =
    Closed, audits FOLLOWUP_SENT then EPISODE_CLOSED. Per-episode Try/Catch. Config += FollowUpDemoMode.
    This is the end of the automated episode.   [DONE]
E9. EMERGENCY_CASES lifecycle. No schema-width change - CaseStatus (free-text) is advanced through
    the episode by a small helper Workflows/SetCaseStatus.xaml (reads the row, rewrites CaseStatus +
    PendingAction + UpdatedAt, non-fatal). Main.xaml still ends reserved cases at "Approved"; then
    AccrueCharges -> IN_TREATMENT, CertifyDischarge -> FIT_FOR_DISCHARGE, ProcessDischarge -> DISCHARGED,
    PostDischargeFollowUp -> CLOSED (ADMISSIONS.Status carries the parallel Admitted/FitForDischarge/
    Discharged/Closed detail). Dashboard bucket() folds the new statuses into the green "Approved"
    outcome so KPIs do not regress. RunAcceptanceTests T1/T6 accept "Approved or any later stage".   [DONE]
E10. Dashboard (dashboard_template.html + index.html + GenerateDashboard.xaml + console_server.py):
     pipeline stepper rebuilt to the full 15-step episode with the two HUMAN gates highlighted amber
     and every bot step teal; new Ops sections "Care team & operating theatres" (on-call roster with
     load bars, theatre status, care-team-assigned table) and "Admissions, billing & discharge"
     (episode KPIs, episode-stage donut, billing-by-category bars, admissions/discharges table).
     9 new injected data blocks (DEPARTMENTS/DOCTORS/OPERATING_THEATRES/DOCTOR_ASSIGNMENTS/OT_SCHEDULE/
     ADMISSIONS/BILLING/DISCHARGES/INSURANCE_CLAIMS) wired through GenerateDashboard.xaml and the live
     console. This is the professor "100% automation" showcase.   [DONE - TEST 9-14 optional surgical case still to add]

--- PHASE 3: FINE-TUNE EXTENSION (real-time coordination + admin controls) ---

The batch pipeline above stays intact. Phase 3 makes the system behave as a real-time
administrative platform: patients are coordinated the instant they submit (the always-on
Python console, Data/Dashboard/console_server.py, mirrors Main.xaml + Workflows/*.xaml for
one patient), unmet needs become persistent PENDING_REQUIREMENTS rows instead of a wait
queue, and an authorised administrator can free resources and approve discharges. Every new
behaviour also exists as a native UiPath workflow so a Studio run demonstrates it. No ML,
no new dependencies - deterministic rules, database operations, event-driven processing.

F1  Admin manual resource release. Workflows/ReleaseResource.xaml (standalone Run File) frees
    an occupied/reserved BED / VENTILATOR / DOCTOR / BLOOD unit: the .psv state is really
    mutated, the occupying admission is vacated, reservations/assignments closed, the release
    time and admin name recorded (ADMIN_RELEASE_RESOURCE), then the pending queue is served.
    Console: POST /api/release. Honours Config AdminManualRelease.   [DONE]
F2  First-come-first-served pending fulfilment. An unavailable requested resource -> the patient
    is admitted to the configured fallback ward and a PENDING_REQUIREMENTS row is opened with an
    explicit RequirementCreatedAt; RequestedValue is never overwritten by the fallback.
    Workflows/RegisterRequirement.xaml (idempotent per case+type). Main.xaml opens these rows
    in its no-reservation branch.   [DONE]
F3  Automatic allocation after a release. Workflows/FulfilPendingRequirements.xaml orders open
    requirements EARLIEST-VALID-REQUEST-FIRST (RequirementCreatedAt), verifies the case is still
    active and the resource genuinely free, then allocates - bed transfer into the freed ward
    (temp bed released), consultant via AssignCareTeam, blood on restock, ventilator attach -
    flips OPEN -> FULFILLED and audits AUTOMATIC_RESOURCE_ALLOCATION / BED_TRANSFERRED /
    DOCTOR_ASSIGNED / REQUIREMENT_FULFILLED. ReleaseResource and ApproveDischarge invoke it
    automatically; the console monitor runs it on a timer. Config PendingAllocationOrder=priority
    flips the ordering back to priority-first.   [DONE]
F4  Same FCFS mechanism for every limited resource (beds, wards, ventilators, doctors, blood).
    A requirement is skipped if its case is discharged/closed or the resource does not match.   [DONE]
F5/F6 Admin dashboard: a manual-release grid and a discharge-approval queue, both live from
    /api/state; the intake form gains an Email field. Releasing a resource auto-fulfils the
    earliest pending and it drops off the list - no manual re-assignment.   [DONE]
F7  Patient email capture. A new EmailAddress column on PatientInput.psv (col 13, optional) +
    Workflows/CapturePatientContact.xaml -> Data/db/PATIENT_CONTACT.psv side table (no PATIENTS
    schema change). Validated format (BE-011 on a malformed value). Console captures it on submit.   [DONE]
F8  Discharge approval. Treatment-complete never auto-discharges. CertifyDischarge.xaml
    (HUMAN GATE 2) still certifies clinical fitness; Workflows/ApproveDischarge.xaml is the new
    administrative gate: a case is approved when APPROVE_DISCHARGE_<case>.txt is present (first
    line "Admin: <name>" is logged) OR Config DischargeRequiresAdminApproval=False (demo bypass).
    On approval: audit DISCHARGE_APPROVED, write a DISCHARGE_APPROVED_<case>.txt marker, then
    EmailFinalBill -> ProcessDischarge -> FulfilPendingRequirements. Console: POST /api/approve-discharge.   [DONE]
F9  Automatic bill email. Workflows/EmailFinalBill.xaml totals the EXISTING BILLING rows only
    (no invented charges) into the final bill - hospital, patient, admission id, dates, doctor,
    ward/bed, line items, subtotal, configurable BillingTaxPercent, total, payment status -
    writes BILL_<case>.txt/.html, audits BILL_GENERATED, then writes a simulated
    EMAIL_<case>_bill_<ts>.html envelope to EmailOutputFolder and audits BILL_EMAIL_SENT.   [DONE]
F10 Billing happens AFTER discharge approval. ProcessDischarge.xaml now also requires the
    DISCHARGE_APPROVED_<case>.txt marker (unless DischargeRequiresAdminApproval=False) before it
    will total the bill and release resources.   [DONE]
F11 Resource release after discharge. ProcessDischarge frees the bed / ventilator / doctors;
    ApproveDischarge then runs FulfilPendingRequirements so the freed bed goes to the earliest
    valid pending request.   [DONE]
F12 Audit logging: ADMIN_RELEASE_RESOURCE, AUTOMATIC_RESOURCE_ALLOCATION, TEMP_BED_ASSIGNED,
    REQUIREMENT_OPENED/FULFILLED, BED_TRANSFERRED, DOCTOR_ASSIGNED, DISCHARGE_APPROVED,
    BILL_GENERATED, BILL_EMAIL_SENT, EMAIL_SEND_FAILED, RESOURCE_RELEASED_AFTER_DISCHARGE -
    each with timestamp, admin/user, case, resource, description.   [DONE]
F13 Failure handling. An email failure (no address on file, write error) is caught, audited
    EMAIL_SEND_FAILED and surfaced as a WARN alert - the discharge, billing and resource
    release are never rolled back. Allocation re-checks availability immediately before writing
    so a resource taken by another process is not double-assigned.   [DONE]
F14 Nothing was rewritten. The 15-step batch pipeline, the datastore, the dashboards and the
    acceptance suite are unchanged; a normal 8-case Main.xaml run opens no PENDING_REQUIREMENTS
    rows (every resource is available) so RunAcceptanceTests still passes exactly as before.   [DONE]

Data model rule: RequestedValue (what the patient asked for) and the current bed are always
kept distinct; RequirementStatus goes OPEN -> FULFILLED (or CANCELLED); the fallback bed is a
TEMPORARY allocation released on transfer.

Config flags added: AdminManualRelease, PendingAllocationOrder (fifo|priority),
DischargeRequiresAdminApproval, BillingTaxPercent, BillingEmailSubjectPrefix.

QUEUE POLICY: this project uses NO UiPath Queue (Config UseQueue=False). The primary patient
admission flow starts immediately on submission (Main.xaml loops the input file; the console
processes each submission synchronously). PENDING_REQUIREMENTS is a persistent requirement
LEDGER polled by FulfilPendingRequirements / the console monitor - not a wait-to-be-picked
work queue: a patient is admitted first (into a fallback bed) and the requirement is fulfilled
in the background when the resource frees. If a real deployment adds an Orchestrator queue it
should carry only non-blocking secondary work (notifications, report/audit batch, retries).

DEMO SEQUENCE (Phase 3):
  Studio: run Main.xaml  (intake -> readiness -> HUMAN GATE 1 -> reserve -> admission;
          unmet needs open PENDING_REQUIREMENTS rows)
  Run File: AccrueCharges.xaml  (xN, advances billing days)
  Run File: CertifyDischarge.xaml   (HUMAN GATE 2 - attending doctor certifies fitness)
  Drop file: APPROVE_DISCHARGE_<case>.txt  (authorised admin sign-off)
  Run File: ApproveDischarge.xaml   (-> EmailFinalBill -> ProcessDischarge -> FulfilPendingRequirements)
  Run File: PostDischargeFollowUp.xaml
  Any time: Run File ReleaseResource.xaml (in_Kind / in_ResourceId / in_AdminName) to free a
            resource and watch the earliest pending requirement get served automatically.
  Live alternative: Data/Dashboard/Start Console.bat - submit from the browser, use the
                    "Manual resource release" and "Discharge approvals" panels on the admin tab.
  Tests: python Tests/finetune_checks.py (46/46) ; Run File Tests/RunFineTuneTests.xaml
         (writes TEST_RESULTS.psv - rewrites the datastore, ResetDatastore afterwards).

FOR EACH PHASE

Before modifying files:

1. Explain what you are going to build.
2. Identify which files will be created or modified.
3. Implement the changes.
4. Validate the result.
5. Report any errors.
6. Fix errors before proceeding.
7. Keep the implementation compatible with UiPath Studio.

DO NOT MOVE TO THE NEXT MAJOR PHASE IF THE CURRENT PHASE IS BROKEN.

FINAL DELIVERABLES

The completed project should contain:

1. Working UiPath project
2. project.json
3. Main.xaml
4. Modular XAML workflows
5. Database
6. Database initialization script
7. Sample hospital data
8. Sample patient documents
9. Configuration file
10. Test cases
11. Exception handling
12. Logging
13. Audit trail
14. Notification workflow
15. Human approval workflow or documented Action Center implementation
16. Queue implementation where appropriate
17. README documentation
18. Architecture diagram
19. Demo instructions

FINAL README SHOULD EXPLAIN

Project overview
Problem statement
Objectives
Use case
Architecture
Workflow
Database schema
UiPath components
Business rules
Exception handling
Human-in-the-loop
Test scenarios
Expected outputs
Installation/setup
How to run
How to demonstrate
Limitations
Future improvements

MOST IMPORTANT REQUIREMENT

Build a genuine, demonstrable UiPath RPA project.

Do not create a fake implementation where Python performs the actual automation and UiPath only launches the script.

UiPath should be responsible for the actual orchestration and automation workflow.

External components should serve only as supporting systems such as the simulated hospital database or test-data generation.

Start with PHASE 1 only.

First inspect the current workspace and determine whether a UiPath project already exists.

If an existing UiPath project exists, do not overwrite it. Analyze it first and adapt the implementation.

If no project exists, prepare the architecture and project structure.

Do not start coding the complete system until the Phase 1 architecture is clear.
