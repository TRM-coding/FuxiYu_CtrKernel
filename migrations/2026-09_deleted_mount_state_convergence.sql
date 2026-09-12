-- Deleted container lifecycle convergence, 2026-09.
--
-- DeletedContainerRestoreSnapshot is the lifecycle source of truth.
-- ContainerMountCleanup remains an execution record and points back to it.
--
-- The application startup compatibility path adds mount_cleaned/deleted_id for
-- old databases. Run the statements below in production to finish the column
-- retirement after verifying the backup.

ALTER TABLE deleted_container_restore_snapshot
    ADD COLUMN mount_cleaned BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE deleted_container_restore_snapshot
SET mount_cleaned = TRUE
WHERE mount_path IS NULL;

UPDATE deleted_container_restore_snapshot d
JOIN container_mount_cleanup c ON c.id = d.mount_cleanup_id
SET d.mount_cleaned = TRUE
WHERE c.cleaned_at IS NOT NULL;

ALTER TABLE container_mount_cleanup
    ADD COLUMN deleted_id INTEGER NULL;

UPDATE container_mount_cleanup c
JOIN deleted_container_restore_snapshot d ON d.mount_cleanup_id = c.id
SET c.deleted_id = d.id
WHERE c.deleted_id IS NULL;

-- These values are duplicated by the retained Container row, the snapshot,
-- or the operation log. Remove them after the application code is deployed.
ALTER TABLE deleted_container_restore_snapshot
    DROP COLUMN operator_user_id,
    DROP COLUMN machine_name,
    DROP COLUMN machine_ip,
    DROP COLUMN mount_path;

-- SQLite installations should use a table rebuild (or SQLite >= 3.35 DROP
-- COLUMN one at a time after checking dependent indexes), because SQLite
-- ALTER TABLE support differs by version. The startup path intentionally does
-- not perform destructive column drops.
