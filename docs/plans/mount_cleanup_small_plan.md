# Plan: 已删除容器的 mount 清理

> 2026-09 ??????????? `CONTAINER_*` / `ANNOUNCEMENT_*` env ??????????????????? `system_settings`??????? `settings_tasks.SETTING_DEFINITIONS` ????????? `settings_tasks.get_*` getter ???`.env.example` ?????? settings ????

## 方针

```
① remove_container 时记录 mount 路径
② 普通删除 → 14 天后清理 mount
③ 冻结升级删除 → 立刻清理 mount（宽限期已是最后机会）
```

## 背景

容器删除（`remove_container`）只清 Docker 容器，宿主机 bind mount 目录（`/home/{owner}/containers/{name}/`）的数据保留不动。目前没有自动清理机制，磁盘空间只增不减。

`operation_logs` 表已有 `remove_container` 记录 + `created_at` 时间戳，可作为"何时删除"的权威时间源。但 mount 路径目前未持久化。

---

## 数据模型

### Container 模型新增字段

**文件**: `models/containers.py`

```python
bind_mount_path = db.Column(db.String(512), nullable=True)
```

- 来源：磁盘检测时 NodeKernel 返回的 `bind_mount_path`
- 在 `_evaluate_limits` 持久化磁盘快照时一并更新

### 新表：`container_mount_cleanup`

```python
class ContainerMountCleanup(db.Model):
    __tablename__ = "container_mount_cleanup"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, nullable=False)
    container_name = db.Column(db.String(120), nullable=False)
    machine_id = db.Column(db.Integer, nullable=False)
    mount_path = db.Column(db.String(512), nullable=False)
    escalation = db.Column(db.Boolean, nullable=False, default=False)
    removed_at = db.Column(db.DateTime, nullable=False)
    cleaned_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index("idx_mount_cleanup_pending", "cleaned_at", "removed_at"),
    )
```

| 字段 | 说明 |
|---|---|
| `container_id` | 原容器 ID（容器已删，不设 FK） |
| `mount_path` | 宿主机路径，如 `/home/alice/containers/test/` |
| `escalation` | True = 冻结升级导致删除（立即清理），False = 普通删除（14 天后清理） |
| `removed_at` | 删除时间 |
| `cleaned_at` | mount 清理完成时间。NULL = 待清理 |

---

## 影响文件

| 文件 | 操作 |
|---|---|
| `models/containers.py` | 新增 `bind_mount_path` 列 |
| `models/container_mount_cleanup.py` | **新建** 清理追踪模型 |
| `models/__init__.py` | 导出新模型 |
| `schemas/container_disk_check_task.py` | `_evaluate_limits` 持久化时更新 `bind_mount_path` |
| `services/container_tasks.py` | `remove_container` 末尾插入 `ContainerMountCleanup` 记录 |
| `schemas/container_disk_check_task.py` | `_handle_freeze_escalation` 插入 escalation=True 的记录 |
| `schemas/container_mount_cleanup_task.py` | **新建** 定期清理任务 |
| `config.py` | 新增配置项 |

---

## 配置

```python
CONTAINER_MOUNT_CLEANUP_ENABLED = os.getenv(
    "CONTAINER_MOUNT_CLEANUP_ENABLED", "false"
).lower() == "true"
CONTAINER_MOUNT_CLEANUP_INTERVAL_SECONDS = int(
    os.getenv("CONTAINER_MOUNT_CLEANUP_INTERVAL_SECONDS", "86400")
)  # 每天一次
CONTAINER_MOUNT_CLEANUP_AFTER_DAYS = int(
    os.getenv("CONTAINER_MOUNT_CLEANUP_AFTER_DAYS", "14")
)
```

---

## 函数收口

### 1. 记录 mount 路径（磁盘检测时）

`_evaluate_limits` 持久化磁盘快照时追加：

```python
containers_repo.update_container(
    ...,
    bind_mount_path=container_data.get("bind_mount_path"),
)
```

### 2. 记录删除（remove_container 时）

`remove_container` 成功删除容器后，追加：

