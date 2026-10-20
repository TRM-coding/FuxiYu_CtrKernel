# 修正已确认的 Ctrl 缺口

## 背景

Q23（Ctrl 校验部分）、Q33、Q46、Q47、Q52（Ctrl 分页边界）的现状可由源码和现有测试直接判定。Q46 原文保留“批量化还是接受现状”的待选策略；本变更选择批量化，理由是它只改变查询次数，不改变返回字段、历史名称、root owner、容器代际判断或分页契约，也不引入缓存/持久化新状态，因此属于行为保持的实现优化，不构成需要用户决定的业务语义。

Q23 的前端 `GROUP_ORDER` 排序子项由 Web change `apply-direct-web-fixes` 的 `frontend--page-settings` 承接；本变更只负责 Ctrl 设置校验，不声称完成 Q23 排序子项。Q52 的 Web 分页/深链由同一 Web change 承接；本变更只补 Ctrl 的列表分页参数边界。

## 目标

- 拒绝会被静默截断或丢弃的非法设置输入。
- 让 entrypoint 的四处说明与实际构建语义一致。
- 在不改变返回契约、不新增缓存/状态的前提下，按目标类型独立只读会话批量化操作日志目标回填。
- 为统计接口使用独立的 `stats_failed` 错误原因。
- 为公告模板列表补 `limit` 1..200、`offset >= 0` 边界，复用既有 400 `invalid_payload` 校验映射，并验证超过 200 条模板的分页。

## 变更归属

Q33 的四处说明为 `models/image.py`、`models/containers.py`、`schemas/image.py`、`services/container_module/creation.py`；`models/image.py` + `schemas/image.py` 归 images，`models/containers.py` + `services/container_module/creation.py` 归 containers。

- `backend--table-system-settings`：Q23 的 Ctrl 设置校验。
- `backend--table-operation-logs`：Q46 的批量回填/失败隔离、Q47 的 `stats_failed`。
- `backend--table-images`：Q33 的 `models/image.py`、`schemas/image.py` 说明。
- `backend--table-containers`：Q33 的 `models/containers.py`、`services/container_module/creation.py` 说明。
- `backend--table-announcement-templates`：Q52 的 `list_templates` 分页参数与分页回归。

## 非目标

- 不修改数据库结构、迁移、状态机、Node 协议或生产配置。
- 不处理仍需用户决定的 Q，不修改 Web 仓库或 Web change。
- 不修改 `review.md`；修订后等待独立复核。
