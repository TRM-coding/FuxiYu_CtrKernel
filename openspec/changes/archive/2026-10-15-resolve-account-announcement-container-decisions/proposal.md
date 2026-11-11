# Proposal

## Why

用户删除、公告草稿、冻结展示及长期容器恢复存在已确认的规则分叉。落实已确认的产品决策，使查询、操作和持久化使用一致的边界，并明确允许主动清空自定义权限组。

## What Changes

- 区分认证失效的 401 与已认证但无权限的 403；删除用户时在删除事务内清理其 Token，容器归属阻止删除仍返回 wild_container。
- 模板仅填充公告编辑初值；草稿与公告保存独立内容，解除历史模板引用，自定义模板删除不影响已有内容。
- 草稿按创建者隔离，更新、删除和发送不得访问他人的草稿。
- 保留自定义权限组可清空的规则，允许操作者因此失去管理权限。
- 冻结查询与调度共享有效冻结天数计算；恢复长期标记执行数量限额校验并返回具体失败原因。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-users`: 用户删除事务与容器阻止删除的边界。
- `backend--table-authentications`: 认证状态码与用户 Token 生命周期。
- `backend--table-auth-group-entities`: 自定义组实体允许清空。
- `backend--table-announcement-drafts`: 独立内容快照与创建者隔离。
- `backend--table-announcement-templates`: 模板初始化语义与删除解除引用。
- `backend--table-announcements`: 发送使用独立内容，保留投递快照。
- `backend--table-container-disk-freeze-state`: 有效冻结天数的查询与调度一致性。
- `backend--table-long-term-containers`: 普通设置与恢复共用数量限额。
- `backend--table-deleted-container-restore-snapshot`: 容量失败时恢复不得消费快照。

## Impact

影响认证依赖、用户删除、公告仓储与 API、冻结计算、容器恢复及其隔离测试。沿用当前 API 与数据库升级载体，保留系统模板保护、公告投递快照和容器恢复来源选择。
