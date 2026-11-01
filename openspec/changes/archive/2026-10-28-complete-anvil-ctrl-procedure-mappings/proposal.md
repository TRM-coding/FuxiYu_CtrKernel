# Proposal

## Why

`procedure--repository-workflow`（16 个 Scenario）与 `procedure--testing-safety`（19 个 Scenario）已经在主规格固化流程契约，但两个 capability 都没有 test-plan sidecar；现有覆盖分散在 `scripts/ci/tests/test_check_pr.py`、`test/test_testing_safety_contract.py`、`test/conftest.py`、`test/utils/test_mail.py`、`test/test_mail.py` 与若干任务/API/repository 测试中，无法确认每个 Scenario 的断言边界、哪些只是配置或源码文本检查、哪些必须由人工步骤取证。本次只做 Anvil 测试对账，为 35 个 Scenario 建立可审计的映射与缺口计划。

## What Changes

- 为两个既有 capability 各写一份 spec delta，只含 `## MODIFIED Requirements`，逐字复制主规格的 8 + 7 个 Requirement 完整块（Requirement 名、SHALL 语义、Scenario 名、WHEN/THEN 原文不变），不复制 Purpose 与 Source references，不新增业务行为。
- 在 `design.md` 记录证据分级与取证方式：`[X]` 必须逐段读过真实断言；配置文本或源码字符串只作为配置事实，不冒充规则执行；真实行为测试只 mock 外部服务；程序性且无自动化对象的步骤用可复现 manual check 明确范围。
- 在 `test-plan.md` 按 `Requirement → Scenario → Test/check → Assertion scope → 可选 Coverage note` 完整枚举 35 个 Scenario；缺口统一规划到 `test/test_anvil_workflow_safety.py`（本步不创建）；不写运行结果。PR 正文“不执行正文”另规划一个真实 sentinel 行为用例（保持 `[ ]`），不把源码 token 扫描当作行为证据。
- 计划中的补测只在隔离环境执行：commit-msg / pre-commit 用临时 git 目录与真实 hook 脚本，不执行真实 commit；HTTP/SMTP 只触发既有守卫；不打开或解析真实 `.env` 以取得密钥，不读取 APIKEY/PASSCODE 值或生产数据库；不部署、不删除真实资源。
- 父级 `d97d6a7` 已移除本轮生成、仅重复 proposal 摘要的两个 README（1 活动 1 归档），原文备份在外部 `removed-generated-readmes.md`；当前三仓 `openspec/` 树内 README 文件名检查为 0，全 `openspec/` 规则可直接检查，不再有未解决冲突或新增 Global 问题。本 change 不重建 README、不重构文档树、不改主规格。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `procedure--repository-workflow`: Requirement 与 Scenario 语义不变；delta 以 MODIFIED 完整块纳入 8 个 Requirement、16 个 Scenario 的对账范围。
- `procedure--testing-safety`: Requirement 与 Scenario 语义不变；delta 以 MODIFIED 完整块纳入 7 个 Requirement、19 个 Scenario 的对账范围。

## Impact

- 规格：两份主规格在 sync/archive 后被以完全相同内容重写，不产生语义差异。
- 测试：拟补用例集中在 `test/test_anvil_workflow_safety.py`；既有 `scripts/ci/tests/test_check_pr.py`、`test/test_testing_safety_contract.py`、`test/test_safe_pytest_app.py`、`test/utils/test_mail.py`、`test/test_mail.py`、`test/operation_log/test_mail_audit.py`、`test/repository/test_authentications_repo.py` 等作为复用来源被引用；以上文件本步不修改。
- 业务代码、模型、迁移、依赖、DB、config、CI、skills、共享 fixture：无影响。
- 运行影响：无；本步只规划，不执行测试，不写 review/tasks，不写 sidecar，不改主规格。
