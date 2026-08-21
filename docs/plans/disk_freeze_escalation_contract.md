# 容器磁盘超限冻结升级机制 — 收口合约

## Phase 5：冻结状态记录与升级（Freeze State & Escalation）

### 0. 常量定义 / 表结构定义

#### 0.1 新表

**文件**: `/home/wyw/FuxiYu_CtrKernel/models/container_disk_freeze_state.py`

```python
from ..extensions import db


class ContainerDiskFreezeState(db.Model):
    __tablename__ = "container_disk_freeze_state"

    container_id = db.Column(
        db.Integer,
        db.ForeignKey("containers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    first_frozen_at = db.Column(
        db.DateTime, nullable=False
    )
    grace_until = db.Column(
        db.DateTime, nullable=True
    )
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False
    )

    container = db.relationship("Container")
```

**字段语义**：

| 字段 | 类型 | 空 | 说明 |
|---|---|---|---|
| `container_id` | FK → containers.id | NOT NULL | 级联删除：容器删则记录一并清除 |
| `first_frozen_at` | DateTime | NOT NULL | 首次被 disk-check 冻结的时刻。写入后不再修改 |
| `grace_until` | DateTime | NULLABLE | 管理员解冻后允许超限使用的截止时间。NULL = 不在宽限期 |
| `created_at` | DateTime | NOT NULL | 记录创建时间（≈ `first_frozen_at`） |

**模型注册**：在 `/home/wyw/FuxiYu_CtrKernel/models/__init__.py` 中导出。

#### 0.2 常量

**文件**: `/home/wyw/FuxiYu_CtrKernel/config.py`

```python
CONTAINER_DISK_FREEZE_ESCALATION_DAYS = int(
    os.getenv("CONTAINER_DISK_FREEZE_ESCALATION_DAYS", "7")
)
CONTAINER_DISK_FREEZE_GRACE_DAYS = int(
    os.getenv("CONTAINER_DISK_FREEZE_GRACE_DAYS", "3")
)
CONTAINER_DISK_FREEZE_RESET_PERCENT = int(
    os.getenv("CONTAINER_DISK_FREEZE_RESET_PERCENT", "95")
)
```

---

### 1. 影响文件

| 文件 | 操作 | 说明 |
|---|---|---|
| `models/container_disk_freeze_state.py` | **新建** | 冻结状态模型 |
| `models/__init__.py` | 改 | 导出新模型 |
| `repositories/container_disk_freeze_state_repo.py` | **新建** | 冻结状态 CRUD |
| `schemas/container_disk_check_task.py` | 改 | 扩展 `_evaluate_limits`，新增 `_handle_freeze_escalation` |
| `config.py` | 改 | 新增 3 个配置项 |

---

### 2. 完整数据流

#### 2.1 首次冻结记录

```
定期任务 _evaluate_limits(container, usage)
  │ usage_percent >= HARD_LIMIT
  │ container IS long_term (response_enabled=True)
  │
  ├─ freeze_state_repo.upsert_first_frozen(container.id)
  │    │ INSERT INTO container_disk_freeze_state
  │    │   (container_id, first_frozen_at, created_at)
  │    │   VALUES (?, utcnow, utcnow)
  │    │ ON CONFLICT (container_id) DO NOTHING
  │    │ （已有记录时不更新 first_frozen_at）
  │
  ├─ 判断升级：days_frozen >= ESCALATION_DAYS (7)?
  │    ├─ Yes → _handle_freeze_escalation()
  │    │         ├─ 发送邮件："容器因磁盘超限冻结已满 N 天，已被清除"
  │    │         ├─ container_tasks.remove_container(container.id)
  │    │         │    → Node POST /remove_container
  │    │         │    → DB: container_status = OFFLINE
  │    │         │    → FreezeState 级联删除 (FK CASCADE)
  │    │         └─ 写操作日志 (reason="disk_freeze_escalation")
  │    │
  │    └─ No  → _handle_hard_limit()
  │              ├─ docker pause (已有逻辑)
  │              ├─ 发邮件 (已有逻辑)
  │              └─ DB: container_status = PAUSED (已有逻辑)
  │
  └─ （短期容器 response_enabled=False → 跳过所有动作）
```

