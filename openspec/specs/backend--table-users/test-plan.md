# users 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| users 持久化结构 | 读取有效记录 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计并同步权限快照新增约束。 |
| users 生产职责与生命周期 | 创建用户 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计并同步权限快照新增约束。 |
| 用户删除与认证记录同事务清理 | 有 Token 但无阻塞容器 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计并同步权限快照新增约束。 |
| 用户删除与认证记录同事务清理 | 容器阻止删除 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计并同步权限快照新增约束。 |
| 用户删除与认证记录同事务清理 | 删除事务失败 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计并同步权限快照新增约束。 |
| 权限快照区分方法能力与镜像资源通配 | 只有方法实体通配 | 已覆盖 | `../../../test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract` | 断言 entities 与 container/image resource_unrestricted 独立、直接 container:manage/bypass_resource、method wildcard 不放行、派生不落库。 |
| 权限快照区分方法能力与镜像资源通配 | 具备全局资源通配 | 已覆盖 | `../../../test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract` | 断言 entities 与 container/image resource_unrestricted 独立、直接 container:manage/bypass_resource、method wildcard 不放行、派生不落库。 |
| 权限快照区分方法能力与镜像资源通配 | 容器方法通配不等于资源通配 | 已覆盖 | `../../../test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract` | 断言 entities 与 container/image resource_unrestricted 独立、直接 container:manage/bypass_resource、method wildcard 不放行、派生不落库。 |
| 权限快照区分方法能力与镜像资源通配 | 直持容器管理或全局资源通配 | 已覆盖 | `../../../test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract` | 断言 entities 与 container/image resource_unrestricted 独立、直接 container:manage/bypass_resource、method wildcard 不放行、派生不落库。 |
| 权限快照区分方法能力与镜像资源通配 | 派生字段不落库 | 已覆盖 | `../../../test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract` | 断言 entities 与 container/image resource_unrestricted 独立、直接 container:manage/bypass_resource、method wildcard 不放行、派生不落库。 |
| 权限快照区分方法能力与镜像资源通配 | 容器资源通配与镜像资源通配互不冒充 | 已覆盖 | `../../../test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract` | 断言 entities 与 container/image resource_unrestricted 独立、直接 container:manage/bypass_resource、method wildcard 不放行、派生不落库。 |
| 验证码注册按成功提交确认 | 非法输入不消费有效验证码 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计并同步权限快照新增约束。 |
| 验证码注册按成功提交确认 | 成功后不可重用 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计并同步权限快照新增约束。 |

## 最近验证

- 时间：2026-10-24 17:30 +08:00
- 版本：4e6830dfa35e584d5232360d5c06b0ea0ed18f50（实现/测试提交）
- 主 spec SHA256：0AFC73999D5AD96E8E61E9F8BED6BDC691B41D664127B7DC5A9C4FEDA34B9CB0
- 命令与环境：WSL 离线 venv 根目录 `/home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest -q --no-header`
- 结果：1431 passed、0 failed、6 deselected、24 subtests passed（224.04s）；Node wire 另由 ../../../test/container/test_account_wire_contracts.py 覆盖（13 passed）。
- 限制：6 项 integration/legacy 按策略排除；权限快照由真实 FastAPI + SQLite 测试覆盖，未运行真实 MySQL；其余 users 场景本轮未审计。