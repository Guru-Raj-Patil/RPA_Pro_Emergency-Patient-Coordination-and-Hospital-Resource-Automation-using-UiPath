-- TestSetup_T4_NoVent.sql
-- Scenario T4: Mark ALL ventilators as Occupied so P1027 (ICU, vent required) finds no ventilator.
-- Run BEFORE processing P1027.

UPDATE VENTILATORS SET Status = 'Occupied', LastUpdated = datetime('now','localtime');

-- Verify
SELECT VentilatorId, Status FROM VENTILATORS;
