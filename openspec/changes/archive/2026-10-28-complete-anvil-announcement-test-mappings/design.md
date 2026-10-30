# Design

## Context

本变更触及 3 个既有能力，但只交付规划产物（proposal / design / delta / test-plan），不交付实现。可用的既有资产：

- 主规格：`openspec/specs/backend--table-announcement-{drafts,templates,announcements}/spec.md`，共 9 个 Requirement、23 个 Scenario。
- 主规格旁 sidecar：drafts 与 templates 仍是旧表格台账，templates 明确把 3 个场景标为“待复核”；announcements 已是 canonical 结构，但存在只核对文件存在与运行总数的痕迹。旧表与旧运行数字按任务约束只作线索，不复制。
- 真实测试：`test/announcement/` 下的 `test_models.py`、`test_repository.py`、`test_services.py`、`test_api.py`、`test_template_decoupling.py`、`test_draft_ownership.py`，以及 `test/utils/test_announcement_markdown.py`、`test/utils/test_mail.py`；公共夹具在 `test/announcement/conftest.py` 的 `inline_send_thread` 与仓库级 `db_session` / `client` / `test/factories.py`。
- 与并行批次的边界：Ctrl 第 1 批正在处理 RBAC 关联表，其文件集合与本变更不重叠。

约束（来自任务与项目 config）：描述用中文，结构标题与 SHALL/MUST 保留英文；不写 `review.md` / `tasks.md`；不改主规格、主 sidecar、既有测试与业务实现；不读取 `.env`/密钥、不触达生产；不 commit/push；本变更唯一可写目录为 `openspec/changes/complete-anvil-announcement-test-mappings/`，后续 apply 的新测试限定 `test/announcement/test_anvil_announcement_mappings.py`。

## Goals / Non-Goals

**Goals**

1. 23 个 Scenario 全部落到 canonical 映射：Requirement → Scenario → Test/check（嵌套 `[X]`/`[ ]`）→ Assertion scope → 可选 Coverage note。
2. `[X]` 必须建立在读过真实断言之上，覆盖既有（含跨文件的渲染/邮件边界测试），不把既有覆盖误报为缺口。
3. 缺口只要能按既定规格补测，就写 `[ ]` 计划项并给出可执行的断言意图，而不是用 Coverage note 或“无独立 Scenario”之类的伪决策回避。
4. delta 的 MODIFIED Requirement 块与主规格逐字一致，Requirement 内部不掺入本轮解释句，使 sync 无净业务与文本变更。

**Non-Goals**

- 不修任何 app 缺陷：本批明确不处理“公告转模板重名导致 500”一类问题；若发现实现与规格不符，只在 design 的 Risks 段记录精确证据，不写进 Requirement，也不改实现。
- 不重构测试目录、不新增/修改 fixture、不用反射 ORM 结构或源码字符串冒充行为断言。
- 不验证生产 MySQL 方言、真实 SMTP 与邮件客户端渲染。

## Decisions

1. **delta 用 MODIFIED 逐字复制，而不是 ADDED 或空 delta。**
   三个能力本轮都没有行为变化，但 anvil 的 test-plan 与 review 需要一个锚定到能力的规格载体。选择 MODIFIED + 完整 Requirement 块逐字复制，可以同时满足“delta 必须包含完整 requirement 块”的官方规则与“sync 后主规格无净变更”的约束。备选方案是 `skip_specs: true`，但那会切断 capability 与映射的关联，且与任务要求的三仓库口径不一致。因此 Requirement 文本、字段附录引用句、Scenario 的 WHEN/THEN 与空行位置都按主规格原样保留，本轮意图只写在 proposal 与 design。

2. **以“断言范围”而非“测试存在”判定 `[X]`。**
   逐条读断言体：既确认被测字段/分支，也确认它是否真的验证了 Scenario 的 THEN。例如 `test_a06_list_templates` 只断言请求成功，不能当“界内分页参数”的完整证据；`test_repository.py::test_r02` 只断言按 id 命中的对象 id，不足以支撑“读取有效记录”的类型与空值语义，于是归档为缺口而非已覆盖。