#### 2.2 重置（容量回落）

```
定期任务 _evaluate_limits(container, usage)
  │ usage_percent < FREEZE_RESET_PERCENT (95%)
  │ （不区分长期/短期容器）
  │
  ├─ freeze_state_repo.reset(container.id)
  │    └─ DELETE FROM container_disk_freeze_state WHERE container_id = ?
  │
  └─ return（不再进入超限判断）
```

---

### 3. 函数收口

#### 3.1 Repository

**新文件**: `/home/wyw/FuxiYu_CtrKernel/repositories/container_disk_freeze_state_repo.py`

##### `get(container_id: int) -> ContainerDiskFreezeState | None`

```
输入:  container_id: int
输出:  ContainerDiskFreezeState | None
内部:  session.get(ContainerDiskFreezeState, int(container_id))
```

##### `upsert_first_frozen(container_id: int) -> ContainerDiskFreezeState`

```
输入:  container_id: int
输出:  ContainerDiskFreezeState（新建或已存在）
内部:
  1. existing = get(container_id)
  2. if existing: return existing  （first_frozen_at 不动）
  3. row = ContainerDiskFreezeState(
         container_id=int(container_id),
         first_frozen_at=datetime.utcnow(),
     )
  4. session.add(row); session.flush()
  5. return row
```

##### `reset(container_id: int) -> bool`

```
输入:  container_id: int
输出:  bool（True = 确实删除了记录，False = 本来就没有）
内部:
  1. row = get(container_id)
  2. if not row: return False
  3. session.delete(row); session.flush()
  4. return True
```

#### 3.2 `_evaluate_limits` 扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py`

在现有逻辑（持久化磁盘快照 → 判断 soft/hard limit）中插入以下步骤。完整流程：

```
_evaluate_limits(container, usage) → None

输入:  container: Container ORM 对象
       usage: dict {
           "container": {
               "overlay_rw_bytes": int,
               "bind_mount_bytes": int,
               "total_bytes": int
           }
       }
输出:  None（副作用：日志、DB 写入、NodeKernel 请求、邮件）

内部逻辑:
  1. 若 CONTAINER_DISK_CHECK_ENABLED=false → return

  2. 计算 usage_percent、soft_limit、hard_limit（已有）

  3. 持久化磁盘快照到 DB（已有）

  4. 构建 log_msg（已有）

  5. 判断长期容器 → response_enabled（已有，本次实现）

  ──────── Phase 5 新增 ────────

  6. 【重置检查】若 usage_percent < CONTAINER_DISK_FREEZE_RESET_PERCENT:
        freeze_state_repo.reset(container.id)
        print("[disk-check] freeze state reset ...")
        print("[disk-check] OK: ...")
        return   ← 不执行任何超限动作

  7. 【超限判断】若 usage_percent >= hard_limit:
        print("[disk-check] HARD LIMIT exceeded: ...")
        if not response_enabled:
            print("[disk-check] response disabled, skip action")
            return

        # 记录/确认冻结状态
        freeze_state = freeze_state_repo.upsert_first_frozen(container.id)

        # 宽限期检查（Phase 6 详述，此处仅占位）
        if freeze_state.grace_until and utcnow < freeze_state.grace_until:
            print("[disk-check] in grace period, skip action")
            return
        if freeze_state.grace_until:
            freeze_state.grace_until = None; session.flush()

        # 升级判断
        days_frozen = (utcnow - freeze_state.first_frozen_at).days
        if days_frozen >= CONTAINER_DISK_FREEZE_ESCALATION_DAYS:
            _handle_freeze_escalation(container, usage, _app, days_frozen)
        else:
            _handle_hard_limit(container, usage, _app)

  8. 【软限判断】elif usage_percent >= soft_limit:  （已有，不变）
  ...
```

#### 3.3 `_handle_freeze_escalation`（新增）

**文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py`

```
_handle_freeze_escalation(container, usage, app, days_frozen) → None

