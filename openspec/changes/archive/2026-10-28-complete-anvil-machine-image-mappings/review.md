# Plan Review

## Review Record

- Change: complete-anvil-machine-image-mappings
- Reviewed revision: 当前工作区（HEAD 4c3eeaf + 作者本轮未提交的 design.md/test-plan.md 修改；本 review 只审当前内容）
- Reviewer: fresh-context reviewer（独立复审；未参与作者规划）
- Access: read-only；本文件是唯一写入。另只读主规格、相关源码与既有测试，用于 locator 与可行性核对。
- Reviewed plan: proposal.md、specs/**/spec.md、design.md、test-plan.md。delta 仍与主规格逐字一致（仅空行差异），no-op 成立；46 Scenario、173 `[X]`、19 `[ ]`，且 19 个 `[ ]` 均集中于 `test/repository/test_anvil_machine_images.py`。该文件当前不存在，符合“测试尚未实现”的状态，不构成计划错误。
- Re-check: 前次两条 Blocking 已定点修复：确认失败用例改为同值 CAS 幂等 no-op，并明确不构造不会触发的 `BEFORE UPDATE`；预留失败由 `BEFORE INSERT ON machine_image` 覆盖“解析失败、Node 不被调用、无缓存行”；窗口失败触发器已改为真实 `container_ssh_login_records`，写明已存在 SSH 行、`delta>0`、`UPDATE OF deferral_seconds` 和原正常控制组。前次 metadata scope 措辞也已收窄。
- Parent records: Q79（`machine_ip` 纯 IPv4 表述与实现只拒冒号的差异）和 Q80/Global6392692（pin 文件写失败策略未定义）已由父任务登记；计划只保留限制说明，不新增业务、原子事务或新表，本轮不因此阻塞。
- Invalidation scope: 任何对 requirement、scenario、design decision、scenario mapping、test/check locator、Assertion scope 或 Coverage note 的语义修改都会使本 verdict 失效。仅在核对未变断言后重算 checkbox，或外部运行/日志变化，不使本 review 失效。
- Scope limit: planning only。实现、tasks、测试执行与 archive readiness 不在范围内；未运行测试套件。本阶段不要求 `[ ]` 测试已实现，只审 mapping 与其可实现性。

## Findings

### Blocking

None.

### Non-blocking

- `test-plan.md:449`（last_seen 写失败）：实施时需先清空 `snapshots._last_seen_written`（或使用未被 60s 节流的机器）并断言 warning。否则模块级节流可能直接跳过 `touch_last_seen`，`BEFORE UPDATE OF last_seen_at ON machines` 触发器不会触发；这不影响计划映射，现有 `TestLastSeenHeartbeat` 与正常控制组已覆盖同一路径。
- `test-plan.md:221`（reservation INSERT 失败）：测试应走 API/`Create_container` 路径并配 Node send spy 断言“Node 不被调用”，不要只调用 `resolve_image_build`；否则该断言没有实际区分力。计划的 scope 已要求 Node 不被调用与无缓存行，实施时按此落点即可。
- `test-plan.md:424`（窗口失败）：除已写明的 SSH 行与 `delta>0` 外，实施时把机器前置状态设为非 ONLINE（如 OFFLINE），再触发恢复；这样“机器状态未部分更新”才是可观测断言。计划已给出 `BEFORE UPDATE OF deferral_seconds` 和 `test_offline_window_adds_deferral_on_recovery` 正常控制组，属于实施细节，不阻塞。

## Verdict

VERDICT: APPROVE
