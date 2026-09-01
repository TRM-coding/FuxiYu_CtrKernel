# Plan: 磁盘超限冻结升级机制（Freeze Escalation）

> 2026-09 ??????????? `CONTAINER_*` / `ANNOUNCEMENT_*` env ??????????????????? `system_settings`??????? `settings_tasks.SETTING_DEFINITIONS` ????????? `settings_tasks.get_*` getter ???`.env.example` ?????? settings ????

## 方针

```
① 长期容器超限 → docker pause + 记录首次冻结时间
② 管理员解冻 → 3 天宽限期（不 pause），3 天后仍超限 → 再次冻结
③ 冻结满 7 天仍超限 + 仍是长期容器 → remove_container（升级清除）
④ 容量回落到 95% 以下 → 自动清除冻结状态（唯一重置途径）
⑤ 冻结状态跨长期/短期转换不重置（防绕开监管）
```

## Context

当前 Phase 3 已实现：
- 长期容器超 hard limit → docker pause + 邮件通知
- 非长期容器只检测不响应

但缺少升级机制：一个长期容器可以被无限期冻结而不被清除，占用机器资源。

本 Phase 5 补齐这个闭环：**冻结不是终点，7 天宽限期后仍未清理 → 直接删容器**。

---

## 数据模型

### 新表：`container_disk_freeze_state`

**文件**: `/home/wyw/FuxiYu_CtrKernel/models/container_disk_freeze_state.py`

```python
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

| 字段 | 说明 |
|---|---|
| `first_frozen_at` | 首次触发 hard limit 被冻结的时间。**设后不改**。 |
| `grace_until` | 管理员解冻后允许超限使用的截止时间。`None` 表示不在宽限期。到期后自动失效，恢复冻结。 |

- 记录的存在本身即表示"该容器当前处于冻结升级倒计时"。
- `first_frozen_at` 设后不改，升级倒计时**不受宽限期影响**（宽限只是暂停 pause，不重置 7 天死线）。
- `grace_until` 每次解冻重新设为 `now + 3 days`，多次解冻可续期。

### 状态机

```
                        首次超 hard limit
       ┌──────────┐    (长期容器 + response)     ┌──────────────┐
       │          │ ───────────────────────────→ │              │
       │  未冻结   │                             │  冻结倒计时   │
       │ (无记录)  │                             │  (有记录)     │
       │          │ ←─────────────────────────── │              │
       └──────────┘    容量回落 < 95% limit       └──────┬───────┘
            ↑                                           │
            │                              满 7 天 + 仍超限 + 仍是长期
            │                               (宽限期不阻断升级)
            │                                           │
            └───────────────────────────────────────────┘
                         remove_container


   ┌──────────────┐      管理员 unpause       ┌──────────────────┐
   │              │ ───────────────────────→  │                  │
   │  冻结倒计时   │                          │  宽限期内         │
   │  (有记录)     │                          │  (有记录,         │
   │  grace=None  │                          │   grace_until 有效)│
   │              │ ←──── 3 天到期 ────────── │                  │
   └──────────────┘      仍超限 → 恢复冻结     └──────────────────┘
          │                                            │
          │              容量回落 < 95%                │
          └───────────────────────────────────────────→ 未冻结（无记录）
