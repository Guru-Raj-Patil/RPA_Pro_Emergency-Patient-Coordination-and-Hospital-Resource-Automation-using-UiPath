-- TestSetup_T3_NoBed.sql
-- Scenario T3: Mark ALL ICU beds as Occupied so P1026 (ICU dept) finds no bed.
-- Run BEFORE processing P1026.

UPDATE BEDS SET Status = 'Occupied', LastUpdated = datetime('now','localtime')
WHERE Department = 'ICU';

-- Verify
SELECT BedId, Department, Status FROM BEDS WHERE Department = 'ICU';
