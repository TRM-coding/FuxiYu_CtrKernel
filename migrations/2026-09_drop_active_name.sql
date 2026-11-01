-- 卸除已废弃的 active_name 派生列（2026-09 决策）。
--
-- 背景：软删要求「删掉即释放名字」，而 UNIQUE(name, machine_id) 会让已删行继续占名。
-- 当时的解法是加一个派生列 active_name（活着=name、删掉=NULL），靠 MySQL/SQLite
-- 唯一索引允许多个 NULL 的性质做出「只对有效子集唯一」的效果。
-- 事后评估：这个不变式的真正守卫在 Node 侧（docker daemon 拒绝同名容器，且请求 Node
-- 发生在落库之前），DB 这层只是兜底；而 active_name 带来的成本是实打实的——
-- 一个冗余存储位（可与 is_valid 脱钩）、一个 mapper 事件、若干回填路径、跨方言 collation
-- 分歧，以及每次改软删语义都要同步维护它。故整套卸除。
--
-- 仅对「曾按旧版 2026-09_container_soft_delete_strict_ids.sql 迁移过」的库需要执行。
-- 全新建的库（create_all）不会有这一列。
--
-- 顺序是硬约束：必须先删索引再删列。
-- MySQL 在 DROP COLUMN 时会把该列从所属索引中移除，若索引因此只剩 machine_id，
-- 就会留下 UNIQUE(machine_id) —— 那等于「每台机器只能有一个容器」。
-- 先删索引可以彻底避开这条路径。
--
-- MySQL / MariaDB production path.
ALTER TABLE containers
    DROP INDEX uq_container_active_name_machine;

ALTER TABLE containers
    DROP COLUMN active_name;

-- SQLite notes:
-- - 若该列是由建表语句内联的 UNIQUE 约束承载，ALTER TABLE 无法卸除。
--   不必强行重建：列值已是死的（新代码不再写它，全为 NULL），多个 NULL 在唯一约束下
--   互不冲突，残留约束因此是惰性的。应用启动时的自愈也会把旧值清空。
