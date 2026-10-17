# Tasks

## 1. 数据模型与仓储原语

- [ ] 1.1 在 `models/containers.py` 增加可空 `runtime_transition`（String(24)）、`runtime_action_binding`（JSON）与 `restore_grace`（JSON，`until/granted_at/deferral_seconds/source`），不新增 `runtime_transition_at`；新增迁移并在 `__init__` 的容器自愈入口补同样三列。验证：旧结构迁移可重复执行、旧行三列为 NULL、动作绑定 JSON 可存 action_ref/local_request_id/local_request_seq/link_generation/phase/时间、恢复宽限 JSON 可空且不伪造冻结行。
- [ ] 1.2 更新 `repositories/containers_repo.py` 的 `update_container` allowed/显式清空规则，并让 `restore_container_record` 清空旧 `runtime_transition`/`runtime_action_binding`、在恢复事务内写入 `restore_grace` 与长期标记；不得用通用 None 过滤丢掉宽限 JSON。验证：显式置空/终态更新/普通更新不误清；软删行旧动作不跨实例；宽限和标记在 `is_valid=True` 同一事务中可见或都不可见。
- [ ] 1.3 在 `repositories/long_term_container_repo.py` 增加条件插入 `add_if_absent` 与条件删除 `remove_if_stable`：插入用 MySQL/SQLite 的冲突忽略语义并回读确认是否实际新增（不单依赖驱动 rowcount），删除用 `WHERE EXISTS` 校验容器有效、`container_status IN ('online','offline')`、`status_unknown_since IS NULL`、`runtime_transition IS NULL`，并连接 machines 校验在线、非维护、无采集异常。验证：两个 session 同时插入仍只有一行且只有实际插入方报告 changed；paused/pausing/unknown/主机离线时条件删除 rowcount=0 且标记保留；正常稳定态删除 rowcount=1。不得在该任务中宣称修复 Q67 跨容器数量并发。

## 2. 动作引用绑定、WSS 与动作生命周期

- [ ] 2.0 在调用 Node 前为每次普通/冻结 pause/unpause 生成并持久化唯一 `local_request_id`，受理绑定、同步失败及传输未知回写都 CAS 匹配它；冻结路径另匹配 `pause_request_seq`。验证：两次同方向普通请求的旧 HTTP 回执晚到时不得绑定或清除新过渡，可空的冻结序号不能替代本地请求 ID。

- [ ] 2.1 修改 `services/container_module/actions.py` 的 pause/unpause：通过状态守卫后、调用 Node 前写 `runtime_transition` 和初始绑定（ref=null、local_request_id、冻结序号、当前 link_generation）；HTTP 受理响应带 `action_ref` 时仅在本地请求 ID/序号仍匹配时绑定精确三元组；相同 ref 的旧 accepted 不得覆盖 terminal；受理、超时、传输未知保留。验证：accepted 后过渡仍在且不写 ONLINE；同 ref 旧 accepted 被忽略；写绑定失败时 Node 请求未被调用；`failed` 不直接写容器状态。
- [ ] 2.2 修改 `services/container_module/node_comms_modules/snapshots.py` 及 HTTP 状态处理：WSS 只接受当前 `link_generation`，HTTP last_action 与 WSS 共用同一 ref/phase 解析；`pausing`/`unpausing` 只写过渡；`last_action` 必须精确匹配 ref+action 才处理；`failed`/`superseded` 结束过渡但不写 `container_status=failed`，`unconfirmed`/`timed_out` 不释放；`confirmed`/`idempotent_confirmed` 仅在方向相符实际态（paused/online/offline）时清除；实际 paused/online/offline 可方向成功结束。验证：帧测试覆盖 pause failed+online、unpause failed+online、confirmed+反向旧帧保留屏障、同 ref 旧 accepted、unknown/collect_error 保留、重复帧幂等；failed/受控重建有含 ref/phase/reason 的诊断且不改容器 failed。
- [ ] 2.3 实现旧 Node 缺 ref 兼容与受控重建：无 action_ref/last_action 时只能由方向成功或同步 HTTP 明确失败解除；反向状态只保留 unconfirmed 安全阻断；WSS `online` 不得推断 `pause_failed`；Node epoch 变化时仅在当前链路新鲜就绪、无在途当前动作/更新请求时把旧绑定标 superseded+stale_node_epoch，按实际状态重评，不伪造成功。验证：旧 Node pause 失败+online 保持 unconfirmed；新 Node 精确 failed+online 解除；旧链路帧丢弃；epoch 变化受控重建不写 confirmed，不宣称 Q70 已解。
- [ ] 2.4 与 `unify-disk-freeze-workflow` 共用 action_ref phase/ref 匹配辅助逻辑；冻结路径把 ref 绑定到 `pause_request_seq`，`failed` 只更新 pause_state/冻结事实，不覆盖容器状态；WSS 早于 HTTP ack 时按 ref 有界暂存并在回执匹配后应用。验证：跨变更契约测试覆盖同 ref/不同 epoch、早到终结、缺 ref、旧 accepted、failed+online，确认长期过渡与冻结状态一致且无重复实现。

