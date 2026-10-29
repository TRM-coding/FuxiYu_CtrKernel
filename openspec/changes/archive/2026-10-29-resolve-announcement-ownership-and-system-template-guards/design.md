# Design

## Context

- `models/announcement.py` 当前把 `Announcement`、`AnnouncementTemplate`、`AnnouncementDraft` 都声明为 `created_by` 非空外键并挂 `creator` 关系；公告和模板的创建者只用于历史追溯，Web 从未消费该字段，也不参与权限判定，却会在用户注销时成为外键阻塞。
- `repositories/announcement_repo.py` 的 `create_announcement`、`create_template`、`list_announcements` 以及草稿读取都直接读写 `created_by`；`api/announcement_api.py` 的 `_announcement_view`、`_template_view` 继续把该字段作为出参，`services/announcement_tasks.py` 把草稿创建者复制到新公告。
- `services/user_tasks.Delete_user` 已有正确的最终事务：同一个 `session_scope` 内删除认证记录并删除用户行，异常整体回滚。草稿级联应落到数据库外键，不新增手工删除草稿的旁路。
- `__init__._ensure_announcement_schema` 是普通启动路径的既有自愈，只处理历史模板引用；本变更 MUST NOT 把公告/模板 `created_by` 的删列放进该路径。生产 MySQL 用显式迁移步骤；SQLite 新建库由模型直接建出真实外键。`extensions._make_engine` 已为 SQLite 默认开启 `PRAGMA foreign_keys=ON`。
- `announcement_repo.update_template` 当前逐字段赋值后 flush，没有类别守卫；`TemplateManager` 编辑时始终提交 `category`，所以后端必须在写库前完成校验并返回稳定的 400 结构。

## Goals / Non-Goals

**Goals:**

- 公告与公告模板不再持久化、读取、写入或返回创建者，同时保留全部内容、状态、目标和历史引用。
- 草稿保留 `created_by` 私有隔离；用户删除成功时由同一最终事务的 `ON DELETE CASCADE` 清理所属草稿，失败整体回滚。
- SYSTEM 模板类别不可改为其他类别，省略或同类别时允许编辑其他内容，CUSTOM→SYSTEM 保持允许，拒绝时不部分落库。
- 提供仅面向 MySQL/MariaDB 的显式迁移：真实发现外键名、幂等、保留正文数据、部署先迁移后新代码，且不进入普通启动路径。
- 用独立真实 MySQL 8.0.46 fixture 执行迁移验收；新 SQLite 只验证模型真实外键与级联，不承担旧库迁移测试。

**Non-Goals:**

- 不新增公告/模板/草稿归属表、列、状态、权限点或后台修复任务。
- 不改变公告发送状态机、模板删除规则、草稿私有语义或 Web/Node/Global/CI/config。
- 不为历史公告/模板回填作者，也不把创建者追溯改名成其他字段。
- 不为 SQLite 旧库构建列重建/外键迁移框架；SQLite 只用于新模型与启动路径验证。
- 不自动迁移生产库，不执行 SSH、真实发信或 commit/push。

## Decisions

### 1. 归属模型与代码面

- `Announcement` 删除 `created_by` 列、`users.id` 外键和 `creator`；`AnnouncementTemplate` 同样删除三项。`AnnouncementDraft` 保留 `created_by` 与 `creator`，仅把外键改为 `db.ForeignKey("users.id", ondelete="CASCADE")`。
- 仓储函数 `create_announcement`、`create_template` 删除 `created_by` 形参；`list_announcements` 删除创建者过滤参数与谓词。草稿仓储的 `created_by` 参数、过滤和归属校验全部保留。
- API 的公告/模板视图删除 `created_by`；草稿视图继续返回 `created_by`。创建模板和转换模板不再需要传入创建者；复制公告为草稿仍把当前操作员传给 `save_draft(created_by=...)`。
- 服务层 `_DraftSnapshot` 不再复制 `created_by` 到公告；`copy_announcement_as_draft_service` 的 `created_by` 保留并明确表示“新草稿所属操作员”；`convert_announcement_to_template_service` 删除 `created_by` 参数。批量发送、重发和转模板的正文/目标路径不变。
- 选择数据库级联而不是 service 手工删除草稿：用户删除最终事务已经存在，数据库外键是单点不变式，失败由同一事务回滚，且可同时约束未来删除入口。服务层只在注释中说明该事务边界，不新增删除函数。

### 2. SYSTEM 类别守卫

