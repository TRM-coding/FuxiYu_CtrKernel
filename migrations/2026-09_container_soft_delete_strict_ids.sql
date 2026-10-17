-- Container lifecycle convergence, 2026-09.
-- Goal:
-- 1. Containers are soft-deleted through is_valid=false instead of deleting rows.
-- 2. Deleted rows keep the original id so restore can reuse the same record.
-- 3. Names are reusable after deletion — hence the old UNIQUE(name, machine_id) must go.
--
-- 唯一性不再由 DB 承担：真正的守卫在 Node 侧——docker daemon 本身就拒绝同名容器，
-- 而创建链路是「请求 Node → 成功才落库」，竞态被拒时失败发生在落库之前，不会留下重复行。
-- Ctrl 侧的 _ensure_create_name_available 只负责给出可读的 409。
--
-- 曾经为此引入的 active_name 派生列 + uq_container_active_name_machine 已废弃
-- （NULL 技巧换来的局部唯一，成本高于收益）。若目标库曾按旧版迁移建过它们，
-- 另跑 2026-09_drop_active_name.sql 卸除。
--
-- MySQL / MariaDB production path.
ALTER TABLE containers
    ADD COLUMN is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN deleted_at DATETIME NULL,
    ADD COLUMN deleted_trigger VARCHAR(64) NULL,
    ADD COLUMN deleted_reason VARCHAR(255) NULL,
    ADD COLUMN deleted_by_user_id INTEGER NULL;

UPDATE containers
SET is_valid = TRUE
WHERE is_valid IS NULL;

-- 释放名字：软删行保留原行，不再有索引把它的 name 钉住
ALTER TABLE containers
    DROP INDEX uq_container_name_machine;

CREATE INDEX idx_containers_is_valid ON containers(is_valid);

-- SQLite notes:
-- - New SQLite databases created by the app use sqlite_autoincrement=True for every
--   single-column integer primary key, so deleted ids are not reused.
-- - Existing SQLite tables cannot gain AUTOINCREMENT through simple ALTER TABLE.
--   If the table predates soft delete, its inline UNIQUE(name, machine_id) constraint
--   also cannot be dropped by ALTER — rebuild the table from SQLAlchemy metadata or
--   dump/reload into a new app-created database before relying on same-name reuse
--   after soft delete. App-created databases have no such constraint.
