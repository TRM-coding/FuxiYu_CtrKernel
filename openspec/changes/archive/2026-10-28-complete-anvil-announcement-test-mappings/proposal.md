# Proposal

## Why

三仓库 65 个主规格的 Anvil test-plan 维护工作里，Ctrl 第 2 批的 3 个公告能力现在只有零散、口径不一的覆盖台账：`backend--table-announcement-templates` 与 `backend--table-announcement-drafts` 的主规格旁 sidecar 还是旧表格格式，且模板侧把 3 个既有场景标成“待复核”；`backend--table-announcements` 的台账虽已是 canonical 结构，但仍存在把“文件存在”当成覆盖、以及若干 Requirement 明文约束（持久化读回的空值语义、排序后再分页、`target_snapshot` 快照、模板删除后的重发路径、历史纯文本统一渲染、发送路径不写回草稿/模板）没有对应断言的情况。结果是 review 与后续 apply 无法判断 23 个 Scenario 到底哪里真的有断言、哪里是缺口。

本变更只做规划补齐：把 23 个 Scenario 逐条对到真实测试断言上，把按既有规格能补的缺口写成计划项，并且不引入任何业务行为变更。

## What Changes

- 为 3 个公告能力共 23 个 Scenario 建立 canonical 映射：Requirement → Scenario → Test/check 嵌套勾选 → Assertion scope → 可选 Coverage note。
- 对既有测试做断言级复核（读取真实断言，而不是只确认 nodeid/文件存在），尽量复用；既有覆盖不得误报为缺口，sidecar 旧表与旧运行数字只作线索。
- 规划 10 个补测项，全部落在新文件 `test/announcement/test_anvil_announcement_mappings.py`，复用既有 `db_session` / `client` / factories / `inline_send_thread` 等夹具，不重构目录与 fixture，不新增反射 ORM 断言或源码字符串断言。
- 补测重点：跨 session 读回（含 `source_draft_id`）、模板详情初值、删除模板后的主题/目标/投递记录快照、非整数 `offset`、默认 100/0 与过滤 `total`/真实排序、`target_snapshot`、删除模板后的重发、纯文本/Markdown 同一 renderer 调用，以及发送/重发前后草稿与模板快照。
- 三个能力的 delta 只承载原 Requirement 块的逐字复制（MODIFIED），Requirement 内不加入本轮解释句；因此 sync 后主规格应无净业务与文本变更。本条只是让映射有可 review 的锚点，不构成行为变更。
- 不写 `review.md` 与 `tasks.md`，不改主规格、主 sidecar、既有测试与任何业务代码，等待独立 review。

## Capabilities

### New Capabilities

- 无。本变更不引入新的能力。

### Modified Capabilities

- `backend--table-announcement-drafts`：无行为变更。delta 逐字复制 2 个既有 Requirement（`announcement_drafts 持久化结构`、`announcement_drafts 生产职责与生命周期`）连同其 4 个 Scenario，仅作为 test-plan 映射锚点。
- `backend--table-announcement-templates`：无行为变更。delta 逐字复制 3 个既有 Requirement（`announcement_templates 持久化结构`、`announcement_templates 生产职责与生命周期`、`announcement_templates 列表分页参数有界且可分页`）连同其 6 个 Scenario。
- `backend--table-announcements`：无行为变更。delta 逐字复制 4 个既有 Requirement（`announcements 持久化结构`、`announcements 生产职责与生命周期`、`公告 Markdown 邮件渲染与双正文`、`公告 Markdown 渲染的内容与安全边界`）连同其 13 个 Scenario。

## Impact

- 规格与台账：新增 `openspec/changes/complete-anvil-announcement-test-mappings/` 下的 `proposal.md`、`design.md`、3 个 delta `spec.md`、`test-plan.md`。
- 代码与测试：本变更不修改任何业务代码、表结构、API、主规格或主 sidecar；后续 apply 若被批准，只会新增 1 个测试文件。
- 数据与依赖：无迁移、无新依赖、无配置或全局 defaultSchema 变更。
- 与并行批次的关系：Ctrl 第 1 批（`complete-anvil-rbac-test-mappings`，RBAC 关联表）与本变更文件集合不重叠，本变更不读写其目录。
