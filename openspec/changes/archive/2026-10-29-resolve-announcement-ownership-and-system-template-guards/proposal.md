# Proposal

## Why

公告与公告模板仍以 `created_by` 同时承担“创建者追溯”和用户删除外键；Web 从未消费该字段，因此它当前只剩历史追溯用途，却会在用户注销时成为外键阻塞，也让已经不再按作者隔离的资源保留了错误的所有权面。公告模板则允许把现有 SYSTEM 模板改成其他类别，破坏系统模板只读类别边界。与此同时，草稿确实需要私有归属，必须保留其创建者隔离并在用户删除时随用户同步清理。

## What Changes

- BREAKING：从 `Announcement` 与 `AnnouncementTemplate` 删除 `created_by` 列、指向 `users.id` 的外键、`creator` 关系；不在模型、仓储、API 出参或服务中继续读写这两类资源的创建者。
- 保留 `AnnouncementDraft.created_by` 及其私有隔离语义；草稿的创建者外键改为 `ON DELETE CASCADE`，使目标用户删除成功时，其所属草稿在同一最终事务内由数据库级联删除。删除失败时整体回滚；其他用户草稿、公告和公告模板均保留。
- 公告创建、批量发送、重发、公告转草稿和公告转模板继续保留正文与目标内容；转草稿仍以当前操作员作为新草稿的 `created_by`，转模板不再要求或写出创建者。
- 更新公告模板时，若当前模板为 SYSTEM：省略 `category` 或传入 `system` 允许编辑其他内容；传入任何其他类别则拒绝，返回 HTTP 400，`error_reason=cannot_change_system_template_category`，且同一请求中的其他字段不得部分落库。CUSTOM 改为 SYSTEM 保留现有行为。
- 新增仅面向 MySQL/MariaDB 的显式迁移，先发现实际外键名，再幂等删除公告/模板的创建者列与外键、将草稿创建者外键收敛为 `ON DELETE CASCADE`。迁移只删除归属列，不重建或清空正文、目标、状态、时间等既有数据；其他 dialect 必须在执行任何 DDL 前拒绝。
- 部署顺序固定为“停止旧 Ctrl → 备份 → 执行迁移 → 再发布新代码”；普通应用启动路径不自动删除 `announcements.created_by` 或 `announcement_templates.created_by` 列。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-announcements`: 公告不再持久化或暴露创建者，正文、目标与投递记录独立保留。
- `backend--table-announcement-templates`: 模板不再持久化或暴露创建者；SYSTEM 模板的类别不可改为其他类别，其他内容仍可编辑。
- `backend--table-announcement-drafts`: 草稿继续按 `created_by` 私有隔离，并新增用户删除时的数据库级联与事务回滚契约。
- `backend--table-users`: 用户最终删除事务级联删除其所属草稿时，保持认证记录、其他用户草稿及公告/模板内容的原子性边界。

## Impact

- 代码：`models/announcement.py`、`repositories/announcement_repo.py`、`api/announcement_api.py`、`services/announcement_tasks.py`、`services/user_tasks.py`（复用既有最终事务，无新增删除旁路）及公告/用户测试。
- 数据库：新增仅支持 MySQL/MariaDB 的显式迁移入口；MySQL 旧库需先迁移，SQLite 新库由模型建立真实外键与级联，不构建跨方言 SQLite 迁移框架。
- 验证：默认 SQLite 安全套件不连接外部 MySQL；旧库迁移由 root 已有的独立 MySQL 8.0.46 验收 harness `check_mysql_migration.py` 真实验证重复执行、全文数据保留、自动/显式外键名、级联与 DML 回滚。生产 MySQL 尚未执行，不能宣称已部署。
- API：公告与模板响应移除 `created_by`；模板更新新增 400 `cannot_change_system_template_category` 拒绝分支。
- 依赖与范围：不新增依赖、表、无关列或状态；不改 Node、Web、Global、CI、config、skills。本计划阶段不修改主规格；apply/sync/archive 阶段按 design 的附录同步计划只更新三处数据附录（删除公告/模板各一列、草稿外键改 CASCADE），不提前改主规格；不执行 commit/push。
