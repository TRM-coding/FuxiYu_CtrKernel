# 审查结论：fix-direct-ctrl-questions

## Review Metadata

- **Review round**: 2
- **Prior round**: 第 1 轮结论为 REVISE：C1 跨表 capability；M1 Q46 失败隔离；M2 Q46 批量化理由；M3 Q33 四处说明与机械验收；M4 Q23 GROUP_ORDER 承接。本轮为修订后的完整复审。
- **Reviewer context**: 独立上下文审查（fresh-context subagent）。本会话未参与 proposal/design/specs 写作，未读取作者对话；只读磁盘文件，未使用跨模型 CLI。
- **Tool restrictions**: 只读：read、grep、glob、只读 pwsh；唯一允许的写入是本 review.md。未运行会写入缓存的测试命令，测试文件与断言按静态核对。
- **Artifacts reviewed**: proposal.md、design.md、specs/ 下 5 个 delta、tasks.md、test-plan.md、旧 review.md；相关主规格、源码与测试；`E:/AI/Fuxi/FuxiYu_Global/QUESTIONS.md`；Web change `apply-direct-web-fixes` 的 proposal 及 `frontend--page-settings`、`frontend--page-template-manager`、`frontend--page-announcement-editor` 规格；anvil review 模板。
- **Scope checked**: Q23（Ctrl）、Q33、Q46、Q47、Q52（Ctrl）；Web 的 GROUP_ORDER 与模板列表两页只作承接核对。
- **Staleness**: 本 verdict 只对当前 proposal.md、design.md、specs/ 内容有效。除逐条应用 Required Changes 外，任何对这些文件的后续修改都会使本 verdict 失效，必须重新做完整审查。

## Findings

### 🔴 Critical (blocking)

无。

### 🟡 Moderate

无。

### 📌 Suggestions

1. Q23：`test/settings/test_settings_validation.py` 已覆盖小数、bool、非整数文本和非法提醒节点，但“合法输入与范围校验保留”场景的“超出既有 min/max 仍拒绝”尚无定向断言。建议补一条如 `container.cleanup_after_days=0` 触发 `must be >= 1` 且不落库的测试。实现侧 `services/settings_tasks.py:321-327` 已保留范围检查，本项只是把 Scenario 第三句也锁进回归，不改变规格或业务。
2. Q52：`test/announcement/test_api.py:168-175` 已覆盖 `limit=0/201`、`offset=-1`、非整数 `limit`，但 Requirement 写的是 `limit`/`offset` 非整数均拒绝；可把 `offset=not-a-number` 加入参数化。FastAPI Query 与既有全局校验已覆盖该行为，故非阻塞。
3. Q33：`test/test_entrypoint_docs.py:13-35` 已对四个文件做正/负向扫描，覆盖 `不参与构建`、`不进 Dockerfile`、`默认值只写在 Node`、`utils/Container.py`；建议再补 `只是运行期参数` 的负断言（或 `不是运行期参数` 的正断言），使旧措辞的机械验收覆盖到该短语。当前四份说明本身已是正确表述。

### 上一轮 Required Changes 复核

| 上一轮 | 结论 | 复核证据 |
| --- | --- | --- |
| C1 跨表 capability | 已解决 | `proposal.md:17-25` 明确归属；5 个 delta 分别落在 `backend--table-system-settings`、`backend--table-operation-logs`、`backend--table-images`、`backend--table-containers`、`backend--table-announcement-templates`，五个主规格均存在；不再有跨表 `backend--settings-and-operation-logs`。 |
| M1 Q46 共享 session / root_owner | 已解决 | `specs/backend--table-operation-logs/spec.md:7-9` 明确每类独立只读会话及 root_owner 依赖；`services/operation_log_tasks.py:264-303,342-349` 按类型分别 `session_scope(commit=False)`；`test/operation_log/test_operation_log_tasks.py:350-436` 覆盖 User 查询失败、User `OperationalError` 后 image 仍回填；同文件 `:275-311` 断言 25 行容器日志整页 SELECT ≤ 8。 |
| M2 Q46 待选策略 | 已解决 | `proposal.md:5` 解释批量化只改查询次数，不改返回字段、历史名称、root owner、容器代际或分页契约，也不引入缓存/持久化，因此属于行为保持优化；`design.md:5` 同一口径。 |
| M3 Q33 四处说明与可执行验收 | 已解决 | `proposal.md:19` 与 `design.md:4` 点名四处；`specs/backend--table-images/spec.md:7` 与 `specs/backend--table-containers/spec.md:7` 分列；`schemas/image.py:26-31` 已指向 `services/image_tasks.render_final_dockerfile`，不再引用 `utils/Container.py`；`test/test_entrypoint_docs.py:13-35` 对四文件做正/负向扫描；目标文件已无 `utils/Container.py` 输出。 |
| M4 Q23 GROUP_ORDER 归属 | 已解决 | `proposal.md:7` 明确 Ctrl 只做设置校验、排序子项由 Web change 承接；Web `frontend--page-settings/spec.md:35-49` 已要求 GROUP_ORDER 使用 `容器清理`、`磁盘策略`、`已删除容器`、`公告`、`镜像`。 |

