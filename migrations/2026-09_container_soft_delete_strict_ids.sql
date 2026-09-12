-- Container lifecycle convergence, 2026-09.
-- Goal:
-- 1. Containers are soft-deleted through is_valid=false instead of deleting rows.
-- 2. Only valid containers block duplicate names on the same machine.
-- 3. Deleted rows keep the original id so restore can reuse the same record.
--
-- MySQL / MariaDB production path.
ALTER TABLE containers
    ADD COLUMN active_name VARCHAR(120) NULL,
    ADD COLUMN is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN deleted_at DATETIME NULL,
    ADD COLUMN deleted_trigger VARCHAR(64) NULL,
    ADD COLUMN deleted_reason VARCHAR(255) NULL,
    ADD COLUMN deleted_by_user_id INTEGER NULL;

UPDATE containers
SET is_valid = TRUE
WHERE is_valid IS NULL;

UPDATE containers
SET active_name = name
WHERE is_valid = TRUE AND active_name IS NULL;

ALTER TABLE containers
    DROP INDEX uq_container_name_machine;

ALTER TABLE containers
    ADD CONSTRAINT uq_container_active_name_machine UNIQUE (active_name, machine_id);

CREATE INDEX idx_containers_is_valid ON containers(is_valid);

-- SQLite notes:
-- - New SQLite databases created by the app use sqlite_autoincrement=True for every
--   single-column integer primary key, so deleted ids are not reused.
-- - Existing SQLite tables cannot gain AUTOINCREMENT, nor can the old
--   UNIQUE(name, machine_id) constraint be removed, through simple ALTER TABLE.
--   Rebuild the affected table from SQLAlchemy metadata or dump/reload into a new
--   app-created database before relying on same-name reuse after soft delete.
