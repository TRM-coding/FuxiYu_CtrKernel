# 已删除容器 mount 清理 — 收口合约

## Phase 8：mount 路径记录与定期清理

### 0. 常量定义 / 表结构定义

#### 0.1 Container 模型新增列

**文件**: `/home/wyw/FuxiYu_CtrKernel/models/containers.py`

```python
# 宿主机 bind mount 路径，磁盘检测时由 NodeKernel 返回并持久化
# 示例: /home/alice/containers/test_container/
bind_mount_path = db.Column(db.String(512), nullable=True)
```

#### 0.2 新表

**文件**: `/home/wyw/FuxiYu_CtrKernel/models/container_mount_cleanup.py`

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

| 字段 | 类型 | 空 | 说明 |
|---|---|---|---|
| `id` | PK | NOT NULL | 自增 |
| `container_id` | Integer | NOT NULL | 原容器 ID（容器已删，不设 FK） |
| `container_name` | String(120) | NOT NULL | 容器名，用于日志 |
| `machine_id` | Integer | NOT NULL | 宿主机 ID，清理时需要知道往哪个 Node 发请求 |
| `mount_path` | String(512) | NOT NULL | 宿主机路径，如 `/home/alice/containers/test/` |
| `escalation` | Boolean | NOT NULL | True = 冻结升级导致删除，False = 普通删除 |
| `removed_at` | DateTime | NOT NULL | 容器被删除的时间 |
| `cleaned_at` | DateTime | NULLABLE | mount 清理完成时间。NULL = 待清理 |

索引：
- `idx_mount_cleanup_pending` 联合索引 (`cleaned_at`, `removed_at`)：定期任务查 `cleaned_at IS NULL AND removed_at < cutoff` 高效走索引。

**模型注册**：在 `/home/wyw/FuxiYu_CtrKernel/models/__init__.py` 中导出。

#### 0.3 常量

**文件**: `/home/wyw/FuxiYu_CtrKernel/config.py`

```python
CONTAINER_MOUNT_CLEANUP_ENABLED = os.getenv(
    "CONTAINER_MOUNT_CLEANUP_ENABLED", "false"
).lower() == "true"
CONTAINER_MOUNT_CLEANUP_INTERVAL_SECONDS = int(
    os.getenv("CONTAINER_MOUNT_CLEANUP_INTERVAL_SECONDS", "86400")
)
CONTAINER_MOUNT_CLEANUP_AFTER_DAYS = int(
    os.getenv("CONTAINER_MOUNT_CLEANUP_AFTER_DAYS", "14")
)
```

---

### 1. 影响文件

| 文件 | 操作 | 说明 |
|---|---|---|
| `models/containers.py` | 改 | 新增 `bind_mount_path` 列 |
| `models/container_mount_cleanup.py` | **新建** | mount 清理追踪模型 |
| `models/__init__.py` | 改 | 导出新模型 |
| `repositories/containers_repo.py` | 改 | `update_container` allowed 集合追加 `bind_mount_path` |
| `repositories/container_mount_cleanup_repo.py` | **新建** | 插入记录 / 查询待清理 / 标记已清理 |
| `schemas/container_disk_check_task.py` | 改 | `_evaluate_limits` 持久化时写 `bind_mount_path`；`_handle_freeze_escalation` 插入 escalation=True 记录 + 立刻清理 |
| `schemas/container_mount_cleanup_task.py` | **新建** | 定期清理任务 |
| `services/container_tasks.py` | 改 | `remove_container` 末尾插入 MountCleanup 记录 |
| `config.py` | 改 | 新增 3 个配置项 |
| `FuxiYu_NodeKernel/network/api.py` | 改 | 新增 `POST /api/clean_mount` 端点 |

---

### 2. 完整数据流

#### 2.1 mount 路径来源：磁盘检测时持久化

```
定期任务 _evaluate_limits(container, usage)
  │ usage = container_tasks.get_container_disk_usage(container.id)
  │          → NodeKernel POST /check_disk_usage
  │          → 返回 { container: { bind_mount_path: "/home/alice/containers/test/" } }
  │
  ├─ containers_repo.update_container(
  │      container.id,
  │      ...,
  │      disk_overlay_rw_bytes=...,
  │      disk_bind_mount_bytes=...,
  │      disk_total_bytes=...,
  │      disk_limit_bytes=...,
  │      disk_checked_at=...,
  │      bind_mount_path=container_data.get("bind_mount_path"),   ← 新增
  │  )
  │
  └─ Container.bind_mount_path 落库
```

#### 2.2 容器删除时记录

```
remove_container(container_id)
  │ Node POST /remove_container
  │ DB: container 记录删除（或标记 OFFLINE）
  │
  └─ ──────── Phase 8 新增 ────────
     │
     ├─ bind_mount = container.bind_mount_path
     ├─ if bind_mount:
     │      mount_cleanup_repo.insert(
     │          container_id=container.id,
     │          container_name=container.name,
     │          machine_id=container.machine_id,
     │          mount_path=bind_mount,
     │          escalation=False,
     │          removed_at=utcnow,
     │      )
     │
     └─ （14 天后由定期任务清理）
```

