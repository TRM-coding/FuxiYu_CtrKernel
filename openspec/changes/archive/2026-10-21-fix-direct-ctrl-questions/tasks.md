# 任务

- [x] 删除跨表 capability，把 delta 拆回 system-settings / operation-logs / images / containers / announcement-templates。
- [x] Q23：增加设置整数和提醒节点的严格校验，并明确 GROUP_ORDER 由 Web change 承接。
- [x] Q33：修正四处 entrypoint 说明，并增加可执行文档扫描测试。
- [x] Q46：改为按目标类型独立只读 session 批量回填；补 User 查询失败与事务级异常测试。
- [x] Q47：区分 stats 与 list 的错误原因并补测试。
- [x] Q52：补 `list_templates` 的 `limit` 1..200、`offset >= 0` 与 400 `invalid_payload` 映射，补 205 条模板分页回归。
- [x] 父任务运行最终定向测试 110 项通过，并在 WSL 运行包含跨仓探针的完整默认安全套件：1358 通过、6 排除；严格校验通过。
- [x] 独立 review 第 2 轮已批准；父任务生成真实 verify.md 并按用户要求提交。
