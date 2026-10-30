## Why

管理日志当前只能按单个 `target_type` 精确匹配，无法一次筛选多种目标类型；同时 Q53、Q49、Q54、Q44、Q45 的口径尚未在规格中明确，代码现状容易被误改。需要先核实行为，再用最小改动补上多选筛选并锁定这些决策。

## What Changes

- 管理日志 `GET /api/admin/operation_logs` 的 `target_type` 支持重复查询参数，多值按 OR（`IN`）匹配；单个旧参数保持兼容，无值不筛选。
- 其他筛选条件仍与目标类型为 AND；分页总数/页数仍按过滤后的结果计算；统计接口口径不变。
- 管理日志不新增 `target_id` 过滤参数；repo 内部既有的 `target_id` 仅继续服务容器操作历史。
- 明确容器操作历史与管理日志查询同一 `operation_logs` 表后各自补充展示字段，不强求两者 DTO 一致。
- 明确密码修改/重置不吊销该用户其他会话。
- 明确发送中删除公告只删公告行，不取消已受理的后台投递。
- 明确毕业年份不可清空，数据库列保持 `nullable=False`；空值/空字符串更新被忽略。
- 新增针对性的 API、repo 与决策测试；不新增数据库结构。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-operation-logs`: 增加目标类型多选 OR 过滤，明确管理日志与容器历史的同表查询及展示字段边界，且不新增管理端 `target_id` 过滤。
- `backend--table-users`: 明确密码变更/重置不吊销其他会话，毕业年份不可清空且保持非空列。
- `backend--table-announcements`: 明确发送中删除公告不取消已受理投递。

## Impact

- Ctrl API：`api/operation_log_api.py`；repo/service：`repositories/operation_log_repo.py`、`services/operation_log_tasks.py`；用户字段保护：`services/user_tasks.py`。
- Ctrl 测试：操作日志 API/repo、用户密码与毕业年份、公告发送中删除。
- 不修改表结构、迁移、Node 接口或其他仓库；不提交、不归档。