## 3. 长期资格评估与只读 DTO

- [ ] 3.1 在长期容器族实现测量适配器：复用 `gate-disk-check-on-mount-identity` 的统一有效谓词、协议/测量年龄/路径一致/乱序规则；缺测量/不可信返回 `disk_sample_untrusted`；用 `machine.max_disk_size_gb` 与 `container.disk_hard_limit_percent` 计算硬阈值。验证：缺 `measured_at`、未验证、过期、未来时钟、`measurement_mount_path` 与当前路径不一致、limit<=0、硬阈值配置非法、null/负总量分别拒绝；`mount_path_status=unresolved` 但同路径测量有效时可启用；明确 no_bind 的 overlay 有效；绝不读取 `disk_checked_at` 充当 `disk_measured_at`，不比较 dev/inode。
- [ ] 3.2 实现 `evaluate_long_term_eligibility`，按 design 的固定顺序产出 enable/disable 布尔、原因和磁盘字段；启用检查动作绑定、终态、配额、限额、有效测量和硬阈值；取消只检查动作绑定与终态，不检查磁盘/配额/`freeze_state`。验证：逐项构造 paused、pausing、unpausing、action binding failed+online、unknown、host offline、maintenance、creating、稳定 offline、在线但硬超限、在线软超限、路径 unresolved 但同路径测量有效、已确认解冻但冻结行仍在等用例，断言原因和布尔值；不写任何表；固定 8 字段 DTO 不变。
- [ ] 3.3 定义唯一 `LongTermEligibility` 嵌套模型（8 字段、精确类型、禁止额外字段），扩展 `container_bref_information`、`container_detail_information`、`schemas/container.py` 的 brief/detail 模型为必填，并调整 `information.py` 的 detail/brief 组装；`build_long_term_container_state` 统一生成并保留旧配额字段。验证：detail 与 brief 的字段集合、布尔结论、reason 一致；字段集合严格为契约 8 项且拒绝额外字段；UTC 时间带 `Z`；总用量/限额/测量时间缺失为 null 而非 0；旧 `long_term_container_can_enable`/blocked/remaining 字段仍在。

## 4. 手工设置、恢复入口与错误映射

- [ ] 4.1 重构 `services/container_tasks.set_long_term_container`：单 session 内 `FOR UPDATE`/写事务读取容器、长期标记、绑定与机器；同目标值直接返回且不写标记/审计/冻结表；实际启用调用评估器并条件插入；实际取消调用条件删除并重读 rowcount=0 的原因。验证：重复 true/false 返回成功、长期表与 operation_logs 均无新增、冻结三字段逐字节不变；并发 pausing 与取消时只允许一方提交，失败方返回具体 reason；成功只写一条审计。
- [ ] 4.2 扩展 `api/container_api.py` 的 `REASON_STATUS_MAP` 与 `set_long_term_container` 失败审计：`long_term_transition_unconfirmed`、`disk_limit_not_configured`、`disk_sample_untrusted`、`disk_usage_over_limit`、`long_term_state_changed` 映射 409；host offline/maintenance 沿用 503；`long_term_already_enabled`/`long_term_not_enabled` 不作为错误。验证：API 测试覆盖每个 reason 的状态码与 `error_reason`，失败审计含目标值/reason，长期标记不变；同目标 no-op 为 200；缺测量说明为测量未验证而非目录身份缺失。
- [ ] 4.3 恢复长期快照：按保留业务路径创建，`_ensure_restore_long_term_capacity` 只做 root 用户配额预检；实际恢复时在使容器可见的同一短事务内恢复长期标记并写一次 `restore_grace={until: now+grace_days, granted_at, deferral_seconds:0, source:"resurrect:<deleted_id>"}`，提交前调度不可见。`requires_choice`/取消/创建前失败不写；同一 source 复用原 until 不刷新。不检查旧 Docker/PID/dev/inode，不新增 Node preflight、确认框/token/临时短期或冻结行。验证：真实恢复原子可见、requires_choice 不耗宽限、同一 deleted_id 并发认领只有一份标记/宽限、重复请求不刷新、失败回滚且不报告完整成功、配额/路径/机器/image 错误沿用、手工新启用无宽限特例。
- [ ] 4.4 实现/复用 `effective_restore_grace_until(container)`：解析 `restore_grace`，按 `until + deferral_seconds` 计算；扩展现有机器不可用结算，只为 `window_start/end` 中晚于 `granted_at` 的部分增加 `restore_grace.deferral_seconds`，不套旧冻结累计。验证：无冻结行只靠容器行宽限；已有冻结行不创建新行/不清 `first_frozen_at`；授予前窗口不计、授予后窗口计；宽限到期后标准策略接管；解析缺失/非法不伪造宽限。
- [ ] 4.5 更新既有测试与 fixture，而不是删除测试：`test_container_tasks_long_term.py`、`test_container_api_long_term.py`、`test_restore_long_term_capacity.py`、`test/e2e/test_ctrl_user_machine_container_flow.py` 的在线容器补有效路径测量（`measurement_mount_path` 一致、真实 measured_at）；保留长期恢复成功、root 用户配额、普通快照、no-op 与幂等断言。验证：旧用例区分 quota/disk/status reason，恢复路径不查 inode，测试不靠旧身份门禁或放宽生产门禁通过。

