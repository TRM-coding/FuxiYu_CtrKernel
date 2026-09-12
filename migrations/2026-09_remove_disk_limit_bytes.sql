-- 容器磁盘上限统一（2026-09-01 决策，见 FuxiYu_Global 速查 · 决策备忘）
-- containers.disk_limit_bytes 移除：它从来是 machine 级上限的字节拷贝
-- （同机器所有容器同值，非 per-container 配额），展示/冻结均已改为
-- 以 machine.max_disk_size_gb 现算派生，此列无独立信息量。
-- 破坏性：删列不可逆，但值可随时由 max_disk_size_gb 重新导出。

ALTER TABLE containers
    DROP COLUMN disk_limit_bytes;
