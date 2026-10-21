# 设计

- 设置服务增加严格整数转换和清理提醒节点校验，保留现有 min/max 范围检查；非法输入不写入，API 映射为 422 `invalid_setting`。
- entrypoint 只修正四处说明：`models/image.py`、`schemas/image.py`（删除 `utils/Container.py` 失效引用）、`models/containers.py`、`services/container_module/creation.py`；不改字段或构建行为。
- 操作日志按目标类型收集 ID，每类在独立的只读 `session_scope(commit=False)` 中批量读取机器、容器、用户、镜像、权限组和 root 绑定，再按原语义回填；不共享 session，因此某类 DBAPI/事务级异常不会毒化后续查询。返回字段、历史名称、代际判断和 root owner 语义不变，不新增缓存或持久化状态。`root_owner` 依赖容器与 User 两侧：User 查询失败时该字段可为空，容器 `target_name` 不受影响。
- stats 异常使用 `stats_failed`，列表异常继续使用 `list_failed`；只改 Ctrl 错误原因，前端 `routeErrorMap` 当前没有该 stats 路径的专用映射，本变更不修改 Web 文案。
- 公告模板列表沿用现有 FastAPI `Query` 约束，增加 `limit` 上限 200；复用既有 400 `invalid_payload` 查询校验，不新增全局异常处理分支或错误原因。正常 `limit=100/200`、默认 `offset=0` 不受影响。
- Q23 前端排序由 Web `apply-direct-web-fixes` 的 `frontend--page-settings` 承接；本变更不修改 Web。
