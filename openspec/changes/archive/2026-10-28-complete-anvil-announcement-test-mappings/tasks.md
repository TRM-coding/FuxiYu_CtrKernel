# Tasks

## 1. 模板读回与读取出参

- [x] 1.1 在新文件 `test/announcement/test_anvil_announcement_mappings.py` 建立本批测试的导入与最小辅助，兑现 `backend--table-announcement-templates` / `announcement_templates 持久化结构` / `读取有效记录`：新 session 按主键重开模板，断言类型、默认 `category`、空值语义、创建者稳定主键与时间窗。完成判据：`-k test_anvil_t01` 定向通过。
- [x] 1.2 兑现 `backend--table-announcement-templates` / `announcement_templates 生产职责与生命周期` / `读取模板`：经 API 断言详情返回 `subject_template`/`body_template`/`source_announcement_id`，并断言请求前后草稿与公告行数不增。完成判据：`-k test_anvil_t02` 定向通过。

## 2. 模板删除与分页

- [x] 2.1 兑现 `backend--table-announcement-templates` / `announcement_templates 生产职责与生命周期` / `删除被历史内容引用的自定义模板`：建模板、草稿、带历史 `template_id` 的公告，生成真实 `send_mail` 日志后删除模板，删除前后断言公告/草稿主题、正文、目标、快照、计数/状态与日志行保留，仅公告 `template_id` 解除。完成判据：`-k test_anvil_t03` 定向通过。
- [x] 2.2 兑现 `backend--table-announcement-templates` / `announcement_templates 列表分页参数有界且可分页` / `越界或非整数参数`：断言 `offset=not-a-number` 返回 400 与 `error_reason=invalid_payload`。完成判据：`-k test_anvil_t04` 定向通过。
- [x] 2.3 兑现同 Requirement 的 `界内分页参数` 与 `205 条模板分页`：用互异 `created_at` 建 205 条模板，断言默认请求 100 条/`total=205`、显式 100/200 与 offset 的精确 id 切片、`category=custom` 的过滤后 `total` 及同一降序顺序。完成判据：`-k test_anvil_t05` 定向通过。

## 3. 公告读回与发送快照

- [x] 3.1 兑现 `backend--table-announcements` / `announcements 持久化结构` / `读取有效记录`：新 session 按主键重开最小/完整公告，断言类型、状态、默认计数、可空列空值、`target_snapshot` 文本往返与 `source_draft_id` 的 NULL/赋值往返。完成判据：`-k test_anvil_a01` 定向通过。
- [x] 3.2 兑现 `backend--table-announcements` / `announcements 生产职责与生命周期` / `批量发送受理`：发送单条草稿后从持久化公告读取 `target_snapshot`，断言可解析、含解析摘要字段，且 `recipient_count` 与解析总数一致。完成判据：`-k test_anvil_a02` 定向通过。

## 4. 重发、统一 renderer 与不写回快照

- [x] 4.1 兑现 `backend--table-announcements` / `announcements 生产职责与生命周期` / `模板已删除`：在模板引用已解除的公告上重发，捕获传输消息并断言正文来自公告已保存内容、终态 `SENT`、`template_id` 保持 NULL、既有字段未被改写。完成判据：`-k test_anvil_a03` 定向通过。
- [x] 4.2 兑现 `公告 Markdown 邮件渲染与双正文` / `历史纯文本按同一规则解析`：分别通过同一发送入口发送纯文本（含单换行）与 Markdown，记录同一 renderer 的调用与输出，断言两者各调用一次且与直接渲染一致。完成判据：`-k test_anvil_a04` 定向通过。
- [x] 4.3 兑现同 Requirement / `HTML 不进入持久化与审计`：发送与重发前后对草稿、模板做全字段快照，在传输捕获点复核，断言公告正文未被 HTML 替换、模板不变、审计详情不含 HTML 标记。完成判据：`-k test_anvil_a05` 定向通过。

## 5. 目标套件回归

- [x] 5.1 在 WSL 隔离环境运行 `test/announcement` 与 `test/utils/test_announcement_markdown.py`，确认新增 10 个测试与既有公告/渲染套件共同通过；保留命令、退出码与失败摘要用于交付。完成判据：定向命令退出码 0。

## Workflow follow-up

- 运行 official `openspec-verify-change` 仅作 advisory，不创建 `verify.md`。
- 运行 official no-op 主规格 sync，确认 3 个主规格的 Purpose/Requirement/附录不变。
- 用 `anvil-test-plan` 更新 3 个 canonical main sidecars，只反映当前已核对断言与真实限制。
- 运行 official archive，归档为 `2026-10-28-complete-anvil-announcement-test-mappings`。
