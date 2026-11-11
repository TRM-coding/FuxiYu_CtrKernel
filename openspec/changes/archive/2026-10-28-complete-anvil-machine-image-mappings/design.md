# Design

## Context

三张主规格分别位于 `openspec/specs/backend--table-images/spec.md`、`openspec/specs/backend--table-machine-image/spec.md` 和 `openspec/specs/backend--table-machines/spec.md`，合计 9 + 6 + 12 个 Requirement、13 + 11 + 22 个 Scenario。现有回归分布在 `test/image`、`test/machine`、`test/container`、`test/repository` 与 `test/test_entrypoint_docs.py`。

本 change 只做映射审计：主规格与运行行为不变，测试计划是 Scenario 到 test/check 的映射，不是执行结果台账。当前不维护 `openspec/specs/*/test-plan.md` sidecar，也不创建 review、tasks 或进行 apply。

## Goals / Non-Goals

**Goals:**

- 为 46 个既有 Scenario 建立完整的 Requirement → Scenario → Test/check → Assertion scope 映射。
- 只把已逐段核对测试代码和实际断言的既有用例标记为 `[X]`。
- 把真实缺口标记为 `[ ]`，并集中规划到 `test/repository/test_anvil_machine_images.py`。
- 将没有独立 Scenario 的 Requirement 正文约束挂到相关 Scenario，并明确其断言范围。
- 保持三份 delta 与主规格逐字一致，避免把测试解释写进主规格。

**Non-Goals:**

- 不改变任何业务行为、接口、数据模型、配置、依赖或数据库结构。
- 不修改应用代码、主规格、既有测试、共享 fixture、sidecar、CI 或 skills。
- 不修复审计中发现的规格/实现差异，不替父任务作业务决策。
- 不运行或部署真实 Docker 镜像，不连接真实 Node、SSH 或生产环境。
- 不创建 tasks、review、commit，也不在本阶段新增测试文件。

## Decisions

### D1: Delta 使用逐字完整的 MODIFIED no-op

每个 delta 只包含 `## MODIFIED Requirements`，Requirement 名称、正文、Scenario 名称、WHEN/THEN 与主规格逐字一致。这样官方 sync 不会改变主规格行为，同时保留本 change 对三个 capability 的明确引用。测试解释、locator、核对结论只写入 change 的 test-plan，不写入 spec delta。

### D2: `[X]` 以实际断言为准，不以文件存在或套件通过为准

每个 `[X]` locator 都在测试源码中找到同名测试，并核对其断言是否覆盖 Scenario THEN 或对应正文约束。只检查测试名称、只依据历史运行日志、或仅看到测试文件存在，都不构成 `[X]`。一个 Scenario 可以由多条既有断言合并覆盖；合并后的 Assertion scope 必须写出实际观察到的行为，不能把未覆盖部分藏在 `[X]` 后面。

### D3: 缺口集中到单一新测试文件

所有 `[ ]` 缺口都规划到 `test/repository/test_anvil_machine_images.py`。该文件可按三个 capability 分组，但只使用现有 `db_session`、`client`、`monkeypatch`、`tmp_path` 等 fixture，不新增或修改共享 fixture。测试设计使用真实 SQLite 行、真实服务/仓储代码与 FastAPI TestClient；Node 通信、TLS 取证、enrollment profile 等外部接缝使用替身，不 mock 被测的目标业务逻辑。

### D4: 失败路径只在真实可命中的写入边界注入

重钉持久化失败、窗口结算失败、`last_seen_at` 写失败等场景，优先用 SQLite 触发器制造真实写入失败，让生产事务路径自行回滚；只有外部通信边界使用替身。触发器必须绑定真实存在且会被更新的行与列，并保留无触发器的正常控制组，避免 0 行更新造成假阳性。派发确认使用与预留相同的 tag/version/fingerprint 时，CAS 不会命中任何行，属于同值幂等 no-op，不构造不会触发的失败触发器；预留写入失败另行覆盖“无法可靠记录派发”的失败 THEN。

### D5: 正文约束挂到同 Requirement 的既有 Scenario

Requirement 中没有独立 Scenario 的规范性句子，按其所属 Requirement 挂到最相关的一个或多个既有 Scenario，并在 Assertion scope 中逐项说明对应断言。例如 `images 生产职责与生命周期` 的 READY 建容器、详情/编辑权限与所有权不转移，分别由资源、状态门和归属断言承接；`machines 生产职责与生命周期` 的注册、端口、GPU 事实/许可和 WSS 更新挂到其唯一 Scenario。

### D6: 规格与实现差异只报告，不在本 change 解决

若审计发现规格文字与实现边界不一致，或某条正文约束没有可判定的测试出口，不修改主规格、不弱化断言、不把差异写成新业务决策；只在交付说明和外部审计日志中报告给父任务。

## Risks / Trade-offs

- 规划的新用例在 apply 前保持 `[ ]`；test-plan 只证明映射意图，不代表测试已创建或通过。
- Node 内部的后台构建结果不可由 Ctrl 观测；相关 Scenario 只能断言 Ctrl 侧的下发、预留与缓存行语义，并在 Coverage note 中显式限定边界。
- SQLite 触发器适合验证事务回滚，但属于 SQLite 方言；测试仍走真实服务与仓储代码，生产数据库差异由既有跨库约束说明承担。
- 缺口测试集中在单文件，便于审阅，但文件会同时覆盖三个 capability；以分组注释和测试名保持可定位性。
- 本次不运行真实 Node、Docker、SSH 或镜像部署，跨仓实际制品行为只能作为外部边界报告。
