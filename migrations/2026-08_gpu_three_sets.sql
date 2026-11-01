-- GPU 三集合建模（2026-08-30 决策，见 FuxiYu_Global 速查 · 决策备忘）
-- machines: gpu_list（事实，smi 枚举，sys_snapshot 自动更新）
--           gpu_allow_list（许可，管理员人工维护；空 = 未配置，默认按 gpu_number 全量）
-- containers: gpu_chosen_list（分配，创建时在 allow_list 内选定并锁定）
-- 说明：max_gpu_number 已退役（逻辑上不再使用，列保留不删，避免破坏性迁移）。

ALTER TABLE machines
    ADD COLUMN gpu_list JSON NULL,
    ADD COLUMN gpu_allow_list JSON NULL;

ALTER TABLE containers
    ADD COLUMN gpu_chosen_list JSON NULL;