```

关键约束：
- **唯一进入条件**：长期容器 + response enabled + 超 hard limit → `upsert_first_frozen`
- **唯一退出条件**：容量回落至 limit 的 95% 以下（不区分长期/短期）→ `reset`
- **升级条件**：冻结满 7 天 + 仍超 hard limit + 仍是长期容器（宽限期内也计天数）
- **宽限期进入**：管理员调用 `unpause_container` API + 容器存在冻结记录 → 设 `grace_until = now + 3d`
- **宽限期行为**：跳过 pause，但 7 天升级倒计时继续走。到期后若仍超限 → 恢复冻结
- **状态在长期↔短期转换中不重置**

---

## 配置

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

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `CONTAINER_DISK_FREEZE_ESCALATION_DAYS` | `7` | 冻结多少天后升级为删容器 |
| `CONTAINER_DISK_FREEZE_GRACE_DAYS` | `3` | 管理员解冻后允许超限使用的天数 |
| `CONTAINER_DISK_FREEZE_RESET_PERCENT` | `95` | 容量回落到此百分比以下时清除冻结状态 |

---

## 影响文件

| 文件 | 操作 |
|---|---|
| `/home/wyw/FuxiYu_CtrKernel/models/container_disk_freeze_state.py` | **新建** 模型 |
| `/home/wyw/FuxiYu_CtrKernel/models/__init__.py` | 导出新模型 |
| `/home/wyw/FuxiYu_CtrKernel/repositories/container_disk_freeze_state_repo.py` | **新建** Repository |
| `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py` | 扩展 `_evaluate_limits`：冻结记录、宽限判断、升级判断、重置判断 |
| `/home/wyw/FuxiYu_CtrKernel/services/container_tasks.py` | 扩展 `unpause_container`：解冻时设置 `grace_until` |
| `/home/wyw/FuxiYu_CtrKernel/config.py` | 新增 3 个配置项 |

---

## 函数收口

### 1. Repository

**新文件**: `/home/wyw/FuxiYu_CtrKernel/repositories/container_disk_freeze_state_repo.py`

```python
def get(container_id: int) -> ContainerDiskFreezeState | None
    """获取冻结状态，无记录返回 None。"""

def upsert_first_frozen(container_id: int) -> ContainerDiskFreezeState
    """
    记录首次冻结时间。
    - 已有记录：直接返回（first_frozen_at 不变，grace_until 不动）
    - 无记录：新建，first_frozen_at = now
    """

def set_grace(container_id: int, grace_days: int) -> bool
    """
    设置宽限期（管理员解冻时调用）。
    无冻结记录时返回 False（无意义操作）。
    grace_until = now + grace_days。
    """

def clear_grace(container_id: int) -> bool
    """清除宽限期（到期后恢复冻结时调用）。"""

def reset(container_id: int) -> bool
    """删除冻结记录（容量回落时调用）。返回是否确实删除了记录。"""
```

### 2. `_evaluate_limits` 扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py`

核心逻辑调整（伪代码）：

```python
def _evaluate_limits(container, usage):
    # ... 现有的限额计算、持久化、日志 ...

    # ── 重置检查（所有容器，不区分长期/短期）──
    reset_pct = CONTAINER_DISK_FREEZE_RESET_PERCENT  # default 95
    if usage_percent < reset_pct:
        if freeze_state_repo.reset(container.id):
            print(f"[disk-check] freeze state reset: container {container.id} "
                  f"usage {usage_percent:.1f}% < {reset_pct}%")
        # 重置后直接走 OK 分支，不再进入超限判断
        print(f"[disk-check] OK: {log_msg}")
        return  # ← 重要：重置后不再触发任何响应

    # ── 超限响应（仅长期容器）──
    if usage_percent >= hard_limit:
        print(f"[disk-check] HARD LIMIT exceeded: {log_msg}")
        if response_enabled:
            freeze_state = freeze_state_repo.upsert_first_frozen(container.id)

            # ── 宽限期检查 ──
            if freeze_state.grace_until and utcnow < freeze_state.grace_until:
                print(f"[disk-check] in grace period until {freeze_state.grace_until}, "
                      f"skip pause for container {container.id}")
                return  # 宽限期内：不 pause，不升级

            # 宽限期已过期，清除 grace_until
            if freeze_state.grace_until:
                freeze_state_repo.clear_grace(container.id)

            # ── 升级判断（宽限期不阻断）──
            days_frozen = (utcnow - freeze_state.first_frozen_at).days
            escalation_days = CONTAINER_DISK_FREEZE_ESCALATION_DAYS
            if days_frozen >= escalation_days:
                # 升级：删容器
                _handle_freeze_escalation(container, usage, _app, days_frozen)
            else:
                # 常规冻结：pause + 邮件
                _handle_hard_limit(container, usage, _app)
        else:
            print(f"[disk-check] response disabled, skip action")

    elif usage_percent >= soft_limit:
        if response_enabled:
            _handle_soft_limit(container, usage, _app)
        else:
            print(...)
    else:
        print(f"[disk-check] OK: {log_msg}")
```

