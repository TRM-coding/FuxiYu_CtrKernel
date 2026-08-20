-- Machine maintenance axis split (2026-08)
--
-- machine_status keeps only automatic connectivity state: online/offline.
-- is_maintenance is the administrator-controlled maintenance switch.

ALTER TABLE machines
  ADD COLUMN is_maintenance BOOLEAN NOT NULL DEFAULT FALSE;
