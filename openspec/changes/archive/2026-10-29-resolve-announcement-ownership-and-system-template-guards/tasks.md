# Tasks

## 1. 归属模型与产品代码收口

- [x] 1.1 从 `Announcement`/`AnnouncementTemplate` 删除 `created_by` 列、用户外键与 `creator` 关系，草稿 `created_by` 外键改为 `ON DELETE CASCADE`；同步删除 repo 创建/列表参数与谓词、API公告/模板出参、service 草稿快照作者复制及转模板创建者参数，保留草稿私有归属。验证：模型元数据无两公告类创建者列/关系，`rg` 无公告/模板资源 `created_by`/`creator` 运行引用。对应 `backend--table-announcements`/`announcements 持久化结构`、`公告发送与复用不依赖创建者归属`；`backend--table-announcement-templates`/`announcement_templates 持久化结构`；`backend--table-announcement-drafts`/`announcement_drafts 持久化结构`。
- [x] 1.2 在 `announcement_repo.update_template` 写入前判断 SYSTEM 类别变更：其他 category 抛固定错误且不修改任何字段；API 映射 400 `cannot_change_system_template_category`，省略/null/same/custom→system 保持既有允许语义。验证：仓储直调与 HTTP 请求均可观察固定原因，多字段拒绝后数据库逐字段未变。对应 `backend--table-announcement-templates`/`SYSTEM 模板类别不可变更` 的全部 Scenario。

## 2. MySQL/MariaDB 显式迁移

- [x] 2.1 新增 `migrations/migrate_announcement_ownership.py`，提供 `migrate(url)` 与 `--url` CLI；执行任何 DDL 前拒绝非 MySQL/MariaDB；用 Inspector 发现真实外键名，校验约束恰为 `[created_by] -> users.[id]`，非预期复合/错误 target 或多约束在 DDL 前抛 `MigrationError`；删除公告/模板创建者外键与列，将草稿创建者外键收敛为 `ON DELETE CASCADE`，幂等且只改归属列。验证：模块可导入、非 MySQL dialect 与异常元数据均在 DDL 前报错、静态代码审查无启动路径 import/调用。对应 `backend--table-announcements`/`公告归属旧库迁移`。
- [x] 2.2 迁移维护说明保留在现有 OpenSpec design 与脚本 docstring（停止旧 Ctrl→备份→运行 CLI→核对→启新代码；MySQL/MariaDB 限定、不可逆删列、回滚需备份、普通启动不自动迁移）；按用户要求不新增 `migrations/*.md`。验证：design/docstring 含实际 CLI 与维护窗口顺序，目录中无该迁移 MD，未新增自动启动入口。
- [x] 2.3 新增迁移纯单元测试：fake Inspector 自动/显式外键名选择、MySQL DDL 使用真实发现名称、非预期复合/错误 target/多 FK 拒绝、实际 `migrate(url)` 对 SQLite 在任何 DDL 前拒绝且 schema 不变；不连接外部 MySQL，不把静态检查冒充真实迁移。验证：迁移规划测试通过，非 MySQL 拒绝不建表/不改列。对应 `backend--table-announcements`/`公告归属旧库迁移`/`旧约束名可发现且迁移幂等` 的单元边界。
- [x] 2.4 修订现有公告/模板测试与新增归属契约测试：删除旧 `created_by` 构造/出参；覆盖删作者后公告重发、模板分页/字段保留、批量发送与重发标题/原文/目标/来源、复制草稿归属当前操作员、转模板无创建者。验证：相关定向测试通过，27 Scenario 对应断言可得。对应 `backend--table-announcements` 与 `backend--table-announcement-templates` 的持久化/生命周期/发送复用 Scenario。
- [x] 2.5 修订草稿/用户测试：新建 SQLite 真实 FK/CASCADE 与 PRAGMA 检查；删除作者时认证记录、目标用户草稿消失，其他用户草稿/公告/模板保留；级联后回滚全恢复；用 spy 断言未调用 `delete_draft`；补草稿列表 `created_by`、SYSTEM 的 omitted/null/same/custom→system 参数。验证：`test/announcement/test_draft_ownership.py`、`test/announcement/test_system_template_category_guard.py`、`test/user/*` 定向通过。对应 `backend--table-announcement-drafts`/`用户删除级联所属草稿` 与 `backend--table-users`/`用户删除原子清理所属草稿` 全部 Scenario。

## 3. 安全测试执行

- [x] 3.1 用 `/home/chest/miniconda3/envs/fuxi/bin/python` + 安全 wrapper 运行受影响安全测试，设置 `DATABASE_URL=sqlite:///:memory:`、`DISABLE_BACKGROUND_TASKS=1`、`CTRL_WSS_ENABLED=0`；原始日志写入 `E:/AI/Fuxi_audit_artifacts/q68-q51-20261029/ctrl/`。验证：公告、草稿、模板、用户/API 受影响测试退出码 0，无真实 MySQL/邮件/Node 调用。
- [x] 3.2 运行 `openspec validate --strict` 与工作区范围检查，确认仅改本 change、模型/repo/API/service/迁移/测试/部署说明，未改主规格/Global/Node/Web/CI/config/skills。验证：valid=true，git status 仅本范围预期文件。

## 4. 外部真实 MySQL 验收（root 执行）

- [x] 4.1 由 root 运行已有外部 harness `check_mysql_migration.py`，真实比对自动/显式外键名、两次迁移、全文数据、无作者插入、user3 回滚与 user1 提交；本会话不调用、不重置实例。验证：root 在新增 FK 元数据校验后已重跑最终脚本，`mysql-migration-acceptance.json` 更新且 `mtime` 晚于迁移脚本；报告覆盖两 schema、两次迁移、全文保留、无作者插入、cascade/rollback。对应 `backend--table-announcements`/`公告归属旧库迁移` 的两个数据/迁移 Scenario。