#### 2.3 冻结升级时立刻清理

```
_handle_freeze_escalation(container, usage, app, days_frozen)
  │
  ├─ remove_container(container.id)
  │
  └─ ──────── Phase 8 新增 ────────
     │
     ├─ bind_mount = container.bind_mount_path
     ├─ if bind_mount:
     │      # 记录（立刻标记已清理）
     │      mount_cleanup_repo.insert(
     │          container_id=container.id,
     │          container_name=container.name,
     │          machine_id=container.machine_id,
     │          mount_path=bind_mount,
     │          escalation=True,
     │          removed_at=utcnow,
     │          cleaned_at=utcnow,
     │      )
     │      # 向 NodeKernel 发起清理
     │      machine_ip = get_machine_ip_by_id(container.machine_id)
     │      url = f"https://{machine_ip}:5789/api/clean_mount"
     │      payload = {"config": {"mount_path": bind_mount}}
     │      send(encryption(json.dumps(payload)), signature(...), url)
     │
     └─ print("[disk-check] escalation mount cleaned: {bind_mount}")
```

#### 2.4 定期清理任务（14 天后普通删除的 mount）

```
container_mount_cleanup_task (daemon thread, interval=86400s)
  │
  ├─ 查询: SELECT * FROM container_mount_cleanup
  │         WHERE cleaned_at IS NULL
  │           AND escalation = False
  │           AND removed_at < utcnow - 14 days
  │
  └─ 对每条记录:
       │
       ├─ machine_ip = get_machine_ip_by_id(row.machine_id)
       ├─ url = f"https://{machine_ip}:5789/api/clean_mount"
       ├─ payload = {"config": {"mount_path": row.mount_path}}
       ├─ send(encryption(json.dumps(payload)), signature(...), url)
       │
       ├─ 成功 → repo 在显式 session 中设置 row.cleaned_at = utcnow 并 flush
       └─ 失败 → print 日志，不清除 cleaned_at（下次重试）
```

---

### 3. 函数收口

#### 3.1 `containers_repo.update_container` 扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/repositories/containers_repo.py`

在 `allowed` 集合中追加 `"bind_mount_path"`：

```python
allowed = {"name", "image", "machine_id", "container_status",
           "disk_overlay_rw_bytes", "disk_bind_mount_bytes", "disk_total_bytes",
           "disk_limit_bytes", "disk_checked_at",
           "bind_mount_path"}  # ← 新增
```

#### 3.2 Repository 新建

**新文件**: `/home/wyw/FuxiYu_CtrKernel/repositories/container_mount_cleanup_repo.py`

##### `insert(container_id, container_name, machine_id, mount_path, escalation, removed_at, cleaned_at=None) -> ContainerMountCleanup`

```
输入:  container_id: int, container_name: str, machine_id: int,
       mount_path: str, escalation: bool, removed_at: datetime,
       cleaned_at: datetime | None
输出:  ContainerMountCleanup (新建的记录)
内部:  row = ContainerMountCleanup(...); session.add(row); session.flush()
```

##### `list_pending(cutoff: datetime, limit: int = 100) -> list[ContainerMountCleanup]`

```
输入:  cutoff: datetime（removed_at 早于此时间的记录）
       limit: int
输出:  list[ContainerMountCleanup]
查询:  SELECT ... WHERE cleaned_at IS NULL
         AND escalation = False
         AND removed_at < cutoff
         ORDER BY removed_at ASC
         LIMIT :limit
```

##### `mark_cleaned(record_id: int) -> bool`

```
输入:  record_id: int
输出:  bool
内部:  row.cleaned_at = utcnow; session.flush()
```

#### 3.3 `_evaluate_limits` 扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py`

持久化磁盘快照时追加 `bind_mount_path`：

```
containers_repo.update_container(
    container.id,
    commit=True,
    disk_overlay_rw_bytes=int(overlay_rw),
    disk_bind_mount_bytes=int(bind_mount),
    disk_total_bytes=int(total_bytes),
    disk_limit_bytes=int(limit_bytes),
    disk_checked_at=datetime.utcnow(),
    bind_mount_path=container_data.get("bind_mount_path"),   ← 新增
)
```

#### 3.4 `_handle_freeze_escalation` 扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py`

在 `remove_container` 成功后追加 mount 立刻清理逻辑（见 2.3 数据流）。

#### 3.5 `remove_container` 扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/services/container_tasks.py`

在现有 `remove_container` 函数末尾（容器删除成功后），追加 MountCleanup 记录插入（见 2.2 数据流）。

#### 3.6 定期清理任务

**新文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_mount_cleanup_task.py`

```
run_mount_cleanup_once() → None