### 3. `unpause_container` 扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/services/container_tasks.py`

在 `unpause_container()` 成功 unpause 后，追加：

```python
# 若容器存在冻结记录，设置 3 天宽限期
from ..repositories import container_disk_freeze_state_repo
freeze_state = container_disk_freeze_state_repo.get(container_id)
if freeze_state:
    grace_days = AppConfig.get("CONTAINER_DISK_FREEZE_GRACE_DAYS", 3)
    container_disk_freeze_state_repo.set_grace(container_id, grace_days)
    print(f"[disk-check] grace period set for container {container_id} "
          f"until {freeze_state.grace_until} ({grace_days} days)")
```

### 4. `_handle_freeze_escalation`（新增）

```python
def _handle_freeze_escalation(container, usage, app, days_frozen):
    """
    冻结满 7 天仍超限 → remove_container + 通知邮件。
    参照 _handle_hard_limit 的模式。
    """
    # 1. 发邮件："容器因磁盘超限冻结已满 N 天，已被清除"
    # 2. remove_container(container.id)
    # 3. 写操作日志（reason="disk_freeze_escalation"）
```

---

## 与现有逻辑的关系

```
_evaluate_limits:

  ① DISK_CHECK_ENABLED? ─── No → return
  ② 计算 usage_percent
  ③ 持久化磁盘快照到 DB（所有容器）
  ④ is_long_term? ─── No → response_enabled = False  ← 已有（本次已实现）
  
  ⑤ usage_percent < 95%? ─── Yes → reset 冻结状态 → return  ← 新增（最高优先级出口）
  
  ⑥ usage_percent >= hard_limit?
      └── response_enabled? (即长期容器)
           ├── upsert_first_frozen (记录/确认冻结)
           ├── grace_until 有效? ─── Yes → skip, return              ← 新增
           ├── grace_until 过期? ─── 清除 grace_until
           ├── days_frozen >= 7? ─── Yes → _handle_freeze_escalation (remove)  ← 新增
           └── No → _handle_hard_limit (pause)                                   ← 已有
  
  ⑦ usage_percent >= soft_limit?
      └── response_enabled? → _handle_soft_limit (mail)                         ← 已有

unpause_container:

  ① 正常 unpause 流程（NodeKernel 请求 + 心跳）
  ② 容器有 FreezeState 记录? → set_grace(container_id, 3d)                      ← 新增
```

关键点：
- **步骤⑤ 先于一切**：容量回落 < 95% → 全清，return。宽限期、冻结记录全部清除。
- **步骤⑥ 宽限期优先于升级判断**：在宽限期内，既不 pause 也不升级删除。
- **宽限期不阻断升级倒计时**：`first_frozen_at` 持续累积。宽限 3 天结束后若距首次冻结已满 7 天 → 直接升级删除。
- **步骤④ 先于步骤⑥⑦**：短期容器直接跳过所有响应，但冻结状态仍在（不会被清除，除非走到步骤⑤）。
- **步骤⑤ 对所有容器生效**：短期容器如果曾经是长期容器被冻结过，只有容量回落到 95% 以下才能清除。

---

## 防绕开分析

| 场景 | 行为 | 是否可绕开 |
|---|---|---|
| 超限被冻结 → 管理员解冻 | 进入 3 天宽限期，不 pause | — 管理员主动操作 |
| 宽限期内清理到 95% 以下 | 冻结状态清除，恢复正常 | — 这是正常出口 |
| 宽限期到期仍超限 | 恢复冻结（pause），倒计时继续 | 否 |
| 宽限期 + 冻结满 7 天仍超限 | 升级删除（宽限不阻断升级） | 否 |
| 重复解冻不清理 | 每次解冻续 3 天宽限，但 7 天死线不变 | 否（最多拖 7 天） |
| 超限被冻结 → 切换为短期容器 | 冻结状态保留，不再 pause 但也不清除 | 否（清除不了状态） |
| 超限被冻结 → 切换为短期 → 切换回长期 | 冻结倒计时从首次冻结起算，不会重置 | 否（时间不重置） |
| 短期容器被管理员解冻 | 无冻结记录，`set_grace` 返回 False | — 无操作 |
| 超限被冻结 → 清理到 95% 以下 | 冻结状态自动清除 | — 正常出口 |
| 超限被冻结 → 清理到 95% 以下 → 再次写满 | 重新冻结，first_frozen_at 重新计时 | — 新周期 |
| 容器被手动删除 | FK CASCADE 清除冻结记录 | — 正常 |

