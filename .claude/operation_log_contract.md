# 操作日志接入合约

## 基础设施（已完成）

| 组件 | 文件 |
|---|---|
| 表 `operation_logs` | MySQL 已建 |
| Model `OperationLog` | `models/operation_log.py` |
| Repo `write()` | `repositories/operation_log_repo.py` |

调用方式：
```python
from ..repositories.operation_log_repo import write as write_op_log
write_op_log(operator_user_id=..., operation="...", target_type="...", target_id=..., detail={...})
```

---

## 接入清单

### 容器操作（6 个接入点）

| # | 操作 | 文件:行号 | operator | 已接入 |
|---|---|---|---|---|
| 1 | `create_container` | `services/container_tasks.py` ~640 | ✅ 有 `operator_user_id` | ⬜ |
| 2 | `delete_container` | `services/container_tasks.py` ~717 | ✅ 有 `operator_user_id` / None=cleanup | ✅ |
| 3 | `pause_container` | `schemas/container_disk_check_task.py` ~261 | None → 系统 | ⬜ |
| 4 | `unpause_container` | `services/container_tasks.py` ~355 | ✅ 有 `operator_user_id` | ⬜ |
| 5 | `add_collaborator` | `services/container_tasks.py` ~871 | 从 API 传入 `operator_user_id` | ⬜ |
| 6 | `remove_collaborator` | `services/container_tasks.py` ~946 | 同上 | ⬜ |
| 7 | `set_long_term` | `services/container_tasks.py` ~832 | 同上 | ⬜ |
| 8 | `start_container` | `services/container_tasks.py` ~1097 | 同上 | ⬜ |
| 9 | `stop_container` | `services/container_tasks.py` ~1131 | 同上 | ⬜ |
| 10 | `restart_container` | `services/container_tasks.py` ~1162 | 同上 | ⬜ |

### 用户操作（4 个接入点，可选）

| # | 操作 | 文件 | operator |
|---|---|---|---|
| 11 | `register_user` | `services/user_tasks.py` Register | None → 匿名 |
| 12 | `delete_user` | `services/user_tasks.py` Delete_user | `operator_user_id` |
| 13 | `change_password` | `services/user_tasks.py` Change_password | 自操作 |
| 14 | `reset_password` | `services/user_tasks.py` Reset_password | 操作者 |

### 邮件操作（2 个接入点）

| # | 操作 | 文件 | operator |
|---|---|---|---|
| 15 | `send_cleanup_reminder` | `schemas/container_cleanup_task.py` ~96 | None | ✅ |
| 16 | `send_hard_limit_alert` | `schemas/container_disk_check_task.py` ~239 | None | ⬜ |

### 机器操作（4 个接入点，可选）

| # | 操作 | 文件 | operator |
|---|---|---|---|
| 17 | `add_machine` | `services/machine_tasks.py` | `operator_user_id` |
| 18 | `remove_machine` | `services/machine_tasks.py` | `operator_user_id` |
| 19 | `update_machine` | `services/machine_tasks.py` | `operator_user_id` |
| 20 | `add_machine_permission` | `services/machine_tasks.py` | `operator_user_id` |

---

## 接入模式

### Pattern A：API 传入 operator_user_id
```python
# 在 service 函数末尾（操作成功后）
write_op_log(
    operator_user_id=operator_user_id,  # 从 API token 解析
    operation="create_container",
    target_type="container",
    target_id=container_id,
    detail={"name": name, "machine_id": machine_id, "image": image},
)
```

### Pattern B：系统自动触发
```python
# 在 scheduler 的处理函数中
write_op_log(
    operator_user_id=None,  # 系统
    operation="pause_container",
    target_type="container",
    target_id=container.id,
    detail={"reason": "disk_hard_limit", "usage": f"{total_gb:.1f}GB"},
)
```

### Pattern C：匿名操作
```python
write_op_log(
    operator_user_id=None,  # 匿名
    operation="register_user",
    target_type="user",
    target_id=user_id,
    detail={"username": username, "email": email},
)
```

---

## 执行顺序建议

1. **容器操作 8 项**（P0，改动集中在 1 个文件 `container_tasks.py`）
2. **pause_container**（补充系统触发路径）
3. **用户操作**（P1，`user_tasks.py`）
4. **机器操作**（P1，`machine_tasks.py`）

每批改完跑一遍现有测试，确认不破坏。
