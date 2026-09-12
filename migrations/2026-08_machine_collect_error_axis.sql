-- Machine collect-error axis (2026-08)
--
-- collect_error_at marks "Node cannot collect container statuses right now"
-- (docker daemon hung). Machine-axis condition (data-path contract C1):
-- container DB statuses keep their last-known values; display derives
-- status_unknown. Cleared by the next normal snapshot.

ALTER TABLE machines
  ADD COLUMN collect_error_at DATETIME NULL;
