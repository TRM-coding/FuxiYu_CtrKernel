# Tasks

## 1. 静态守卫

- [ ] 1.1 在 `services/container_module/long_term.py` 增加按方向判断的长期切换守卫，先调用既有 `ensure_container_operation_allowed(..., "set_long_term")`，再按目标执行配额、磁盘或冻结取消规则；保持既有状态矩阵与权限入口不变。验证：单测覆盖启用/取消方向、`online/offline/paused/failed`、不稳定/主机/未知状态，断言原矩阵结论不变。
- [ ] 1.2 实现启用方向的配额检查：复用 root 用户计数与既有 `long_term_limit_reached` used/limit 文案，不新增表或查询来源。验证：配额已满拒绝且不写标记，配额未满继续磁盘判断，重复启用走 no-op。
- [ ] 1.3 实现启用方向的磁盘硬限制检查：只用 `container.disk_total_bytes`、`machine.max_disk_size_gb` 和 `get_container_disk_hard_limit_percent()`；用量未知、上限未配置、软阈值均不阻断，已知达到硬限制抛 `disk_usage_over_limit`。验证：参数化单测覆盖等于/高于/低于阈值、空用量、空上限、软阈值，断言不把未知当 0。
- [ ] 1.4 实现取消方向的冻结拦截：实际状态为 `paused` 时抛既有 `container_paused`；不查询、不删除 `container_disk_freeze_state` 行，`online`/`offline` 即使行仍在也允许。验证：冻结取消被拒且 Q72 三字段逐字节不变；在线/离线且遗留冻结行时允许取消。

## 2. 写入流程与错误契约

- [ ] 2.1 重构 `services/container_tasks.set_long_term_container` 为同一会话读取容器、绑定、长期标记和机器，再判断和写入；同目标值直接返回，不写长期表、不写成功审计、不触碰冻结字段。验证：重复 true/false 前后长期行数、成功审计数、冻结三字段不变；单会话重读后状态变化会重新判断。
- [ ] 2.2 让配额计数与写入使用同一会话，或抽出同语义的只读 helper；继续使用 `long_term_container_repo.add/remove` 原语，不新增条件写、行锁或跨容器配额机制。验证：同一容器并发切换只产生一条长期标记；测试不宣称 Q67/Q70 已修复。
- [ ] 2.3 在 `api/container_api.py` 的 `REASON_STATUS_MAP` 增加 `disk_usage_over_limit: 409`，失败审计记录实际 reason，长期标记不变；既有权限 403、不存在 404、入参 400、主机 503 保持。验证：API 测试覆盖新 reason、`long_term_limit_reached`、`container_paused`、主机原因与 no-op 200。

## 3. 回归与边界

- [ ] 3.1 增加 Sylvan 事故回放：长期容器 `paused` 时取消返回 409；实际恢复 `online` 后允许取消，遗留冻结行和 `first_frozen_at`/`grace_until`/`deferral_seconds` 不变；冻结字段不被重置（Q72 累计不清零）。验证：隔离 SQLite + mock，不触达真实 Docker/Node/生产库。
- [ ] 3.2 增加恢复长期快照回归：快照为长期时仍在 `Create_container` 前做 root 配额预检，成功后按既有 `_persist_long_term_state` 恢复标记；恢复宽限政策保留，但其承载缺口见 3.4，本变更不新增宽限存储或额外创建冻结行。验证：现有恢复配额/幂等/普通快照用例通过，测试中 `container_disk_freeze_state` 行数不因恢复长期标记而增加。
- [ ] 3.3 增加边界测试：用量未知/上限未配置不误拒；已知硬超限拒绝；`failed`/不稳定/主机离线/维护/状态未知仍按原矩阵拒绝；`paused` 下启用仍按原矩阵允许（本次只禁止冻结时取消）。验证：单测逐项断言原因与状态码，并记录这是静态现有数据判断。
- [ ] 3.4 记录恢复宽限的表示缺口：在变更文档或交付说明中引用现有冻结仓储只对已有冻结行 `set_grace`、`first_frozen_at` 非空的事实，说明无冻结行时无法在不伪造冻结行、不新增结构的前提下表达恢复宽限；不改代码、不新增字段。验证：交付说明含具体源码位置与原文，且本变更任务不把该缺口当成静态守卫前置。

## 4. 验证

- [ ] 4.1 运行定向长期/恢复/磁盘测试与 `openspec validate guard-long-term-container-transitions --strict`，确认 strict 无错误。验证：命令输出与测试结果留档。
- [ ] 4.2 运行 `git diff --check`，并检查变更只涉及长期守卫相关服务/API/测试与 change 文档；确认没有新增模型、数据库结构或响应模型改动，没有新增资格对象或 Node 字段。验证：`git status`、`git diff --stat` 与源码检索结果一致。
- [ ] 4.3 与 Web 变更核对：Web 只使用既有 `is_long_term`、`long_term_container_can_enable`、磁盘百分比和 `effective_status`，不依赖新增响应字段；后端 409/403 仍是最终裁决。验证：跨仓字段清单对照，无新增字段/API。

## Workflow follow-up

- 评审通过后按仓库流程归档，把本 delta 合并进 `backend--table-long-term-containers` 主规格。
- 恢复宽限的承载缺口单列于 Global `QUESTIONS.md` 的 Q74；在另行决策前不添加新列、不伪造冻结行，也不宣称恢复宽限已完成。
- Web 变更使用既有字段独立上线；本变更不修改 Node、Web、正式 `openspec/specs/` 或 archive。
