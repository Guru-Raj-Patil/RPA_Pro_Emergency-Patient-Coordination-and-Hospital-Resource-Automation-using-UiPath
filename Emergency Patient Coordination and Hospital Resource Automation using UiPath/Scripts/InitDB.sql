-- ============================================================
-- HospitalDB.db  –  Emergency Patient Coordination System
-- SQLite Schema + Seed Data
-- Generated for UiPath RPA Project
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============================================================
-- DROP existing tables (safe re-run)
-- ============================================================
DROP TABLE IF EXISTS AUDIT_LOG;
DROP TABLE IF EXISTS RESOURCE_RESERVATIONS;
DROP TABLE IF EXISTS EMERGENCY_CASES;
DROP TABLE IF EXISTS DOCUMENTS;
DROP TABLE IF EXISTS BEDS;
DROP TABLE IF EXISTS VENTILATORS;
DROP TABLE IF EXISTS BLOOD_INVENTORY;
DROP TABLE IF EXISTS PATIENTS;

-- ============================================================
-- TABLE: PATIENTS
-- ============================================================
CREATE TABLE PATIENTS (
    PatientId           TEXT    PRIMARY KEY,
    Name                TEXT    NOT NULL,
    Age                 INTEGER NOT NULL,
    Gender              TEXT    NOT NULL,
    EmergencyType       TEXT    NOT NULL,
    RequiredDepartment  TEXT    NOT NULL,
    RequiredVentilator  INTEGER NOT NULL DEFAULT 0,
    RequiredBloodGroup  TEXT,
    RequiredBloodUnits  INTEGER NOT NULL DEFAULT 0,
    CreatedAt           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ============================================================
-- TABLE: VENTILATORS
-- ============================================================
CREATE TABLE VENTILATORS (
    VentilatorId    TEXT    PRIMARY KEY,
    Status          TEXT    NOT NULL DEFAULT 'Available',
    Location        TEXT    NOT NULL,
    LastUpdated     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ============================================================
-- TABLE: BEDS
-- ============================================================
CREATE TABLE BEDS (
    BedId           TEXT    PRIMARY KEY,
    Department      TEXT    NOT NULL,
    BedType         TEXT    NOT NULL DEFAULT 'Standard',
    Status          TEXT    NOT NULL DEFAULT 'Available',
    VentilatorId    TEXT    REFERENCES VENTILATORS(VentilatorId),
    LastUpdated     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ============================================================
-- TABLE: BLOOD_INVENTORY
-- ============================================================
CREATE TABLE BLOOD_INVENTORY (
    BloodGroup          TEXT    PRIMARY KEY,
    AvailableUnits      INTEGER NOT NULL DEFAULT 0,
    MinimumThreshold    INTEGER NOT NULL DEFAULT 3,
    LastUpdated         TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ============================================================
-- TABLE: DOCUMENTS
-- ============================================================
CREATE TABLE DOCUMENTS (
    DocumentId          INTEGER PRIMARY KEY AUTOINCREMENT,
    PatientId           TEXT    NOT NULL REFERENCES PATIENTS(PatientId),
    DocumentType        TEXT    NOT NULL,
    FilePath            TEXT,
    VerificationStatus  TEXT    NOT NULL DEFAULT 'Missing',
    VerifiedAt          TEXT
);

-- ============================================================
-- TABLE: EMERGENCY_CASES
-- ============================================================
CREATE TABLE EMERGENCY_CASES (
    CaseId              TEXT    PRIMARY KEY,
    PatientId           TEXT    NOT NULL REFERENCES PATIENTS(PatientId),
    CaseStatus          TEXT    NOT NULL DEFAULT 'Open',
    DocumentStatus      TEXT    NOT NULL DEFAULT 'Pending',
    BedStatus           TEXT    NOT NULL DEFAULT 'Pending',
    VentilatorStatus    TEXT    NOT NULL DEFAULT 'Pending',
    BloodStatus         TEXT    NOT NULL DEFAULT 'Pending',
    ReadinessPercentage INTEGER NOT NULL DEFAULT 0,
    PendingAction       TEXT,
    CreatedAt           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UpdatedAt           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ============================================================
-- TABLE: RESOURCE_RESERVATIONS
-- ============================================================
CREATE TABLE RESOURCE_RESERVATIONS (
    ReservationId   INTEGER PRIMARY KEY AUTOINCREMENT,
    CaseId          TEXT    NOT NULL REFERENCES EMERGENCY_CASES(CaseId),
    ResourceType    TEXT    NOT NULL,
    ResourceId      TEXT    NOT NULL,
    Quantity        INTEGER NOT NULL DEFAULT 1,
    Status          TEXT    NOT NULL DEFAULT 'Reserved',
    ReservedAt      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ============================================================
-- TABLE: AUDIT_LOG
-- ============================================================
CREATE TABLE AUDIT_LOG (
    LogId       INTEGER PRIMARY KEY AUTOINCREMENT,
    CaseId      TEXT    NOT NULL,
    Action      TEXT    NOT NULL,
    Description TEXT    NOT NULL,
    Timestamp   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    PerformedBy TEXT    NOT NULL DEFAULT 'Bot'
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX idx_documents_patientid   ON DOCUMENTS(PatientId);
CREATE INDEX idx_emergcases_patientid  ON EMERGENCY_CASES(PatientId);
CREATE INDEX idx_reservations_caseid   ON RESOURCE_RESERVATIONS(CaseId);
CREATE INDEX idx_auditlog_caseid       ON AUDIT_LOG(CaseId);
CREATE INDEX idx_beds_dept_status      ON BEDS(Department, Status);

-- ============================================================
-- SEED: VENTILATORS
-- ============================================================
INSERT INTO VENTILATORS (VentilatorId, Status, Location) VALUES
    ('V-01', 'Occupied',  'ICU Ward A'),
    ('V-02', 'Occupied',  'ICU Ward A'),
    ('V-03', 'Available', 'ICU Ward B'),
    ('V-04', 'Available', 'ICU Ward B'),
    ('V-05', 'Available', 'ICU Ward C'),
    ('V-06', 'Available', 'ICU Ward C');

-- ============================================================
-- SEED: BEDS
-- ============================================================
INSERT INTO BEDS (BedId, Department, BedType, Status, VentilatorId) VALUES
    ('ICU-01',  'ICU',        'Premium',  'Occupied',  'V-01'),
    ('ICU-02',  'ICU',        'Premium',  'Occupied',  'V-02'),
    ('ICU-03',  'ICU',        'Premium',  'Available', 'V-03'),
    ('ICU-04',  'ICU',        'Standard', 'Available', 'V-04'),
    ('GEN-01',  'General',    'Standard', 'Occupied',  NULL),
    ('GEN-02',  'General',    'Standard', 'Available', NULL),
    ('GEN-03',  'General',    'Standard', 'Available', NULL),
    ('GEN-04',  'General',    'Standard', 'Available', NULL),
    ('CARD-01', 'Cardiology', 'Premium',  'Available', 'V-05'),
    ('CARD-02', 'Cardiology', 'Standard', 'Available', NULL);

-- ============================================================
-- SEED: BLOOD_INVENTORY
-- ============================================================
INSERT INTO BLOOD_INVENTORY (BloodGroup, AvailableUnits, MinimumThreshold) VALUES
    ('A+',  15, 3),
    ('A-',   5, 2),
    ('B+',  12, 3),
    ('B-',   4, 2),
    ('AB+',  8, 2),
    ('AB-',  2, 1),
    ('O+',  20, 5),
    ('O-',   6, 2);

-- ============================================================
-- SEED: PATIENTS
-- ============================================================
-- T1: All docs + resources available -> 100% READY
INSERT INTO PATIENTS VALUES ('P1024','Rahul Kumar',  54,'Male',  'Critical','ICU',        1,'O-',  4, datetime('now','localtime'));
-- T2: Missing Medical Report          -> 75% PENDING_DOCUMENTATION
INSERT INTO PATIENTS VALUES ('P1025','Ananya Singh', 32,'Female','Urgent',  'ICU',        0,'A+',  2, datetime('now','localtime'));
-- T3: Run TestSetup_T3 first (all ICU beds occupied) -> PENDING_BED
INSERT INTO PATIENTS VALUES ('P1026','Mohan Das',    67,'Male',  'Critical','ICU',        1,'B+',  3, datetime('now','localtime'));
-- T4: Run TestSetup_T4 first (all vents occupied)   -> PENDING_VENTILATOR
INSERT INTO PATIENTS VALUES ('P1027','Priya Sharma', 45,'Female','Critical','ICU',        1,'AB+', 2, datetime('now','localtime'));
-- T5: O- available=6, needs 10                       -> PENDING_BLOOD
INSERT INTO PATIENTS VALUES ('P1028','Arun Mehta',   29,'Male',  'Critical','ICU',        1,'O-',  10,datetime('now','localtime'));
-- T6a: Batch General ward
INSERT INTO PATIENTS VALUES ('P1029','Kavitha Nair', 38,'Female','Standard','General',    0,'B-',  2, datetime('now','localtime'));
-- T6b: Batch General ward
INSERT INTO PATIENTS VALUES ('P1030','Suresh Patel', 61,'Male',  'Urgent',  'General',    0,'A-',  1, datetime('now','localtime'));
-- T6c / T8 base: Cardiology
INSERT INTO PATIENTS VALUES ('P1031','Deepa Reddy',  55,'Female','Critical','Cardiology',  0,'AB-', 1, datetime('now','localtime'));

-- ============================================================
-- SEED: DOCUMENTS
-- ============================================================
-- P1024 – all present
INSERT INTO DOCUMENTS (PatientId,DocumentType,FilePath,VerificationStatus,VerifiedAt) VALUES
('P1024','ID_Proof',      'Patients/P1024/ID_Proof.pdf',      'Present',datetime('now','localtime')),
('P1024','Insurance',     'Patients/P1024/Insurance.pdf',     'Present',datetime('now','localtime')),
('P1024','Consent_Form',  'Patients/P1024/Consent_Form.pdf',  'Present',datetime('now','localtime')),
('P1024','Medical_Report','Patients/P1024/Medical_Report.pdf','Present',datetime('now','localtime'));

-- P1025 – Medical_Report MISSING (T2)
INSERT INTO DOCUMENTS (PatientId,DocumentType,FilePath,VerificationStatus,VerifiedAt) VALUES
('P1025','ID_Proof',      'Patients/P1025/ID_Proof.pdf',    'Present',datetime('now','localtime')),
('P1025','Insurance',     'Patients/P1025/Insurance.pdf',   'Present',datetime('now','localtime')),
('P1025','Consent_Form',  'Patients/P1025/Consent_Form.pdf','Present',datetime('now','localtime')),
('P1025','Medical_Report','',                                'Missing',NULL);

-- P1026 – all present
INSERT INTO DOCUMENTS (PatientId,DocumentType,FilePath,VerificationStatus,VerifiedAt) VALUES
('P1026','ID_Proof',      'Patients/P1026/ID_Proof.pdf',      'Present',datetime('now','localtime')),
('P1026','Insurance',     'Patients/P1026/Insurance.pdf',     'Present',datetime('now','localtime')),
('P1026','Consent_Form',  'Patients/P1026/Consent_Form.pdf',  'Present',datetime('now','localtime')),
('P1026','Medical_Report','Patients/P1026/Medical_Report.pdf','Present',datetime('now','localtime'));

-- P1027 – all present
INSERT INTO DOCUMENTS (PatientId,DocumentType,FilePath,VerificationStatus,VerifiedAt) VALUES
('P1027','ID_Proof',      'Patients/P1027/ID_Proof.pdf',      'Present',datetime('now','localtime')),
('P1027','Insurance',     'Patients/P1027/Insurance.pdf',     'Present',datetime('now','localtime')),
('P1027','Consent_Form',  'Patients/P1027/Consent_Form.pdf',  'Present',datetime('now','localtime')),
('P1027','Medical_Report','Patients/P1027/Medical_Report.pdf','Present',datetime('now','localtime'));

-- P1028 – all present
INSERT INTO DOCUMENTS (PatientId,DocumentType,FilePath,VerificationStatus,VerifiedAt) VALUES
('P1028','ID_Proof',      'Patients/P1028/ID_Proof.pdf',      'Present',datetime('now','localtime')),
('P1028','Insurance',     'Patients/P1028/Insurance.pdf',     'Present',datetime('now','localtime')),
('P1028','Consent_Form',  'Patients/P1028/Consent_Form.pdf',  'Present',datetime('now','localtime')),
('P1028','Medical_Report','Patients/P1028/Medical_Report.pdf','Present',datetime('now','localtime'));

-- P1029 – all present
INSERT INTO DOCUMENTS (PatientId,DocumentType,FilePath,VerificationStatus,VerifiedAt) VALUES
('P1029','ID_Proof',      'Patients/P1029/ID_Proof.pdf',      'Present',datetime('now','localtime')),
('P1029','Insurance',     'Patients/P1029/Insurance.pdf',     'Present',datetime('now','localtime')),
('P1029','Consent_Form',  'Patients/P1029/Consent_Form.pdf',  'Present',datetime('now','localtime')),
('P1029','Medical_Report','Patients/P1029/Medical_Report.pdf','Present',datetime('now','localtime'));

-- P1030 – all present
INSERT INTO DOCUMENTS (PatientId,DocumentType,FilePath,VerificationStatus,VerifiedAt) VALUES
('P1030','ID_Proof',      'Patients/P1030/ID_Proof.pdf',      'Present',datetime('now','localtime')),
('P1030','Insurance',     'Patients/P1030/Insurance.pdf',     'Present',datetime('now','localtime')),
('P1030','Consent_Form',  'Patients/P1030/Consent_Form.pdf',  'Present',datetime('now','localtime')),
('P1030','Medical_Report','Patients/P1030/Medical_Report.pdf','Present',datetime('now','localtime'));

-- P1031 – all present
INSERT INTO DOCUMENTS (PatientId,DocumentType,FilePath,VerificationStatus,VerifiedAt) VALUES
('P1031','ID_Proof',      'Patients/P1031/ID_Proof.pdf',      'Present',datetime('now','localtime')),
('P1031','Insurance',     'Patients/P1031/Insurance.pdf',     'Present',datetime('now','localtime')),
('P1031','Consent_Form',  'Patients/P1031/Consent_Form.pdf',  'Present',datetime('now','localtime')),
('P1031','Medical_Report','Patients/P1031/Medical_Report.pdf','Present',datetime('now','localtime'));

-- ============================================================
-- Verification row-counts
-- ============================================================
SELECT 'PATIENTS'        AS TableName, COUNT(*) AS Rows FROM PATIENTS        UNION ALL
SELECT 'VENTILATORS'     AS TableName, COUNT(*) AS Rows FROM VENTILATORS      UNION ALL
SELECT 'BEDS'            AS TableName, COUNT(*) AS Rows FROM BEDS             UNION ALL
SELECT 'BLOOD_INVENTORY' AS TableName, COUNT(*) AS Rows FROM BLOOD_INVENTORY  UNION ALL
SELECT 'DOCUMENTS'       AS TableName, COUNT(*) AS Rows FROM DOCUMENTS;