输入:  container: Container ORM 对象
       usage: dict（同上）
       config: Ctrl 配置对象
       days_frozen: int（已冻结天数，用于邮件内容）
输出:  None

内部逻辑:
  1. 获取 owner 邮箱:
       emails = container_tasks.get_container_root_owner_emails(container.id)

  2. 计算用量展示:
       total_gb = usage["container"]["total_bytes"] / 1024**3
       limit_gb = machine.disk_size_gb
       usage_pct = total_gb / limit_gb * 100

  3. 发送清除通知邮件（冷却: 同一容器 24h 内不重复）:
       subject = "伏羲平台 - 容器 {name} 因磁盘超限已被清除"
       content = (
           f"容器: {container.name}\n"
           f"磁盘用量: {total_gb:.1f}GB / {limit_gb:.1f}GB ({usage_pct:.0f}%)\n"
           f"已冻结天数: {days_frozen} 天\n"
           f"\n容器已被清除。如有疑问请联系管理员。\n"
       )
       for email in emails: send_mail(to=email, subject=subject, content=content)

  4. 删除容器:
       container_tasks.remove_container(container.id)
       （内部: Node POST /remove_container + DB 状态更新 + FreezeState 级联删除）

  5. 写操作日志:
       operation_log_repo.write(
           operation="remove_container",
           target_type="container",
           target_id=container.id,
           detail={"reason": "disk_freeze_escalation",
                   "days_frozen": days_frozen,
                   "usage": f"{total_gb:.1f}GB/{limit_gb:.1f}GB"}
       )
```

---

### 4. 测试用例

#### 4.1 Repository 层

| 用例 | 描述 |
|---|---|
| `test_get_returns_none_when_no_record` | 无记录时 `get()` 返回 None |
| `test_get_returns_record_when_exists` | 有记录时 `get()` 返回 `ContainerDiskFreezeState` |
| `test_upsert_creates_new_record` | 无记录 → `upsert_first_frozen` 新建，`first_frozen_at` 为当前时间 |
| `test_upsert_preserves_first_frozen_at` | 已有记录 → 再次调用，`first_frozen_at` 不变 |
| `test_reset_deletes_record` | `reset()` → 记录被删除，再次 `get()` 返回 None |
| `test_reset_returns_false_when_no_record` | 无记录 `reset()` → 返回 False |
| `test_reset_returns_true_when_record_deleted` | 有记录 `reset()` → 返回 True |

#### 4.2 `_evaluate_limits` 冻结与升级

| 用例 | 描述 |
|---|---|
| `test_first_frozen_recorded_on_hard_limit` | 长期容器首次超 hard limit → `upsert_first_frozen` 被调用，FreezeState 记录写入 |
| `test_first_frozen_not_updated_on_second_hit` | 第二次超限 → `first_frozen_at` 保持不变 |
| `test_escalation_after_7_days` | mock `first_frozen_at` 为 7 天前 + 仍超限 + 仍是长期 → `_handle_freeze_escalation` 被调用 |
| `test_escalation_not_triggered_before_7_days` | mock `first_frozen_at` 为 3 天前 → `_handle_hard_limit` 被调用，`_handle_freeze_escalation` 不被调用 |
| `test_escalation_not_triggered_for_short_term` | 冻结满 7 天但已切换为短期 → 不触发任何 handler（`response_enabled=false`） |
| `test_escalation_calls_remove_container` | 升级时 `container_tasks.remove_container` 被调用 |
| `test_escalation_sends_email` | 升级时邮件被发送 |
| `test_escalation_writes_operation_log` | 升级时操作日志被写入，reason="disk_freeze_escalation" |
| `test_escalation_email_cooled_down_24h` | 同一容器 24h 内不重复发升级邮件 |

#### 4.3 重置

| 用例 | 描述 |
|---|---|
| `test_freeze_state_reset_on_usage_below_95` | 容量回落 < 95% → FreezeState 记录删除 |
| `test_freeze_state_reset_works_for_short_term` | 短期容器（曾经长期被冻结）容量回落 < 95% → 状态清除 |
| `test_freeze_state_not_reset_on_usage_above_95` | 容量 96%（不满足 < 95%）→ 状态保留 |
| `test_reset_returns_early_no_further_action` | 重置后直接 return，不进入超限判断 |
| `test_freeze_state_survives_long_to_short_transition` | 切换为短期容器 → FreezeState 记录仍在，不清除 |
| `test_freeze_state_cascade_on_container_delete` | 容器被删 → FreezeState 级联删除，不残留 |

---

## Phase 6：宽限期（Grace Period）

### 0. 常量定义

无新增常量。复用 Phase 5 的 `CONTAINER_DISK_FREEZE_GRACE_DAYS`。

---

### 1. 影响文件

| 文件 | 操作 | 说明 |
|---|---|---|
| `repositories/container_disk_freeze_state_repo.py` | 改 | 新增 `set_grace`、`clear_grace` |
| `services/container_tasks.py` | 改 | `unpause_container()` 追加宽限期设置 |
| `schemas/container_disk_check_task.py` | 改 | `_evaluate_limits` 宽限期判断（Phase 5 已预留） |

---

### 2. 完整数据流

#### 2.1 管理员解冻 → 进入宽限期

```
API: POST /containers/unpause_container
  │
  ├─ container_tasks.unpause_container(container_id)
  │    │ 验证 token、权限、机器在线
  │    │ Node POST /pause_container { action: "unpause" }
  │    │ 心跳等待状态变更
  │    │
  │    │ ──────── Phase 6 新增 ────────
  │    │
  │    ├─ freeze_state = freeze_state_repo.get(container_id)
  │    ├─ if freeze_state:
  │    │      grace_days = app.config["CONTAINER_DISK_FREEZE_GRACE_DAYS"]
  │    │      freeze_state_repo.set_grace(container_id, grace_days)
  │    │      （设置 grace_until = utcnow + timedelta(days=grace_days)）
  │    │      print("[disk-check] grace period set until {grace_until}")
  │    │
  │    └─ return True
