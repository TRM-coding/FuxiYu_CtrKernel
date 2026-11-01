# Tasks

## 1. Hook 契约测试

- [x] 1.1 在 `test/test_anvil_workflow_safety.py` 实现 commit-msg 三条用例：合规/空行注释、MERGE_HEAD 豁免、署名尾注逐行列出。覆盖 `procedure--repository-workflow` 的「提交信息条目格式」三个 Scenario；用临时 `git init` 目录和真实 `githooks/commit-msg` 验证，不执行 commit。
- [x] 1.2 在 `test/test_anvil_workflow_safety.py` 实现 pre-commit 两条用例：叠加前缀拒绝、缺前缀拒绝且合规前缀通过。覆盖「能力命名与粒度」的「叠加前缀被拒」「缺前缀被拒」；用 `git hash-object` + `git update-index --cacheinfo` 暂存，不 commit。

## 2. 测试安全与流程测试

- [x] 2.1 在 `test/test_anvil_workflow_safety.py` 实现默认安全套件/配置/隔离用例：`test_default_suite_deselects_integration_and_legacy_probes`、`test_safe_config_uses_exact_in_memory_sqlite`、`test_create_app_overrides_clear_mysql_engine_options_and_ignore_flask_config`、`test_assert_sqlite_database_uri_rejects_non_sqlite`。覆盖「安全默认命令」「测试配置注入」「非 SQLite 隔离被拒」；collect 探针用最小子环境、`sitecustomize` 禁 socket、`tmp_path`，不导入应用。
- [x] 2.2 在 `test/test_anvil_workflow_safety.py` 实现 HTTP/SMTP 用例：`test_pinned_adapter_http_path_is_blocked_before_network`、`test_real_smtp_ssl_is_blocked_by_default`、`test_mail_send_uses_local_success_stub_without_smtp`、`test_mail_send_batch_uses_local_success_stub_without_smtp`。覆盖「真实 HTTP 被拦截」「真实 SMTP 被拦截」；只触发 conftest 守卫，不发真实请求。
- [x] 2.3 在 `test/test_anvil_workflow_safety.py` 实现 harness/邮件/替换覆盖/旧文档用例：`test_integration_marker_bypasses_external_stubs`、`test_ensure_auth_users_builds_rows_on_test_sqlite`、`test_legacy_replacement_paths_exist`、`test_retired_testing_docs_are_not_restored`。覆盖「集成用例豁免替身」「约束与隔离 fixture 可直接构造」「旧测试删除名单与替换覆盖」「替换覆盖存在」「不恢复旧文档」；integration 用例自身标 marker、不请求 app/db_session、不发网络。
- [x] 2.4 在 `test/test_anvil_workflow_safety.py` 实现 `test_check_pr_does_not_execute_body_sentinel`：正文放会写 sentinel 的 Python payload，断言 `check_pr.main` 返回 0、stdout 含“通过”、sentinel 不存在。覆盖「校验实现与其边界」的“不执行正文”；保持真实行为断言，不用源码 token 扫描替代。

## 3. 执行与验证

- [x] 3.1 用 WSL fuxi Python 安全环境运行 `test/test_anvil_workflow_safety.py` 默认套件，确认全部非 integration 新增测试通过；记录 raw/exit 到外部 `ctrl-batch-7`。
- [x] 3.2 单独精准运行 `test/test_anvil_workflow_safety.py::test_integration_marker_bypasses_external_stubs`（显式 `-m integration`），确认无真实网络并记录 raw/exit。
- [x] 3.3 运行相关流程/CI checker 套件：`scripts/ci/tests/test_check_pr.py` 与 `test/test_testing_safety_contract.py`，确认通过并记录 raw/exit；不跑全 Ctrl。
- [x] 3.4 保持 README 规则为映射/文件名检查：运行 `git ls-files -- ':(glob)openspec/**/README*'` 与文件系统 README 文件名枚举，期望为空；不读取 README 内容、不重建 README。
- [x] 3.5 运行官方 `openspec-verify-change` advisory；不创建 `verify.md`，记录结论与限制。

## Workflow follow-up

- 精准 no-op sync 两份主规格，保持 27 个主规格 SHA 不变；确认无内容差异。
- 用 `anvil-test-plan` 更新 `procedure--repository-workflow` 与 `procedure--testing-safety` 两个主侧车，机械状态与 change test-plan 一致；保留未验证 manual 的 `[ ]`，不写运行 ledger。
- 按 2026-10-28 归档 change；不 commit/push，父级负责 Git。
