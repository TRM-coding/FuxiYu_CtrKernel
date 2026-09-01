# Plan: 容器磁盘用量检测与管控

> 2026-09 ??????????? `CONTAINER_*` / `ANNOUNCEMENT_*` env ??????????????????? `system_settings`??????? `settings_tasks.SETTING_DEFINITIONS` ????????? `settings_tasks.get_*` getter ???`.env.example` ?????? settings ????

## 方针

```
① 平台展示用量          ← 让用户和管理员看得见
② 快满时邮件提醒         ← soft limit，提前告知
③ 超限直接 docker pause ← hard limit，硬冻结
```

## Context

容器创建时不设磁盘限额。Docker overlay2 不支持 `--storage-opt size=`。

两路求和：`overlay2 可写层 (SizeRw)` + `bind mount 目录 (du -sb)`，两者互斥，相加即真实总占用。

docker pause 覆盖两路——cgroup freezer 冻结所有进程，bind mount 和 overlay2 都写不了。不需要 chattr +i。

---

## 数据模型

### 返回结构（Node → CtrKernel）

```json
{
    "success": 1,
    "machine_disk": { "total_gb": 512.0, "used_gb": 200.0, "free_gb": 312.0, "percent": 39.1 },
    "container": {
        "container_name": "container_A",
        "overlay_rw_bytes": 2147483648,
        "bind_mount_bytes": 16106127360,
        "bind_mount_path": "/home/userA/containers/container_A",
        "total_bytes": 18253611008
    }
}
```

---

## Phase 1：只读检测

### 1.1 NodeKernel — 两路求和

**文件**: `/home/wyw/FuxiYu_NodeKernel/services/container_service.py`

```python
def get_disk_usage(container_name: str) -> dict
```

| 路 | 方法 | 说明 |
|---|---|---|
| overlay2 | `container.attrs['SizeRw']` | Docker daemon 维护；null 时 fallback 到 `du -sb /var/lib/docker/overlay2/<id>/diff/` |
| bind mount | `du -sb <Source>` | 从 `attrs['Mounts']` 取 Destination=`/root` 的 Source |
| 宿主机 | `shutil.disk_usage("/home")` | 机器级 |

### 1.2 NodeKernel — 端点

**文件**: `/home/wyw/FuxiYu_NodeKernel/network/api.py`

```
POST /api/check_disk_usage
入参: { config: { container_name: "xxx" } }   ← 必填
返回: { success: 1, machine_disk: {...}, container: {...} }
```

遵循现有 `/container_last_ssh_time` 的加密/签名模式。

### 1.3 CtrKernel — 调用函数

**文件**: `/home/wyw/FuxiYu_CtrKernel/services/container_tasks.py`

```python
def get_container_disk_usage(container_id: int, timeout: float = 10.0) -> dict | None
```

严格遵循 `get_container_last_ssh_login_time()` 的模式。

### 1.4 CtrKernel — 定期任务

**新文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py`

参考当前 scheduler 模式：分页读取 DB 容器记录，消费 WSS 已落库的磁盘快照字段，不再并发请求 Node。

| 配置项 | 默认值 |
|---|---|
| `CONTAINER_DISK_CHECK_ENABLED` | `false` |
| `CONTAINER_DISK_CHECK_INTERVAL_SECONDS` | `900` |
| `CONTAINER_DISK_SOFT_LIMIT_PERCENT` | `80` |
| `CONTAINER_DISK_HARD_LIMIT_PERCENT` | `100` |

### 1.5 配置

**文件**: `/home/wyw/FuxiYu_CtrKernel/config.py`

```python
CONTAINER_DISK_CHECK_ENABLED = os.getenv("CONTAINER_DISK_CHECK_ENABLED", "false").lower() == "true"
CONTAINER_DISK_CHECK_INTERVAL_SECONDS = int(os.getenv("CONTAINER_DISK_CHECK_INTERVAL_SECONDS", "900"))
CONTAINER_DISK_SOFT_LIMIT_PERCENT = int(os.getenv("CONTAINER_DISK_SOFT_LIMIT_PERCENT", "80"))
CONTAINER_DISK_HARD_LIMIT_PERCENT = int(os.getenv("CONTAINER_DISK_HARD_LIMIT_PERCENT", "100"))
```

---

## Phase 2：合作者 home 归拢到 bind mount

### 原理

合作者的 `/home/{user}` 原本落在 overlay2 上——不受 bind mount 保护，容器删除即丢失。改为放在 bind mount 下，与 owner 数据同级。

```
改前:                               改后:
/home/alice/  (overlay2)            /root/.collaborators/alice/  (bind mount)
/home/bob/    (overlay2)            /root/.collaborators/bob/    (bind mount)
                                    /home/alice → /root/.collaborators/alice  (symlink)
                                    /home/bob   → /root/.collaborators/bob    (symlink)
```

宿主机实际位置：
```
/home/{owner}/containers/{name}[_suffix]/
├── (owner 原有数据)
└── .collaborators/
    ├── alice/              ← 持久化，随宿主机备份
    └── bob/                ← 持久化，随宿主机备份
```

### 为什么这是唯一同时满足所有条件的方案

```
                            新老兼容   动态加    不绕Docker   数据持久化
                            ────────   ──────    ──────────   ────────