```

#### 2.2 宽限期内的磁盘检测

```
定期任务 _evaluate_limits(container, usage)
  │ usage_percent >= hard_limit
  │ container IS long_term
  │
  ├─ freeze_state = upsert_first_frozen(...)
  │
  ├─ if freeze_state.grace_until and utcnow < freeze_state.grace_until:
  │      print("[disk-check] in grace period, skip pause")
  │      return   ← 不 pause，不升级，不邮件
  │
  ├─ if freeze_state.grace_until:  （已过期）
  │      freeze_state_repo.clear_grace(container_id)
  │      继续往下走 → 升级判断 / pause
  │
  └─ ...
```

#### 2.3 宽限期到期后

```
宽限期到期（grace_until 已过） → 下次检测：
  │ clear_grace()
  │ 进入正常冻结/升级流程
  │
  ├─ days_frozen >= 7?
  │    ├─ Yes → _handle_freeze_escalation  （直接删除！宽限期内倒计时未停）
  │    └─ No  → _handle_hard_limit  （恢复 pause）
```

---

### 3. 函数收口

#### 3.1 Repository 新增函数

**文件**: `/home/wyw/FuxiYu_CtrKernel/repositories/container_disk_freeze_state_repo.py`

##### `set_grace(container_id: int, grace_days: int) -> bool`

```
输入:  container_id: int
       grace_days: int（宽限天数，来自 config）
输出:  bool（True = 设置成功，False = 无冻结记录，操作无意义）

内部:
  1. row = get(container_id)
  2. if not row: return False
  3. row.grace_until = datetime.utcnow() + timedelta(days=grace_days)
  4. session.flush()
  5. return True
```

##### `clear_grace(container_id: int) -> bool`

```
输入:  container_id: int
输出:  bool

内部:
  1. row = get(container_id)
  2. if not row or row.grace_until is None: return False
  3. row.grace_until = None
  4. session.flush()
  5. return True
```

#### 3.2 `unpause_container` 扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/services/container_tasks.py`

在现有 `unpause_container()` 函数末尾（NodeKernel 请求成功、状态更新完成之后），追加：