内部:
  1. cutoff = utcnow - timedelta(days=CONTAINER_MOUNT_CLEANUP_AFTER_DAYS)
  2. rows = mount_cleanup_repo.list_pending(cutoff)
  3. 对每条 row:
       a. machine_ip = get_machine_ip_by_id(row.machine_id)
       b. url = get_full_url(machine_ip, "/clean_mount")
       c. payload = {"config": {"mount_path": row.mount_path}}
       d. send(encryption(payload), signature(payload), url, timeout=10)
       e. 成功 → mount_cleanup_repo.mark_cleaned(row.id)
       f. 失败 → print 日志，继续下一条


start_mount_cleanup_scheduler(app, interval_seconds=86400) → Thread | None

  仅在 CONTAINER_MOUNT_CLEANUP_ENABLED=true 时启动。
  与现有 container_disk_check_scheduler 同一模式（daemon thread + stop_event）。
```

#### 3.7 NodeKernel 新端点

**文件**: `/home/wyw/FuxiYu_NodeKernel/network/api.py`

```
POST /api/clean_mount

入参（解密后）: { config: { mount_path: str } }
返回: { success: 1 } | { success: 0, error_reason: str }

内部:
  1. mount_path = config["mount_path"]
  2. 安全检查: mount_path 必须以 "/home/" 开头 AND 包含 "/containers/"
  3. subprocess.run(["rm", "-rf", mount_path], timeout=30)
  4. 成功 → { success: 1 }
     路径不存在 → { success: 1 }（幂等）
     权限不足 → { success: 0, error_reason: "permission_denied" }
     安全检查失败 → { success: 0, error_reason: "invalid_path" }
```

遵循现有端点加密/签名模式（与 `/check_disk_usage`、`/pause_container` 一致）。

---

### 4. 测试用例

#### 4.1 路径持久化

| 用例 | 描述 |
|---|---|
| `test_bind_mount_path_persisted_during_disk_check` | 磁盘检测时 NodeKernel 返回 bind_mount_path → Container 表记录更新 |
| `test_bind_mount_path_null_handled` | NodeKernel 不返回 bind_mount_path → 不写 None 值（update_container 跳过 None） |

#### 4.2 MountCleanup 记录

| 用例 | 描述 |
|---|---|
| `test_mount_cleanup_recorded_on_remove` | remove_container 成功 → MountCleanup 记录写入，escalation=False |
| `test_mount_cleanup_not_recorded_without_path` | 容器无 bind_mount_path → remove_container 不写 MountCleanup |
| `test_mount_cleanup_escalation_immediate` | 升级删除 → cleaned_at 立刻非空，escalation=True |

#### 4.3 定期清理任务

| 用例 | 描述 |
|---|---|
| `test_list_pending_returns_only_old_uncleaned` | list_pending(cutoff) 只返回 cleaned_at IS NULL AND removed_at < cutoff |
| `test_list_pending_excludes_escalation` | escalation=True 的记录不被 list_pending 返回（已立刻清理） |
| `test_mount_cleanup_task_skips_recent` | 删除不到 14 天 → 不在 pending 列表中 |
| `test_mount_cleanup_task_cleans_old` | 删除超过 14 天 → 发送 NodeKernel 清理请求 → mark_cleaned |
| `test_mount_cleanup_task_continues_on_failure` | 某条记录清理失败 → 不标记 cleaned → 下次重试 |
| `test_mount_cleanup_scheduler_disabled` | ENABLED=false → start 返回 None |

#### 4.4 NodeKernel 端点

| 用例 | 描述 |
|---|---|
| `test_clean_mount_success` | 有效路径 → rm -rf 被调用 → success=1 |
| `test_clean_mount_nonexistent_path` | 路径不存在 → success=1（幂等） |
| `test_clean_mount_security_reject` | mount_path 不以 /home/ 开头 → success=0, error_reason="invalid_path" |
| `test_clean_mount_security_no_containers` | mount_path 不含 /containers/ → 拒绝 |

#### 4.5 集成

| 用例 | 描述 |
|---|---|
| `test_escalation_sends_clean_mount_request` | 升级删除 → NodeKernel /api/clean_mount 被调用 |
| `test_escalation_clean_mount_failure_logged` | 清理请求失败 → 不崩溃，日志记录 |

---

### 5. 不修改的文件（本次）

- Container 模型其他逻辑
- Machine 模型
- LongTermContainer 模型
- 容器创建流程
- 容器 SSH 刷新任务
- 前端

---

## DDL

```sql
-- Container 表加列
ALTER TABLE containers ADD COLUMN bind_mount_path VARCHAR(512) NULL;

-- mount 清理追踪表
CREATE TABLE container_mount_cleanup (
    id              INTEGER      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    container_id    INTEGER      NOT NULL,
    container_name  VARCHAR(120) NOT NULL,
    machine_id      INTEGER      NOT NULL,
    mount_path      VARCHAR(512) NOT NULL,
    escalation      TINYINT(1)   NOT NULL DEFAULT 0,
    removed_at      DATETIME     NOT NULL,
    cleaned_at      DATETIME     NULL,
    INDEX idx_mount_cleanup_pending (cleaned_at, removed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```