```python
# 记录 mount 清理信息
bind_mount = getattr(container, 'bind_mount_path', None)
if bind_mount:
    row = ContainerMountCleanup(
        container_id=container.id,
        container_name=container.name,
        machine_id=container.machine_id,
        mount_path=bind_mount,
        escalation=False,
        removed_at=datetime.utcnow(),
    )
    session.add(row)
    session.flush()
```

### 3. 升级删除（冻结升级时，立刻清理）

`_handle_freeze_escalation` 中，`remove_container` 成功后立即清理 mount：

```python
# 升级删除：立刻清理 mount（宽限期已是最后机会）
container_tasks.remove_container(container.id)

# 记录 + 立刻清理
bind_mount = getattr(container, 'bind_mount_path', None)
if bind_mount:
    # 记录
    row = ContainerMountCleanup(
        container_id=container.id,
        container_name=container.name,
        machine_id=container.machine_id,
        mount_path=bind_mount,
        escalation=True,
        removed_at=datetime.utcnow(),
        cleaned_at=datetime.utcnow(),  # 立刻标记已清理
    )
    session.add(row)
    session.flush()
    # 异步清理 Node 端：rm -rf mount_path
    _async_clean_mount(container.machine_id, bind_mount, container.name)
```

### 4. 定期清理任务

**新文件**: `schemas/container_mount_cleanup_task.py`

```
遍历 ContainerMountCleanup
  WHERE cleaned_at IS NULL
    AND removed_at < utcnow - CONTAINER_MOUNT_CLEANUP_AFTER_DAYS
    AND escalation = False

对每条记录：
  1. 向对应 NodeKernel 发送清理请求
     POST /api/clean_mount { config: { mount_path: "..." } }
  2. 成功 → cleaned_at = now
     失败 → 记录日志，下次重试
```

### 5. NodeKernel 新端点（最小）

```
POST /api/clean_mount
入参: { config: { mount_path: "/home/alice/containers/test/" } }
内部: rm -rf <mount_path>（安全检查：路径必须以 /home/ 开头且包含 /containers/）
返回: { success: 1 }
```

---

## 与现有逻辑的关系

```
容器删除路径：
  
  普通清理 (cleanup_task)         冻结升级 (_handle_freeze_escalation)
  ─────────────────────            ──────────────────────────────────
  remove_container()               remove_container()
  → 写 operation_logs             → 写 operation_logs
  → 写 MountCleanup                → 写 MountCleanup
     (escalation=False)               (escalation=True, cleaned_at=now)
  → 14 天后清理 mount              → 立刻清理 mount
```

---

## 不修改的文件

- Container 模型主逻辑（只加一列）
- 容器创建流程
- LongTermContainer 模型
- 前端

---

## 测试用例

| 用例 | 描述 |
|---|---|
| `test_bind_mount_path_persisted_during_disk_check` | 磁盘检测时 `bind_mount_path` 写入 Container |
| `test_mount_cleanup_recorded_on_remove` | remove_container → MountCleanup 记录写入 |
| `test_mount_cleanup_escalation_immediate` | 升级删除 → cleaned_at 立刻非空 |
| `test_mount_cleanup_task_skips_recent` | 删除不到 14 天 → 不触发清理 |
| `test_mount_cleanup_task_cleans_old` | 删除超过 14 天 → 发送 NodeKernel 清理请求 |
| `test_mount_cleanup_task_only_pending` | cleaned_at 已有值 → 跳过 |
| `test_mount_cleanup_no_path_skips` | 容器无 bind_mount_path → 不写 MountCleanup |
| `test_clean_mount_endpoint_security` | NodeKernel 路径安全检查（非 /home/ 拒绝） |

---

## 验证步骤

1. 创建容器 → 跑一次磁盘检测 → 确认 `containers.bind_mount_path` 已写入
2. 删除容器 → 确认 `container_mount_cleanup` 有新记录
3. mock `removed_at` 为 15 天前 → 跑清理任务 → 确认 NodeKernel 收到清理请求
4. 触发冻结升级 → 确认 mount 被立刻清理