```python
# 磁盘超限冻结宽限期：管理员解冻后给予宽限
from ..repositories import container_disk_freeze_state_repo
freeze_state = container_disk_freeze_state_repo.get(container_id)
if freeze_state is not None:
    grace_days = AppConfig.get("CONTAINER_DISK_FREEZE_GRACE_DAYS", 3)
    container_disk_freeze_state_repo.set_grace(container_id, grace_days)
    print(
        f"[disk-check] grace period set for container {container_id} "
        f"({grace_days} days, until {freeze_state.grace_until})"
    )
```

**条件说明**：
- `freeze_state` 为 None → 容器从未被冻结过，不需要宽限期
- 容器存在但 `grace_until` 已有值（宽限期内再次解冻）→ set_grace 覆盖为新值 `now + 3d`，续期

#### 3.3 `_evaluate_limits` 宽限期判断

已在 Phase 5 的 `_evaluate_limits` 收口中详述（步骤 7 的宽限期分支）。

---

### 4. 测试用例

#### 4.1 Repository 层

| 用例 | 描述 |
|---|---|
| `test_set_grace_sets_grace_until` | `set_grace(1, 3)` → `grace_until` 设为 `utcnow + 3d` |
| `test_set_grace_returns_false_when_no_record` | 无冻结记录时 `set_grace` → 返回 False |
| `test_set_grace_overwrites_existing_grace` | 已有 `grace_until` → 再次 `set_grace` → 覆盖为新值 |
| `test_clear_grace_sets_null` | `clear_grace` → `grace_until` 变为 None |
| `test_clear_grace_returns_false_when_no_grace` | grace_until 本已是 None → `clear_grace` → 返回 False |

#### 4.2 `unpause_container` 宽限期入口

| 用例 | 描述 |
|---|---|
| `test_unpause_sets_grace_when_freeze_state_exists` | 有冻结记录 → unpause 后 `grace_until` 被设为 `now + 3d` |
| `test_unpause_does_not_set_grace_without_freeze_state` | 无冻结记录 → unpause 成功但不调 `set_grace`，无异常 |
| `test_unpause_extends_grace_when_already_in_grace` | 已在宽限期内 → 再次 unpause → `grace_until` 续期 |

#### 4.3 `_evaluate_limits` 宽限期行为

| 用例 | 描述 |
|---|---|
| `test_grace_period_skips_pause` | 宽限期内超 hard limit → `_handle_hard_limit` 不被调用 |
| `test_grace_period_skips_escalation` | 宽限期内 + 冻结已满 7 天 → `_handle_freeze_escalation` 不被调用 |
| `test_grace_expired_resumes_freeze` | mock grace_until 为过去 → `clear_grace` 被调用 → 正常走 `_handle_hard_limit` |
| `test_grace_expired_triggers_escalation_if_7_days` | grace_until 过期 + 冻结已满 7 天 → 走 `_handle_freeze_escalation` |
| `test_grace_cleared_on_usage_below_95` | 宽限期内容量回落 < 95% → `reset()` 删除整条记录（含 `grace_until`） |
| `test_multiple_unpause_extends_grace` | 宽限期内再解冻 → grace_until 延长，检测继续跳过 pause |

---

## Phase 7（后续可选）：运维可见性

> 非本次实现范围，备忘。

| 改动 | 说明 |
|---|---|
| 前端容器列表 | 冻结状态的容器展示"冻结中（N 天）"/"宽限中"标签 |
| 前端容器详情 | 展示 `first_frozen_at`、`grace_until`、距升级剩余天数 |
| API 返回值 | `get_container_detail_information` 补充 `disk_freeze_state` 字段 |
| 管理后台 | 手动清除冻结状态的操作入口（需权限控制） |

---

## 不修改的文件（本次）

- Container 模型（无需加列）
- Machine 模型
- LongTermContainer 模型
- Container_info
- 容器创建/删除/暂停的 NodeKernel 端点（复用现有 `/pause_container` `/remove_container`）
- 前端
- Docker 配置