## 5. 审计、冻结语义与联合回归

- [ ] 5.1 增加长期切换/恢复审计与冻结不变量测试：实际新增/删除标记写成功审计；失败写失败审计；no-op 不写；普通切换前后冻结三字段不变；恢复只写 `restore_grace`，不创建假冻结行、不清 `first_frozen_at`、不套旧 deferral；取消后遗留行不删除；动作 failed 不写容器 failed。验证：operation_logs、freeze 表与 `restore_grace` 前后快照断言。
- [ ] 5.2 用独立测试回放 Sylvan 事故与恢复宽限：长期+磁盘超限+paused 时取消返回 409；unpause 未确认仍拒绝；终态 online 后允许取消且冻结行/锚点/宽限/累计不变；pause failed+online 解除；手工新启用超硬阈值 409；恢复长期快照自动授一次宽限、requires_choice 不授、重复请求不刷新、宽限内不暂停/通知/升级、到期后按新实例测量标准处理。验证：隔离 SQLite+mock Node/WSS，不触达真实 Docker/生产 DB。
- [ ] 5.3 与依赖做混合版本验收：旧 Node 缺 measured_at/协议时启用 `disk_sample_untrusted`；gate 已部署/Node 未升级测量未验证；路径 unresolved 但同路径测量有效；旧 Node 无 action_ref 的 online/paused、同步失败、超时与 `pause_failed` 只 unconfirmed；新 Node 精确 failed/confirmed、同 ref 旧 accepted、早到 WSS、epoch/旧链路。验证：不启动生产服务，输出资格、动作绑定、恢复宽限与最终冻结状态；不检查 dev/inode。
- [ ] 5.4 编写部署/回滚说明：明确先 `gate-disk-check-on-mount-identity` Ctrl 测量/路径字段、再逐机 Node 路径/测量协议与 action_ref/last_action、然后本变更、最后 Web；包含旧样本/旧 Node 覆盖率、迁移重复执行、恢复路径/配额/标记/静默宽限、Q72 保留、回滚保留新列。验证：文档步骤隔离可执行，不把目录身份/旧 inode 写成恢复或长期门禁。
- [ ] 5.5 完成实现后的联合校验：运行 `openspec validate gate-disk-check-on-mount-identity --strict`、`openspec validate guard-long-term-container-transitions --strict`、`openspec validate unify-disk-freeze-workflow --strict` 与相关隔离安全测试；strict warning 逐条记录并确认为非致命，真实错误修复。验证：测试报告包含事故回放、pause failed+online、旧 Node、动作竞态、restore 宽限、quota、幂等、冻结不变量和 DTO 契约；不声称修复 Q67/Q70。

## Workflow follow-up

- 评审通过后按仓库流程 archive；archive 时把本变更两个 delta 的新增字段/要求合并进 `openspec/specs/backend--table-containers/spec.md` 与 `openspec/specs/backend--table-long-term-containers/spec.md`，否则主规格会滞后。
- 与 Web `align-container-action-eligibility-and-recovery`、Node `guard-runtime-state-reconciliation` 做跨仓库契约核对；本变更只负责 Ctrl change 目录，Node action_ref/last_action 由父代理同步实现。
- 恢复政策已决：恢复原长期资格执行相同硬超限规则，但实际恢复时静默授予一次宽限并恢复原长期标记；不再保留待决/确认框/临时短期路径。
- Q67 跨容器长期数量并发、Q70 跨进程动作代际、线上 Sylvan 行修复均不在本变更；action_ref 只用于 pause/unpause 局部关联，不得宣称为 Q70 删除身份。
