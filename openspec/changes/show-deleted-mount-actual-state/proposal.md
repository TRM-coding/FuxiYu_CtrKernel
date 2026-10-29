## Why

已删除容器的历史挂载路径即使被标记为已清理，目录也可能仍然存在。当前 Ctrl 不查询此类路径，页面无法展示实际采集结果。

## What Changes

- 对有历史路径的已删除记录继续进行只读用量查询，不以清理标记过滤。
- 保留现有权限、目标机器定向和响应格式；不更改路径、清理记录或恢复规则。

## Capabilities

### Modified Capabilities

- `backend--table-deleted-container-restore-snapshot`: 允许查询已清理记录的历史挂载路径。

## Impact

- Ctrl 已删除容器用量查询与相关测试；无需更改表结构或 Node 接口。
