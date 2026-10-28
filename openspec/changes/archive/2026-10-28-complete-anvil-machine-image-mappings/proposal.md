# Proposal

## Why

三张主规格共 46 个 Scenario，既有断言分散在 image、machine、container、repository 等多个测试目录；仅凭套件通过数无法证明每个 Scenario 的 THEN 与 Requirement 正文约束都有可核对的测试映射。本 change 只做逐段核对与缺口规划，不改变运行行为。

## What Changes

- 对 `backend--table-images`、`backend--table-machine-image`、`backend--table-machines` 的既有 Requirement 逐字复制为 MODIFIED no-op delta，保持主规格语义不变。
- 建立 46 个 Scenario 到既有 test/check 的映射；只有实际读过测试断言并核对范围内行为后才标记 `[X]`。
- 对没有既有断言覆盖的真实缺口使用 `[ ]`，集中规划到新测试文件 `test/repository/test_anvil_machine_images.py`。
- 把没有独立 Scenario 的 Requirement 正文约束挂到同一 Requirement 的相关 Scenario 的 Assertion scope 中。
- 不修改应用代码、主规格、既有测试、共享 fixture、依赖、配置、数据库、CI 或 skills；本阶段不创建 tasks、review、sidecar，不提交 Git。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-images`: 规格行为不变；以 13 个既有 Scenario 的 no-op MODIFIED 承载全量映射。
- `backend--table-machine-image`: 规格行为不变；以 11 个既有 Scenario 的 no-op MODIFIED 承载全量映射。
- `backend--table-machines`: 规格行为不变；以 22 个既有 Scenario 的 no-op MODIFIED 承载全量映射。

## Impact

- 规划期仅新增本 change 的 proposal、design、spec delta 与 test plan。
- Apply 期只新增 `test/repository/test_anvil_machine_images.py`；测试使用 SQLite、FastAPI TestClient 和外部通信替身，不部署镜像，不访问真实 Node、Docker、SSH 或生产数据库。
- 无 API、数据模型、配置、依赖或运行时行为变化。