- 守卫放在 `announcement_repo.update_template` 的写入前：先按主键取模板；若当前类别为 SYSTEM，且请求显式提供非空 `category`，将值解析为目标类别，只有目标为 SYSTEM 才继续；否则立即抛 `ValueError("cannot_change_system_template_category")`，不修改任何属性。
- 守卫通过后才按既有允许字段一次性赋值并在末尾 flush。因此多字段请求即使同时改名称/正文/类别，也不会先落一部分；API 的 `session_scope` 继续负责提交或回滚。
- API 将上述固定原因映射为 `400`，响应沿用 `_error` 的 `{success:0,message,error_reason}` 结构；`error_reason` 精确为 `cannot_change_system_template_category`。省略 `category`、传 `null` 或传 `system` 不触发拒绝；CUSTOM→SYSTEM 不触发拒绝。
- Web 已统一按 `status + body + route` 交给错误弹窗；本变更只保证后端状态码和原因字面量，不改 Web。

### 3. 旧库迁移与部署顺序

- 新增显式迁移入口 `migrations/migrate_announcement_ownership.py`，提供 `migrate(url) -> report` 和 `--url` CLI；应用模块不导入它，普通启动不调用它。该入口 MUST 在执行任何 DDL 前检查 `engine.dialect.name`，仅接受 `mysql`/`mariadb`；SQLite 或其他 dialect 直接报“不支持”，不建表、不删列、不进入半迁移。迁移入口不导入 `FuxiYu_CtrKernel` 包，避免加载 `.env`，只依赖 SQLAlchemy 和标准库。
- 迁移先通过 SQLAlchemy `Inspector` 读取实际表、列和外键：对 `announcements`、`announcement_templates` 找出约束列包含 `created_by` 且引用 `users.id` 的外键，按元数据返回的真实名称删除，再删除列；MUST NOT 硬编码 `announcements_ibfk_1` 等自动名。目标列已不存在时视为已完成。
- 对 `announcement_drafts`，发现 `created_by` 的实际外键；若删除规则已是 `CASCADE` 则跳过，否则按真实名称删除旧约束并创建 `fk_announcement_drafts_created_by ... ON DELETE CASCADE`。若没有外键而列存在，直接补建级联外键；重复执行收敛为同一状态。
- MySQL/MariaDB 只执行 `ALTER TABLE ... DROP FOREIGN KEY`、`DROP COLUMN`、`ADD CONSTRAINT`，只改 `created_by` 归属列和约束；`template_id`、正文、目标、状态、时间及其他列/索引原样保留。不得重建表、复制数据或引入 SQLite 迁移分支。
- 迁移幂等来自每次操作前的元数据检查，而非吞异常。若旧库出现未预期的列/约束组合，迁移应报出实际名称并停止，不猜测、不删无关列。
- 真实验收直接使用 root 已有的 `/mnt/e/AI/Fuxi_audit_artifacts/q68-q51-20261029/check_mysql_migration.py`（无 CLI 参数），不在产品仓复制 verifier，也不加入 pytest 默认套件。该 harness 读取同目录 `mysql-instance.json`/`legacy-mysql-before.json`，只连指定 Unix socket，重置其自有的 `q68_fixture` 与 `q68_fixture_explicit`，分别用自动名和 `q68_<table>_explicit_author` 显式名建旧四表；每个 schema 调用产品 `migrations/migrate_announcement_ownership.py --url ...` 两次，检查删除的两列/外键、草稿 FK CASCADE 与全文数据，插入新的无作者公告/模板，再以事务删除 user3 验证回滚、删除 user1 验证提交，输出 `mysql-migration-acceptance.json`。不连接默认 socket、不触碰现有业务库、不 shutdown 实例；实例最终 shutdown 由 root 负责。
- 显式外键名与自动名都在该 harness 的两个自有 schema 中真实覆盖，不在产品仓另建 harness 或临时库；验收失败时保留日志与 JSON，不回滚 root fixture。
- 部署顺序固定：停止旧 Ctrl → 备份数据库 → 运行迁移并核对外键/行数/正文 → 部署并启动新代码 → 验证。旧代码依赖 `created_by NOT NULL`，迁移后不可直接回滚代码，回滚需恢复备份；因此必须在维护窗口执行。普通 `db.create_all()` 和 `_ensure_announcement_schema()` 不承担本迁移。

### 4. 测试策略

