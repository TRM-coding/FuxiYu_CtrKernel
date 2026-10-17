-- 磁盘语义收敛（2026-08-30 决策，见 FuxiYu_Global 速查 · 决策备忘）
-- machine.disk_size_gb：语义从「实际分区大小」→「显示用」（Node 采集 bind_mount 分区容量）
-- machine.max_disk_size_gb（新）：容器磁盘可用上限（管理员维护），冻结/容器展示「已用/上限」用它
-- 回填：新列 NULL → 沿用原 disk_size_gb（上限行为延续）；幂等。

ALTER TABLE machines
    ADD COLUMN max_disk_size_gb INTEGER NULL;

UPDATE machines
    SET max_disk_size_gb = disk_size_gb
    WHERE max_disk_size_gb IS NULL AND disk_size_gb IS NOT NULL;

-- 端口映射（2026-08 决策）：docker 自动分配宿主端口，WSS 快照回填。
ALTER TABLE containers
    ADD COLUMN port_mappings JSON NULL;
