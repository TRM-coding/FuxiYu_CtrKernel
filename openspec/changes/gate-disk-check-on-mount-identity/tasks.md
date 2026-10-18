# Tasks

## 1. 接收链路与既有列

- [ ] 1.1 在 `_apply_disk_usage_entry` 中先处理路径、再判断测量：新协议 `mount_path_status=resolved` 且路径非空时更新 `bind_mount_path`；`no_bind` 清空；`unresolved`/`not_running`/路径为空/字段缺失保留已有路径；旧 Node 帧不改写或清空路径。验证：resolved 修正、no_bind 清空、unresolved 保留、旧 Node 路径 A 不回写已校正的 B。
- [ ] 1.2 用既有更新链路支持磁盘四元组与 `bind_mount_path` 的专用显式清空，不把普通 `None` 一律当清空；路径变化或 no_bind 时清空旧路径相关 `disk_overlay_rw_bytes`/`disk_bind_mount_bytes`/`disk_total_bytes`/`disk_checked_at`，再按新路径完整样本回填。验证：旧路径 A→B 后旧 A 字节不贴 B；其他 `update_container` 调用传 `None` 不会误清。
- [ ] 1.3 实现测量接收：`total_bytes`/overlay/必要 bind 字节完整；当前路径为空时只有 `no_bind` 才允许 overlay-only；`measured_at` 解析、未来偏差、缺省旧 Node 兼容；真实 `measured_at` 写入既有 `disk_checked_at`，重复缓存帧同值不刷新。验证：失败/缺组成不写 0、不刷新时间；重复帧不推进；无效 `measured_at` 只拒绝测量但仍落合法路径。
- [ ] 1.4 清理手动刷新回写：删除 `_refresh_disk_async` 对 `disk_*`/`disk_checked_at` 的补零重写（或改为纯读）；不得用 DB 现值或接收时间冒充新测量。验证：手动刷新不改变磁盘事实，不把缺失值写成 0。
- [ ] 1.5 不新增 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation` 或 `disk_identity_*`，不新增模型/迁移；保留既有 `disk_*_bytes`、`disk_checked_at`、`bind_mount_path`。验证：模型/仓储/迁移无新列，诊断只进日志。

## 2. 评估与兼容

- [ ] 2.1 在 `_usage_from_db`/评估入口增加 `disk_checked_at` 年龄判断（初值 3600 秒，不低于 Node 缓存 TTL 900 秒与 du 超时 600 秒之和）；无当前完整、路径一致且未过期的测量时跳过 pause、冻结重置、邮件、升级删除和挂载清理。验证：过期/缺时间/路径不一致/缺组成均不动作；同路径 unresolved 有效测量仍可评估。
- [ ] 2.2 保持冻结、恢复、长期、删除、清理资格与 Q72 不变：不新增 review/invalid，不重写冻结流程，不因路径诊断额外顺延或阻断；路径修正不授予删除/清理权限。验证：冻结锚点/宽限/补偿、长期资格、恢复路径与删除清理用例不因本变更改变。
- [ ] 2.3 旧 Node 兼容矩阵：无 `mount_path_status` 的帧不改写或清空已有路径；当前路径为空且帧内路径非空时可按旧协议建立路径并按接收时间接收测量；新 Node 已明确 no_bind 的容器用进程内标记拒绝旧帧重建；当前路径非空且帧内路径一致时接收测量；路径不一致或两者皆空时不把其字节当新测量。验证：旧帧首次建立路径、no_bind 后旧帧重建、路径一致/不一致、两者皆空的 no_bind 歧义、旧手动刷新、旧缓存心跳、已校正后回滚旧 Node 的过期行为、Ctrl 重启后 no_bind 标记丢失的残留。
- [ ] 2.4 查询/日志只读现有字段：继续返回 `bind_mount_path` 与既有字节；拒绝原因、机器/容器、帧内关键值只进日志，不落状态列、不落观测 JSON、不作为业务状态回读。验证：日志可检索，API 出参无新增状态/观测字段依赖。

## 3. 联合验收

- [ ] 3.1 与 Node `verify-bind-mount-identity` 回放 resolved/unresolved/not_running/no_bind、Source 改变、路径 A→B 与在途旧样本、失败/缺组成、重复帧、手动刷新、旧 Node 路径一致/不一致；确认 Ctrl 不比较 dev/inode/PID，不以 `resolved` 作业务门禁。
- [ ] 3.2 确认无 schema 变更：不新增四列，不新增迁移，不改模型；`disk_checked_at` 仍为既有列，只改变写入语义。验证：隔离库旧结构可直接运行，旧行无需回填。
- [ ] 3.3 运行 `openspec validate gate-disk-check-on-mount-identity --strict` 与 `git diff --check`；核对与 `guard-long-term-container-transitions` 只共享既有路径/测量字段，不交叉修改其对象代际、资格或 Q72 文档。

## Workflow follow-up

- 本阶段只修待执行 OpenSpec 文档，不实施代码、不写模型/迁移/测试、不提交/部署/SSH。
- 评审后按仓库流程 archive；归档时只把本 delta 的既有字段语义合并进正式 `backend--table-containers` 主规格，不新增列。
- Node 只负责内部定位并回填业务路径；路径修正不是删除/清理授权，不新增 inode 清理门禁，也不宣称 Q70 跨进程原子。
