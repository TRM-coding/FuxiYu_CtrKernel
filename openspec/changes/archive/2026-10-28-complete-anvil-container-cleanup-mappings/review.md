# Plan Review

## Review Record

- Change: complete-anvil-container-cleanup-mappings（作者 e8dbd2a3；本次复审未改动作者计划）
- Context: 官方 fallback 后的同一独立复审；上一轮 quota 中断无可用产物，本轮从实际 plan 重新核对，未复用中断结论。作者已按上一轮 5 个 Blocking 与 Non-blocking 整改。
- Reviewer: fresh-context reviewer（独立于作者上下文；只读审查）
- Access: read-only；本文件是唯一写入
- Reviewed plan: proposal.md、specs/**/spec.md（4 份）、design.md、test-plan.md；主规格、现有测试与相关源码仅作只读核对
- Counts verified: 35 Requirement / 94 Scenario；test-plan 共 267 条映射（215 个 `[X]`、52 个 `[ ]`），46 个唯一 pending 测试函数；4 份 delta 的 35 个 Requirement 块与主规格逐字一致；所有 `[X]` 定位的测试文件与函数名均存在。未运行 tests/build，未据此宣称任何测试通过。
- Invalidation scope: Requirement、Scenario、设计决定、场景映射、Test/check locator、Assertion scope 或 Coverage note 的任何语义变更都会使本审查失效。仅在实际断言不变时重算复选框，或仅有外部运行/日志变化，不会使本审查失效。
- Scope limit: 仅审查计划；实现、任务完成、测试执行与归档就绪不属于本审查范围。
- Plan status: 52 个 `[ ]` 是待实现的规划缺口，不以“计划测试尚不存在”判错；本 review 只核对映射与 Assertion scope，不声称任何测试已通过。

## Findings

### Blocking

None.

### Non-blocking

- **design.md:65-66 仍称 Q81/Q82 “冲突未决”，与父已核对的定性不一致。** 父已源码核对并登记 Global：Q81 已有 model/appendix 确定按 `container + recipient`，Q82 已有请求 schema 与非法请求 Scenario 确定 400、记录缺信息才 `not_found`；它们是规格误述，不需要新的业务/表结构决定，也不改返回。test-plan 已正确保留“原错误 clause 未覆盖/暂缓”的限制；请把 design 的“未决”改为“已核实为规格误述/无需业务决策，保留未覆盖限制”，不要重新要求决定。该修改只是措辞对齐，不改 app、主规格或业务契约。
- **`仅实体通配被资源层拒绝` 的无密码/无 Node 仍依赖 C18 的“拒绝分支”，但 C18 的 Assertion scope 只描述了放行。** test-plan.md:459 写“由 C18 的拒绝分支一并覆盖”，C18 的 Coverage note（test-plan.md:453）也提到拒绝分支，但 C18 的 Assertion scope（test-plan.md:452）只写 `container:manage`/`bypass_resource` 放行。请把 `bypass_auth_entity` 的 403、无密码、无 Node 明确写进 C18 的 Assertion scope（或把该分支并入 C35），使该 Scenario 的 THEN 有具体断言归属；不新增业务行为。
- **R01 的“唯一约束”需要写明是 `(container_id, recipient_email)`，避免重新把 Q81 的错误 clause 当成待验证目标。** test-plan.md:790 只写“未直接触发唯一约束；R01 补齐”，而 Q81 已明确按收件人；请在 R01 的 Assertion scope 中点明触发的是既有 `(container_id, recipient_email)` 唯一键，并继续把“每个 container_id 只有一条”标为未覆盖/暂缓。这样不会改变 Q81 的父决策，也不会要求新表结构。
- **Q74 Coverage note 的附加 effective_status 引用只有文件级定位。** test-plan.md:38 已给出 6 组 Q74 的真实 `test_long_term_transitions.py` 定位；同一 note 中的 `test/container/test_container_effective_status.py` 仍只是文件名。为保持可审计性，请补该文件的具体测试名（例如本计划其他行已使用的 `test_status_unknown_when_machine_collect_error`），不改变覆盖范围。

## Verdict

VERDICT: APPROVE
