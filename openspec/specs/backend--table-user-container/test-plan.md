# user_container 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| user_container 持久化结构 | 读取有效记录 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计角色/密码/交接契约。 |
| user_container 生产职责与生命周期 | 协作角色变更 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_role_change_semantics_contract | 断言普通非 ROOT 互换无密码、ROOT 降 ADMIN 独立账号密码与绑定 username。 |
| user_container 生产职责与生命周期 | 普通非 ROOT 角色互换不改密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_role_change_semantics_contract | 断言普通非 ROOT 互换无密码、ROOT 降 ADMIN 独立账号密码与绑定 username。 |
| user_container 生产职责与生命周期 | 旧 ROOT 降为 ADMIN 保留独立账号密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_role_change_semantics_contract | 断言普通非 ROOT 互换无密码、ROOT 降 ADMIN 独立账号密码与绑定 username。 |
| 单目标 ROOT 提升（transfer_root=false） | 详情页单目标升 ROOT 只返回 root 一项 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_single_root_promotion_contract | 断言详情单目标只返回 root、一项、旧 ROOT 不变、不生成旧 owner 账号与 guard。 |
| 单目标 ROOT 提升（transfer_root=false） | 单目标升 ROOT 不生成旧 owner 账号 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_single_root_promotion_contract | 断言详情单目标只返回 root、一项、旧 ROOT 不变、不生成旧 owner 账号与 guard。 |
| 单目标 ROOT 提升（transfer_root=false） | 机器/容器/目标不可用时不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_single_root_promotion_contract | 断言详情单目标只返回 root、一项、旧 ROOT 不变、不生成旧 owner 账号与 guard。 |
| ROOT 交接（transfer_root=true） | 正常单旧 ROOT 交接返回两项不同登录名 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言 Home 交接两项/N+1、旧 ROOT 系统用户名、调用者先降级仍继续、目标/guard 拒绝。 |
| ROOT 交接（transfer_root=true） | 旧 ROOT 降 ADMIN 的独立账号使用其系统用户名 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言 Home 交接两项/N+1、旧 ROOT 系统用户名、调用者先降级仍继续、目标/guard 拒绝。 |
| ROOT 交接（transfer_root=true） | 直接 ROOT 降 ADMIN 也返回独立账号密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言 Home 交接两项/N+1、旧 ROOT 系统用户名、调用者先降级仍继续、目标/guard 拒绝。 |
| ROOT 交接（transfer_root=true） | 多个旧 ROOT 时逐项处理并返回 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言 Home 交接两项/N+1、旧 ROOT 系统用户名、调用者先降级仍继续、目标/guard 拒绝。 |
| ROOT 交接（transfer_root=true） | `transfer_root=false` 不进入交接循环 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言 Home 交接两项/N+1、旧 ROOT 系统用户名、调用者先降级仍继续、目标/guard 拒绝。 |
| ROOT 交接（transfer_root=true） | 机器或容器不可用时不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言 Home 交接两项/N+1、旧 ROOT 系统用户名、调用者先降级仍继续、目标/guard 拒绝。 |
| ROOT 交接（transfer_root=true） | 目标未绑定或用户名不可用时不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言 Home 交接两项/N+1、旧 ROOT 系统用户名、调用者先降级仍继续、目标/guard 拒绝。 |
| ROOT 交接（transfer_root=true） | 调用者先被降级也不影响后续步骤 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言 Home 交接两项/N+1、旧 ROOT 系统用户名、调用者先降级仍继续、目标/guard 拒绝。 |
| ROOT 交接的逐步执行与失败边界 | 两步成功各记一条真实日志 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言逐步 Node/绑定、失败停止、部分成功如实、后台 guard、Node 单目标且无 transfer_root。 |
| ROOT 交接的逐步执行与失败边界 | 第一步失败不继续第二步 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言逐步 Node/绑定、失败停止、部分成功如实、后台 guard、Node 单目标且无 transfer_root。 |
| ROOT 交接的逐步执行与失败边界 | 第二步失败不伪报整体成功 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言逐步 Node/绑定、失败停止、部分成功如实、后台 guard、Node 单目标且无 transfer_root。 |
| ROOT 交接的逐步执行与失败边界 | 绑定更新失败也停止后续步骤 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言逐步 Node/绑定、失败停止、部分成功如实、后台 guard、Node 单目标且无 transfer_root。 |
| ROOT 交接的逐步执行与失败边界 | 后台最小 guard 复核失败只记失败 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言逐步 Node/绑定、失败停止、部分成功如实、后台 guard、Node 单目标且无 transfer_root。 |
| ROOT 交接的逐步执行与失败边界 | Node 只改指定目标 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言逐步 Node/绑定、失败停止、部分成功如实、后台 guard、Node 单目标且无 transfer_root。 |
| 删除用户内部 ROOT 提升的密码兼容 | 删除用户内部提升生成随机 root 密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_delete_user_root_password_contract | 断言内部同步提升传 config.root_password、失败不回退弱密码、不触发 Web 交接。 |
| 删除用户内部 ROOT 提升的密码兼容 | 内部提升失败不回退弱密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_delete_user_root_password_contract | 断言内部同步提升传 config.root_password、失败不回退弱密码、不触发 Web 交接。 |

## 附加合同证据（非新增 Scenario）

- `UpdateRoleRequest.updated_role` 公开大写枚举（ADMIN/COLLABORATOR/ROOT），非法角色 400 且不下发 Node；`transfer_root:true` 仅 ROOT：`../../../test/container/test_container_api_collaborators.py::test_update_role_api_rejects_unknown_role_before_node`、`::test_collaborator_openapi_role_enums_are_public_uppercase`、`../../../test/container/test_password_contracts.py::test_update_role_api_transfer_root_contract`。
- 真实 Node Pydantic/HTTP wire：`../../../test/container/test_account_wire_contracts.py`，13 passed；大写角色被 Node 422 拒绝，helper 小写 wire 被接受且 no-store。

## 最近验证

- 时间：2026-10-24 17:30 +08:00
- 版本：4e6830dfa35e584d5232360d5c06b0ea0ed18f50（实现/测试提交）
- 主 spec SHA256：48301818245187FA01E71643294C6D896FDAEA1DED64039A971063BF0622AAE7
- 命令与环境：
  - WSL 离线 venv 根目录完整套件：`/home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest -q --no-header`
  - 真实 Node wire：`/home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest test/container/test_account_wire_contracts.py -q --no-header`
- 结果：完整套件 1431 passed、0 failed、6 deselected、24 subtests passed（224.04s）；Node wire 13 passed（19.72s）。
- 限制：6 项 integration/legacy 按策略排除；未运行真实生产 Docker/MySQL；持久化读取旧场景未在本轮重新审计。