.collaborators + symlink    ✅         ✅        ✅           ✅
预挂 /home                   ❌ 老的     ✅        ✅           ✅
stop + 加 mount             ✅         ❌ 停容器  ✅           ✅
nsenter mount               ✅         ✅        ❌           ✅
不处理（留在 overlay2）      ✅         ✅        ✅           ❌
```

### 代码改动

**文件**: `/home/wyw/FuxiYu_NodeKernel/services/container_service.py:add_collaborator()`

```bash
# 原来:
useradd -m -s /bin/bash {user_name}

# 改为:
mkdir -p /root/.collaborators
mkdir -p /root/.collaborators/{user_name}
useradd -M -d /root/.collaborators/{user_name} -s /bin/bash {user_name}
ln -s /root/.collaborators/{user_name} /home/{user_name}
chown -R {user_name}:{user_name} /root/.collaborators/{user_name}
```

**文件**: `/home/wyw/FuxiYu_NodeKernel/services/container_service.py:remove_collaborator()`

```bash
# 改为：不删数据，改名存档
ts=$(date +%Y%m%d%H%M%S)
mv /root/.collaborators/{user_name} /root/.collaborators/.legacy_{user_name}_$ts 2>/dev/null || true
userdel {user_name}
rm -f /home/{user_name}
```

数据不丢，root 自己决定何时清理：

```
/root/.collaborators/
├── alice/                              ← 在任
├── bob/                                ← 在任
└── .legacy_charlie_20260614153022/      ← 离任，root 可手动删
```

**文件**: `/home/wyw/FuxiYu_NodeKernel/services/container_service.py:update_role()` ROOT 分支

```bash
# 原来：userdel -r {user_name}   ← 会连带删家目录（在 bind mount 上）
# 改为：与 remove_collaborator 统一，mv 到 .legacy_
ts=$(date +%Y%m%d%H%M%S)
mv /root/.collaborators/{user_name} /root/.collaborators/.legacy_{user_name}_$ts 2>/dev/null || true
userdel {user_name}
rm -f /home/{user_name}
```

### 状态机安全分析

| 场景 | 结论 | 说明 |
|---|---|---|
| add → remove 正常生命周期 | ✅ | `.legacy_` 改名，不丢数据 |
| 同名重新 add | ✅ | Fuxi 统一用户体系下必定是同一人，新目录即空 |
| 合作者 → ROOT 易主 | ✅ | `--no-remove-home` 保留数据，root 自行处理 |
| ROOT → 降级（update_role 到 ADMIN/COLLABORATOR） | ✅ | 家目录不动，只改 sudo 权限 |
| docker rm 容器 | ✅ | 数据在宿主机持久化，路径隔离防撞名 |
| 跨容器同名 | ✅ | `{owner}/containers/{name}_suffix` 路径隔离 |
| docker pause 期间操作 | ⚠️ | `container.exec_run` 会 hang；CtrKernel 侧已有 `status != ONLINE` 拦截 |

### 兼容性

- `.collaborators` 点号前缀让 `ls /root` 默认不可见
- `.legacy_` 点号前缀 + 时间戳，审计可追溯
- 存量容器首次 `add_collaborator` 自动走新路径，无需迁移
- 已有合作者的存量容器：迁移需手动操作（稀有，手动搬迁即可）

### 与磁盘检测的关系

两者互不冲突，可以一起部署：
- `.collaborators` 使合作者数据从 `SizeRw` 路迁移到 `du -sb` 路
- 总和不变，检测结果一致
- 不管谁先部署，下一轮检测自动反映最新分布

---

## Phase 3：管控动作

### 3.1 分级响应

```
detect():
    total = overlay_rw_bytes + bind_mount_bytes
    usage_percent = total / limit * 100

    if usage_percent >= HARD_LIMIT:
        → docker pause（覆盖两路，进程全停）
        → 邮件: "容器磁盘已超限冻结，请联系管理员清理"

    elif usage_percent >= SOFT_LIMIT:
        → 邮件: "容器磁盘使用接近上限，请及时清理"

    else:
        → 只记录，不动作
```

### 3.2 新增端点

**文件**: `/home/wyw/FuxiYu_NodeKernel/network/api.py`

```
POST /api/pause_container
入参: { config: { container_name: "xxx", action: "pause"|"unpause" } }
返回: { success: 1 }
```

### 3.3 限额来源

初期：`limit = machine.disk_size_gb` / 该机器容器数（简单均分）。

后续可在 Container 模型加 `disk_size_gb` 字段实现 per-container 限额。

---

## Phase 4：前端展示

**文件**: `/home/wyw/FuxiYu_Web/src/components/ContainerDetailModal.jsx`

新增磁盘用量条：
```
磁盘用量:  ████████░░░░  8.5GB / 10GB (85%)
           写层: 2.0GB | 数据: 6.5GB
```

`/containers/get_container_detail_information` 返回值补充 `disk_usage` 字段。

---

## 不修改的文件

- Machine 模型
- Container 模型（Phase 3 后续再加 disk_size_gb）
- Container_info
- Docker 配置
- 容器创建流程

---

## 验证步骤

1. **Phase 1**：启用 `CONTAINER_DISK_CHECK_ENABLED=true`，观察日志确认两路数据
2. **Phase 2**：新建容器 → 加合作者 → ssh 登录 → `ls -la /home/` 确认符号链接 → 验证宿主机 `.collaborators/` 目录有数据
3. **Phase 3**：手动 `docker pause` 测试容器 → 验证无法 ssh/操作 → `docker unpause` 恢复 → 模拟写满触发自动 pause
4. **Phase 4**：前端确认磁盘用量展示正确

