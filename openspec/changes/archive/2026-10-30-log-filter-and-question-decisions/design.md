## Context

`GET /api/admin/operation_logs` 目前把 `target_type` 声明为单个可空字符串，repo 用 `==` 过滤。容器操作历史直接调用同一 repo，并以字符串 `container` 查询；管理日志与容器历史随后分别补充展示字段。Q53/Q49/Q54/Q44/Q45 需要把已核实的现状写成可验证契约，避免后续把“没有实现”误当成“应该实现”。

## 现状核实

- `Change_password` 与 `Reset_password` 只调用 `update_user` 更新哈希，没有删除 `authentications` 行。
- `delete_announcement` 只对公告行执行 `session.delete`；投递使用创建时已准备好的 `_PreparedSend`，删除后仍会继续发信，终态回写按 id 查找不到时返回 `None`。
- `UpdateUserFields` 把空字符串归一为 `None`，API 用 `exclude_none=True` 过滤；repo 的 `update_user` 也忽略 `None`，模型列为 `nullable=False`。内部服务直接传空字符串仍可写空串，因此做最小防御。
- 管理日志 API 当前没有 `target_id` 参数；repo 的 `target_id` 仅由容器历史等内部调用使用。
- 容器历史与管理日志都调用 `operation_log_repo.list_logs`，前者补 `operator_username`，后者补 `target_name`/`target_display_name`/`root_owner`。

## Decisions

### 目标类型多选

- FastAPI 参数使用 `list[str] | None = Query(default=None)`：重复传 `target_type` 得到列表，单个旧参数得到单元素列表，不传得到 `None`。
- repo 的 `_filtered_stmt` 同时接受字符串、字符串序列与 `None`：字符串仍走等值比较以兼容既有调用；非空序列走 `IN`，多值之间为 OR；`None`、空序列、空字符串都视为不筛选。
- `operator_user_id`、`operation`、`success`、`start`、`end` 仍各自追加 `WHERE`，与目标类型为 AND。
- 分页仍先对完整过滤条件计数，再按 `id desc` 取页；统计接口不增加目标类型参数，保持原有时间范围聚合口径。
- 管理 API 不新增 `target_id`；repo 的 `target_id` 参数保留给容器操作历史等内部调用。

### 容器历史与管理日志

- 两者都以 `operation_logs` 为数据源，分别调用现有 repo 查询。
- 管理日志服务补充 `target_name`、`target_display_name`、`root_owner`；容器历史补充 `operator_username`，并按容器创建时间过滤 id 复用前的旧日志。
- 不强行统一 DTO，也不把一方的展示字段复制给另一方。

### 问题决策

- Q53：`Change_password`/`Reset_password` 只更新口令哈希，不删除 `authentications` 行；其他会话继续有效。测试锁定该行为。
- Q49：`delete_announcement_service` 只删除公告行；后台投递使用已准备好的消息继续发信，终态回写找不到行时自然不生效，不会复活公告，也不存在取消投递的旁路。
- Q54：`User.graduation_year` 保持 `nullable=False`；请求层空字符串归一为 `None` 且被 `exclude_none` 排除；服务层再忽略空值/空字符串，避免内部调用把年份写成空串。
- Q44：不增加管理端 `target_id` 过滤。
- Q45：保持同表查询、分开展示字段补充。

## Risks / Trade-offs

- 把 `target_type` 改为列表后，旧客户端仍可传单值；新客户端可重复传参。
- 空字符串目标类型按“无值”处理，避免 `?target_type=` 产生无意义过滤。
- 服务层忽略毕业年份空值属于防御性最小修复，不改变正常数值更新。