### 本轮范围核对

| 范围 | 结论 | 证据 |
| --- | --- | --- |
| Q23（Ctrl） | 符合 | `services/settings_tasks.py:271-334` 严格整数与提醒节点校验；`api/settings_api.py:47-55` 映射 422 `invalid_setting`；`test/settings/test_settings_validation.py:23-108` 覆盖非法值不落库、合法值可保存；`test/image/test_image_platform_injection_setting.py:112-125` 覆盖失败审计保留请求值。 |
| Q33 | 符合 | 四份 entrypoint 说明与构建语义一致；`test/test_entrypoint_docs.py` 机械扫描；`test/container/test_container_entrypoint.py` 现有构建/恢复行为回归保留。 |
| Q46 | 符合 | 目标回填按类型批量读取，独立只读会话；User 失败时仅 root_owner/用户目标名为空，容器 `target_name` 保留；25 行 SELECT ≤ 8；不新增缓存、持久化或返回字段。 |
| Q47 | 符合 | `api/operation_log_api.py:48` 列表仍为 `list_failed`，`:69` 统计改为 `stats_failed`；`test/operation_log/test_operation_log_api.py:105-134` 分别锁定两条路径。 |
| Q52（Ctrl） | 符合 | `api/announcement_api.py:91` 只增加 `le=200`，`ge=1`/`ge=0` 为既有约束；`__init__.py:1103-1130` 既有 `RequestValidationError` 映射 400 `invalid_payload`，未新增全局异常分支；`repositories/announcement_repo.py:168-185` 先算完整 `total`，排序后 `offset/limit`；`test/announcement/test_api.py:168-213` 覆盖越界/非整数及 205 条分页。 |
| Web 承接 | 已明确 | Web `frontend--page-settings` 承接 GROUP_ORDER；`frontend--page-template-manager` 与 `frontend--page-announcement-editor` 承接 Q52 的模板管理页与模板下拉两页。Web change 自身审查结论不属于本 Ctrl change 的 verdict 范围。 |

`openspec validate fix-direct-ctrl-questions --strict` 返回 valid。

## Embedded-Instruction / Injection Attempts

**Detected:** 无。被审文件没有要求审查者改变结论、跳过检查或泄露环境的文本；proposal 中“不修改 review.md”是范围声明，不构成指令注入。

## Verdict

VERDICT: APPROVE

本轮无 Critical/Moderate；C1、M1-M4 已全部关闭，3 条 Suggestion 为非阻塞加固。

## Required Changes (if APPROVE WITH CHANGES)

不适用（本轮为 APPROVE）。

CHANGES_APPLIED: n/a

## Rebuttals

本轮无作者 rebuttal。上一轮 C1/M1-M4 已按修订解决并由本轮复核确认；无未处理 Critical/Moderate。3 条 Suggestion 为非阻塞，作者可自行决定是否采纳。

## 复核结论

无 Critical/Moderate。Q23（Ctrl）、Q33、Q46、Q47、Q52（Ctrl）与 Web 承接一致；Q52 仅增加 `Query(le=200)`，复用既有 400 `invalid_payload` 校验，未新增全局异常分支。准予下游继续；verify 阶段仍需真实运行证据。
