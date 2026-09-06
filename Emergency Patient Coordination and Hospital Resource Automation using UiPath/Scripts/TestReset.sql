-- TestReset.sql
-- Resets all transactional tables and resource statuses to the baseline seed state.
-- Run between test scenarios for a clean slate.

-- Clear transactional tables
DELETE FROM AUDIT_LOG;
DELETE FROM RESOURCE_RESERVATIONS;
DELETE FROM EMERGENCY_CASES;

-- Reset BEDS to baseline
UPDATE BEDS SET Status = 'Occupied',  LastUpdated = datetime('now','localtime') WHERE BedId IN ('ICU-01','ICU-02','GEN-01');
UPDATE BEDS SET Status = 'Available', LastUpdated = datetime('now','localtime') WHERE BedId NOT IN ('ICU-01','ICU-02','GEN-01');

-- Reset VENTILATORS to baseline
UPDATE VENTILATORS SET Status = 'Occupied',  LastUpdated = datetime('now','localtime') WHERE VentilatorId IN ('V-01','V-02');
UPDATE VENTILATORS SET Status = 'Available', LastUpdated = datetime('now','localtime') WHERE VentilatorId NOT IN ('V-01','V-02');

-- Reset BLOOD_INVENTORY to baseline
UPDATE BLOOD_INVENTORY SET AvailableUnits = 15, LastUpdated = datetime('now','localtime') WHERE BloodGroup = 'A+';
UPDATE BLOOD_INVENTORY SET AvailableUnits =  5, LastUpdated = datetime('now','localtime') WHERE BloodGroup = 'A-';
UPDATE BLOOD_INVENTORY SET AvailableUnits = 12, LastUpdated = datetime('now','localtime') WHERE BloodGroup = 'B+';
UPDATE BLOOD_INVENTORY SET AvailableUnits =  4, LastUpdated = datetime('now','localtime') WHERE BloodGroup = 'B-';
UPDATE BLOOD_INVENTORY SET AvailableUnits =  8, LastUpdated = datetime('now','localtime') WHERE BloodGroup = 'AB+';
UPDATE BLOOD_INVENTORY SET AvailableUnits =  2, LastUpdated = datetime('now','localtime') WHERE BloodGroup = 'AB-';
UPDATE BLOOD_INVENTORY SET AvailableUnits = 20, LastUpdated = datetime('now','localtime') WHERE BloodGroup = 'O+';
UPDATE BLOOD_INVENTORY SET AvailableUnits =  6, LastUpdated = datetime('now','localtime') WHERE BloodGroup = 'O-';

-- Reset document statuses (in case bot updated them)
UPDATE DOCUMENTS SET VerificationStatus = 'Present', VerifiedAt = datetime('now','localtime')
WHERE PatientId <> 'P1025' OR DocumentType <> 'Medical_Report';

UPDATE DOCUMENTS SET VerificationStatus = 'Missing', VerifiedAt = NULL
WHERE PatientId = 'P1025' AND DocumentType = 'Medical_Report';

-- Confirm
SELECT 'Reset complete' AS Status;
SELECT 'EMERGENCY_CASES'       AS T, COUNT(*) FROM EMERGENCY_CASES       UNION ALL
SELECT 'RESOURCE_RESERVATIONS' AS T, COUNT(*) FROM RESOURCE_RESERVATIONS UNION ALL
SELECT 'AUDIT_LOG'             AS T, COUNT(*) FROM AUDIT_LOG;