---

## 测试用例

### 核心冻结与升级

| 用例 | 描述 |
|---|---|
| `test_first_frozen_recorded_on_hard_limit` | 长期容器首次超 hard limit → FreezeState 记录写入，first_frozen_at 不为空 |
| `test_first_frozen_not_updated_on_second_hit` | 第二次超限 → first_frozen_at 保持不变 |
| `test_escalation_after_7_days` | 冻结满 7 天 + 仍超限 + 仍是长期 → remove_container 被调用 |
| `test_escalation_not_triggered_before_7_days` | 冻结 3 天 → 只 pause，不 remove |
| `test_escalation_not_triggered_for_short_term` | 冻结满 7 天但已切换为短期 → 不 remove（response_enabled=false） |
| `test_escalation_sends_email` | 升级删容器时发送通知邮件 |
| `test_escalation_writes_operation_log` | 升级动作写入操作日志（reason="disk_freeze_escalation"） |

### 宽限期

| 用例 | 描述 |
|---|---|
| `test_unpause_sets_grace_when_freeze_state_exists` | 管理员 unpause 有冻结记录的容器 → grace_until 被设为 now + 3d |
| `test_unpause_does_not_set_grace_without_freeze_state` | unpause 无冻结记录的容器 → 不设 grace_until，不报错 |
| `test_grace_period_skips_pause` | 宽限期内超 hard limit → 不触发 pause，不触发升级 |
| `test_grace_period_expired_resumes_freeze` | 宽限期到期 + 仍超限 → 恢复 pause |
| `test_grace_period_does_not_block_escalation` | 宽限 3 天后到期，但首次冻结已满 7 天 → 直接升级删除 |
| `test_multiple_unpauses_extend_grace` | 宽限期内再次 unpause → grace_until 续期为 now + 3d |
| `test_grace_cleared_on_usage_below_95` | 宽限期内容量回落 < 95% → 整条 FreezeState 记录删除 |

### 重置

| 用例 | 描述 |
|---|---|
| `test_freeze_state_reset_on_usage_below_95` | 容量回落 < 95% → FreezeState 记录删除（包括 grace_until） |
| `test_freeze_state_reset_works_for_short_term` | 短期容器（曾经长期被冻结）容量回落 → 状态清除 |
| `test_freeze_state_not_reset_on_usage_above_95` | 容量 96%（不满足 < 95%）→ 状态保留 |
| `test_freeze_state_survives_long_to_short_transition` | 切换为短期 → 冻结记录仍在 |
| `test_freeze_state_cascade_on_container_delete` | 容器被删 → FreezeState 级联删除 |

---

## 不修改的文件

- Container 模型（无需加字段）
- Machine 模型
- LongTermContainer 模型
- 容器创建/删除流程
- NodeKernel（无新端点，复用现有 `/pause_container` 和 `/remove_container`）
- 前端（后续可选：展示冻结倒计时）

---

## 验证步骤

1. **冻结记录**：创建长期容器 → 写满磁盘 → 等待检测周期 → 确认 `container_disk_freeze_state` 表有记录
2. **宽限期**：管理员 unpause → 确认 `grace_until` 字段被设置 → 下次检测超限不 pause → 3 天后再次检测确认恢复 pause
3. **升级删除**：mock `first_frozen_at` 为 7 天前 → 触发检测 → 确认 `remove_container` 被调用
4. **宽限不阻断升级**：mock `first_frozen_at` 为 7 天前 + 处于宽限期内 → 宽限到期后检测 → 直接升级删除
5. **重置**：mock `first_frozen_at` + 磁盘清理到 95% 以下 → 确认记录被删除
6. **短期不重置**：冻结后切换为短期容器 → 确认记录仍在；磁盘清理到 95% 以下 → 确认记录被清除

