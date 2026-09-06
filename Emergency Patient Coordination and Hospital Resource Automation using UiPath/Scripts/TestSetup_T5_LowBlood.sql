-- TestSetup_T5_LowBlood.sql
-- Scenario T5: Reduce O- blood to 3 units so P1028 (needs 10) finds insufficient inventory.
-- Run BEFORE processing P1028.

UPDATE BLOOD_INVENTORY
SET AvailableUnits = 3, LastUpdated = datetime('now','localtime')
WHERE BloodGroup = 'O-';

-- Verify
SELECT BloodGroup, AvailableUnits, MinimumThreshold FROM BLOOD_INVENTORY WHERE BloodGroup = 'O-';
