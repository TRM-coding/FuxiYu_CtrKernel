## MODIFIED Requirements

### Requirement: 已删除容器遗留挂载用量查询接口

Ctrl SHALL 提供 `POST /api/containers/get_deleted_container_mount_usage`。请求体 SHALL 只含 `deleted_ids`：正整数数组，最多 100；MUST NOT 接受宿主路径。成功响应 SHALL 为 `{success:1,usages:[{deleted_id,bytes,measured_at,pending,error}]}`，MUST NOT 返回 `path`。无挂载路径的项 MAY 省略且不得触发扫描；有历史路径的项 SHALL 不因清理标记而跳过查询。请求模型失败 SHALL 走现有 400 `invalid_payload`；缺 `container:manage` SHALL 走现有 403 `insufficient_permission`。该接口不改变周期 WSS 或既有列表/恢复/清理接口，也不新增 DB 列/表/JSON 迁移。

#### Scenario: 成功响应形状固定

- **WHEN** 请求合法且所有可查询项均成功
- **THEN** 返回 `success:1` 与 `usages` 数组；每项只有 `deleted_id`、`bytes`、`measured_at`、`pending`、`error`，不含 `path`

#### Scenario: 无挂载或已清理可省略

- **WHEN** 某个 `deleted_id` 没有可解析的挂载路径（包括已清理且无路径）
- **THEN** 该项可从 `usages` 省略，Ctrl 不请求 Node，也不返回旧缓存

#### Scenario: 已清理记录查询历史路径

- **WHEN** 某个 `deleted_id` 已标记清理，但仍有可解析的历史挂载路径
- **THEN** 按既有规则向对应 Node 查询该路径，返回成功、等待或错误结果，不更改清理记录、历史路径或恢复资格

#### Scenario: 非法请求与权限错误

- **WHEN** `deleted_ids` 非正整数、超过 100、混入宿主路径，或调用者缺少 `container:manage`
- **THEN** 分别返回现有 400 `invalid_payload` 或 403 `insufficient_permission`，且不发起 Node 请求