- 默认 pytest 仍只跑隔离 SQLite 安全套件；使用 root 提供的 `run_pytest_no_dotenv.py` 与 `/home/chest/miniconda3/envs/fuxi/bin/python`，不新增 MySQL 环境开关，不让默认套件连接外部数据库。
- 模型/API 测试直接检查新表列、外键、关系和出参，不再通过旧的 `created_by` 构造公告或模板；草稿测试继续断言 `created_by` 与 `creator`。新建 SQLite 库只验证模型真实外键、`PRAGMA foreign_keys=ON` 与级联行为。
- 用户删除测试使用真实 SQLite 外键：目标用户草稿级联消失，其他用户草稿、公告和模板保留；在最终事务中级联后注入失败，断言用户、认证记录与草稿全部回滚。
- 类别守卫测试同时覆盖 API 400、多字段不部分落库、省略/同类别可编辑、CUSTOM→SYSTEM 允许，并在仓储层直接调用确认不变式不依赖路由。
- 迁移单元/入口测试只验证纯规划与守卫：用 fake Inspector 元数据选择自动名与显式名外键，编译 MySQL/MariaDB DDL；另用 SQLite URL 调用实际 `migrate(url)` 入口，断言在任何 DDL 前拒绝且 schema 不变。它们不连接 MySQL、不执行真实迁移，不能作为真实迁移证据。
- 迁移真实验收不进入 pytest，由 root 已有的 `/mnt/e/AI/Fuxi_audit_artifacts/q68-q51-20261029/check_mysql_migration.py` 直接执行（无参数，读取同目录 JSON）；它重置自有的 `q68_fixture`/`q68_fixture_explicit`，用自动名与 `q68_<table>_explicit_author` 两种真实外键建旧四表，每个 schema 调用产品迁移 CLI 两次，逐行比较所有迁移不应改动的数据（公告/模板除被删的 `created_by` 外全部字段，草稿含 `created_by` 的全部字段），验证无作者插入、user3 删除回滚与 user1 删除提交。harness 不复制进产品仓，不读应用 `.env`，不连默认 socket，不 shutdown 实例；结果写 `mysql-migration-acceptance.json`。
- 启动路径不把 helper 测试冒充完整 `create_app`：用一次性 SQLite 列保留测试覆盖 `_ensure_announcement_schema`，再用 `create_app → _init_database → _ensure_announcement_schema` 的完整源码调用链检查补足“不删列、不调用迁移”；Coverage note 明确未自动启动完整 `create_app` 的边界，避免重绑全局引擎和种子副作用。
- 现有公告测试中的 `created_by` 构造参数和出参断言同步清理；批量发送、重发、复制为草稿、转模板继续由既有服务/API 测试覆盖。

### 5. 主规格数据附录同步计划

- 本计划阶段不修改主规格。apply/sync/archive 只有在对应 requirement 同步成功后，才按以下最小编辑更新主 spec 的 `## Data model appendix`；未列出的字段行一律保留，不得删除或重排其他字段。
- `openspec/specs/backend--table-announcements/spec.md`：只删除 `created_by` 行；模型同时不再有该用户的 `created_by` 外键与 `creator` 关系，公告标题、正文、原始正文、状态、目标、计数、时间、`source_draft_id`、`template_id` 行全部保留。
- `openspec/specs/backend--table-announcement-templates/spec.md`：只删除 `created_by` 行；模型同时不再有该用户的 `created_by` 外键与 `creator` 关系，名称、类别、描述、主题/正文模板、来源公告与时间行全部保留。
- `openspec/specs/backend--table-announcement-drafts/spec.md`：只把 `created_by` 行的模型声明改为 `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)`；字段与 `creator` 关系继续保留，其他字段行全部保留。
- 三个 delta spec 的 `## Data model appendix` 只列本次变更摘要，不复抄或删除整张主 spec 字段表；delta 不是主 spec 的替代数据附录。
- 同步/归档失败时不得提前改主 spec；主 spec 未同步前也不写 sidecar mapping，沿用 Anvil 现有规则。

## Risks / Trade-offs

- **不可逆删列**：迁移后旧代码无法运行；必须以备份和停服窗口兜底，回滚只能恢复备份。
- **MySQL DDL 自动提交**：无法像 DML 一样整体回滚；迁移按“先检查、最小步骤、可重跑”设计，执行前必须备份，失败时按报告中的真实约束名继续或恢复。
- **仅支持 MySQL/MariaDB**：迁移入口对 SQLite 或其他 dialect 在 DDL 前明确拒绝；本地旧 SQLite 库不在本迁移范围，开发库按现有约定重建即可。生产 MySQL 迁移后由 root 最终验收，不能由默认 SQLite 套件替代。
- **API 出参破坏性变化**：公告/模板不再返回 `created_by`；Web 未消费该字段，但外部调用方若曾依赖需同步适配，本期不改 Web。
- **类别守卫范围**：只禁止 SYSTEM→其他类别，不新增 SYSTEM 模板不可编辑名称/正文的限制；省略类别仍可编辑，避免扩大只读范围。
- **测试环境边界**：默认套件只证明 SQLite 模型/接口/级联行为；MySQL 方言的外键名发现、DDL、全文保留与 DML 回滚必须由 root 的独立 MySQL 验收证明。生产 MySQL 未执行，不能宣称已部署。
- **验收 fixture 重置**：root harness 会重置其自有的 `q68_fixture`/`q68_fixture_explicit`，仅用于独立实例验收；不触碰默认 socket、现有业务库或其他库，实例最终 shutdown 由 root 负责。