3. **缺口集中到一个新测试文件，按 capability 分段。**
   10 个缺口计划全部写入 `test/announcement/test_anvil_announcement_mappings.py`，文件内按 3 个 capability 分节，函数名沿用仓库既有的 `mNN_` / `rNN_` / `aNN_` 风格并加 `anvil` 前缀标识。复用既有夹具（`db_session`、`client`、`mock_operator_token`、`inline_send_thread`、`test/factories.create_user` 等），不新建 conftest、不改公共夹具。分页项 t05 同时服务“界内分页参数”与“205 条模板分页”两个 Scenario；发送/重发不写 HTML 与纯文本/Markdown 统一路径分别用持久化快照和同一 renderer 调用记录，不使用源码字符串或反射断言。备选方案是按层拆成多个文件，但那会与“限定单一文件、不重构目录”的约束冲突。

4. **新测试只断言真实写读 / 服务 / API 行为。**
   持久化读回类缺口一律用新会话按主键重开（沿用 `test_m02b_draft_readback_contract` 的做法），而不是断言创建时的内存对象；API 类缺口走 `client` 真实请求并解析响应；投递类缺口用 `inline_send_thread` 让后台线程就地执行，并 monkeypatch `utils.mail._send_batch_smtp` 捕获消息。发送路径是否写回草稿/模板，用发送前、传输捕获点与完成后的持久化快照比对；纯文本/Markdown 统一路径用发送入口对同一 renderer 的调用记录，不用 `inspect.signature` 冒充行为断言。明确不引入 `inspect(engine)` 反射列清单来替代行为断言（`_detach_template_references` 相关既有测试的反射用法只作为旧库兼容线索，不扩大到新测试）。

5. **模板删除后的重发缺口直接落在服务投递入口。**
   “模板已删除”Scenario 的 THEN 是“仍按公告自身持久化的内容投递或重发”。既有 `test_q06_delete_template_referenced_by_announcement_keeps_content` 只证明内容快照与追溯引用保留，没有走重发路径。补测用 `start_resend_service` + 就地线程 + 捕获传输层，断言捕获消息的 `content` 等于公告已保存的 `content`、公告终态 SENT、`template_id` 保持解除，且公告既有字段未被改写。

## Risks / Trade-offs

- **逐字复制的 delta 在 sync 时可能被判为“无变更”。** 这是本变更的预期结果，不是失败；但若某个 CLI 版本把“无净变更”当错误，需要在 sync 阶段显式说明并跳过写入，而不是为了让它“有变更”去改 Requirement 文本。风险由 review 与父代理确认。
- **跨文件映射的稳定性。** announcements 的 6 个渲染/安全 Scenario（“公告 Markdown 渲染的内容与安全边界”的 5 个 + “历史纯文本按同一规则解析”）依赖 `test/utils/test_announcement_markdown.py`；“发送草稿生成双正文”还依赖 `test/utils/test_mail.py`。如果后续重构把渲染或邮件测试搬走，映射会失效。缓解：nodeid 写全路径，并在 Assertion scope 里点明被复用的是渲染函数边界还是投递服务边界。
- **补测项均要求真实断言。** 10 个计划项集中在“读回契约（含 `source_draft_id`）、模板读取出参、删除后保留主题/目标与投递记录、非整数 `offset`、分页默认值/过滤 `total`/真实顺序、`target_snapshot` 快照、模板删除后重发、纯文本/Markdown 同一 renderer 调用、发送/重发不写回草稿/模板”，其余 Scenario 由既有测试支撑。若 review 认为某些既有测试的断言仍不足，需要补的是断言而非新用例，应在 review 中逐条指出。
- **已观察到的实现与规格的偏差（仅记录证据，不在本变更修正）**：
  - 公告详情/轮询出参：`api/announcement_api.py::_announcement_progress_view` 不含 `content` 与 `target_snapshot`（`test_a16b` 正是断言这一点），因此“`target_snapshot` 当次解析快照”只能通过持久化层与 `_create_sending_announcement` 写入路径验证，不能从轮询 API 读取。
  - `repositories/announcement_repo.py::list_templates` 只按 `created_at` 倒序排序且没有 tie-breaker；同值时间戳下分页顺序不稳定。t05 必须显式设置互异 `created_at`，逐 id 断言期望顺序切片与 `offset`/`limit` 的先后关系；两页 id 集合的不重不漏只作为附带结果，不能单独证明排序。
  - `test_announcement_markdown.py::test_render_preserves_single_newlines` 的 `inspect.signature` 只证明接口只有一个入参，不能证明内部没有按内容探测的分支，只作接口线索。a04 用纯文本/Markdown 代表输入记录发送入口对同一 renderer 的调用，能证明入口统一且输出与直接渲染一致；renderer 内部若存在黑盒分支仍不可证，Coverage note 保留该限制。
