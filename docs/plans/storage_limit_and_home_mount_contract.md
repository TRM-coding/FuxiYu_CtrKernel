# 容器磁盘用量检测与管控 — 收口合约

## Phase 1：只读检测（两路求和）

### 0. 常量定义

**文件**: `/home/wyw/FuxiYu_CtrKernel/config.py`

```python
CONTAINER_DISK_CHECK_ENABLED = os.getenv("CONTAINER_DISK_CHECK_ENABLED", "false").lower() == "true"
CONTAINER_DISK_CHECK_INTERVAL_SECONDS = int(os.getenv("CONTAINER_DISK_CHECK_INTERVAL_SECONDS", "900"))
```

### 1. 影响文件

| 文件 | 操作 |
|---|---|
| `/home/wyw/FuxiYu_NodeKernel/services/container_service.py` | 新增 `get_disk_usage()` |
| `/home/wyw/FuxiYu_NodeKernel/network/api.py` | 新增 `POST /api/check_disk_usage` |
| `/home/wyw/FuxiYu_CtrKernel/services/container_tasks.py` | 新增 `get_container_disk_usage()` |
| `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py` | **新建** 定期任务 |
| `/home/wyw/FuxiYu_CtrKernel/config.py` | 新增 2 个配置项 |
| `/home/wyw/FuxiYu_CtrKernel/__init__.py` | 启动 scheduler |

### 2. 完整数据流

```
CtrKernel (定期任务)
  │ 遍历 DB 容器列表，分页
  │ 对每个容器调用 get_container_disk_usage(container_id)
  │
  ├─ 查 DB: container → machine_id → machine_ip
  ├─ 构造 payload: {"config": {"container_name": "xxx"}}
  ├─ signature() + encryption()
  ├─ send() → POST http://{machine_ip}:5789/api/check_disk_usage
  │
  ▼
NodeKernel
  │ 解密 + 验签
  │ 提取 container_name
  │
  ├─ docker_client.containers.get(container_name)
  │   ├─ attrs['SizeRw']                    ← overlay2 可写层
  │   └─ attrs['Mounts'] → 找 /root 的 Source
  │       └─ subprocess: du -sb <Source>     ← bind mount 目录
  │
  ├─ shutil.disk_usage("/home")              ← 宿主机磁盘
  │
  └─ return {
        machine_disk: {total_gb, used_gb, free_gb, percent},
        container: {overlay_rw_bytes, bind_mount_bytes, bind_mount_path, total_bytes}
     }
```

### 3. 函数收口

#### 3.1 NodeKernel `get_disk_usage()`

**文件**: `/home/wyw/FuxiYu_NodeKernel/services/container_service.py`

```
输入:  container_name: str
输出:  dict {
          "machine_disk": { total_gb: float, used_gb: float, free_gb: float, percent: float },
          "container": {
              "container_name": str,
              "overlay_rw_bytes": int | None,
              "bind_mount_bytes": int | None,
              "bind_mount_path": str | None,
              "total_bytes": int
          }
      }
异常:  不抛。目录不存在/权限不足/超时 → 对应字段为 null + error 字段
```

**内部逻辑**:
1. `container = docker_client.containers.get(container_name)` → Docker SDK 取容器对象
2. `container.attrs['SizeRw']` → overlay2 可写层字节数；若为 null/0，fallback `du -sb /var/lib/docker/overlay2/<id>/diff/`
3. 遍历 `container.attrs['Mounts']`，取 `Destination == '/root'` 的 `Source` → `subprocess.run(["du", "-sb", source], timeout=10)` → 解析输出
4. `shutil.disk_usage("/home")` → 转为 GB

#### 3.2 NodeKernel 端点

**文件**: `/home/wyw/FuxiYu_NodeKernel/network/api.py`

```
POST /api/check_disk_usage

入参:  { message: str, signature: str }
       解密后: { config: { container_name: str } }

返回:  { success: 1, machine_disk: {...}, container: {...} }
       { success: 0, error: str, error_reason: str }
```

与 `/container_last_ssh_time` 同模式的加密/签名/错误处理。

#### 3.3 CtrKernel `get_container_disk_usage()`

**文件**: `/home/wyw/FuxiYu_CtrKernel/services/container_tasks.py`

```
输入:  container_id: int, timeout: float = 10.0
输出:  dict | None
异常:  网络错误 → None，Node 错误 → _raise_on_node_error()
```

参考 `get_container_last_ssh_login_time()` 的实现模式。

#### 3.4 定期任务

**新文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py`

```
start_container_disk_check_scheduler(app, interval_seconds=900)
  → Threading.Thread (daemon)
  → 首次立即执行，之后每隔 interval_seconds
  → 仅在 CONTAINER_DISK_CHECK_ENABLED=true 时启动

check_all_containers_disk_usage_once(page_size=200)
  → 分页遍历 containers_repo.list_containers()
  → parallel_node_calls() 并发查询
  → 只 print 日志，不做限制操作
```

参考 `container_ssh_refresh_task.py` 的 scheduler 模式。

### 4. 测试用例

| 用例 | 描述 |
|---|---|
| `test_get_disk_usage_online` | mock Docker SDK 返回正常 attrs，验证两路求和正确 |
| `test_get_disk_usage_size_rw_null` | `SizeRw` 为 null，验证 fallback 到 du overlay2 diff |
| `test_get_disk_usage_no_bind_mount` | 容器无 `/root` bind mount，验证 bind_mount_bytes 为 null |
| `test_get_disk_usage_container_not_found` | Docker SDK 抛 NotFound，验证返回 error 不抛异常 |
| `test_get_disk_usage_du_timeout` | mock subprocess 超时，验证不抛异常、返回 error 字段 |
| `test_endpoint_check_disk_usage` | 发加密请求到 `/api/check_disk_usage`，验证返回格式 |
| `test_endpoint_missing_container_name` | 不传 container_name，验证 400 + missing_container_name |
| `test_endpoint_invalid_signature` | 签名错误，验证 401 |
| `test_ctrl_get_container_disk_usage` | monkeypatch send()，验证解析 Node 返回值 |
| `test_scheduler_enabled` | `ENABLED=true`，验证 scheduler 启动并执行一次 |
| `test_scheduler_disabled` | `ENABLED=false`，验证 scheduler 不启动 |

---

## Phase 2：合作者 home 归拢到 bind mount

### 0. 常量定义

无新增常量。

### 1. 影响文件

| 文件 | 操作 |
|---|---|
| `/home/wyw/FuxiYu_NodeKernel/services/container_service.py` | 改 `add_collaborator()`、`remove_collaborator()`、`update_role()` |

### 2. 完整数据流

```
add_collaborator:
  CtrKernel → Node POST /api/add_collaborator
    → container.exec_run:
        mkdir -p /root/.collaborators/{user_name}
        useradd -M -d /root/.collaborators/{user_name} -s /bin/bash {user_name}
        ln -s /root/.collaborators/{user_name} /home/{user_name}
        chown -R {user_name}:{user_name} /root/.collaborators/{user_name}

remove_collaborator:
  CtrKernel → Node POST /api/remove_collaborator
    → container.exec_run:
        ts=$(date +%Y%m%d%H%M%S)
        mv /root/.collaborators/{user_name} /root/.collaborators/.legacy_{user_name}_$ts
        userdel {user_name}
        rm -f /home/{user_name}

update_role → ROOT:
  CtrKernel → Node POST /api/update_role
    → container.exec_run:
        ts=$(date +%Y%m%d%H%M%S)
        mv /root/.collaborators/{user_name} /root/.collaborators/.legacy_{user_name}_$ts
        userdel {user_name}
        rm -f /home/{user_name}
        echo 'root:{user_name}123' | chpasswd
```

### 3. 函数收口

#### 3.1 `add_collaborator()`

```
输入:  container_name: str, user_name: str, role: ROLE
输出:  bool
内部:  上述 mkdir + useradd -M + ln -s + chown
```

改动：`useradd -m` → `useradd -M -d /root/.collaborators/{name}` + `ln -s`，家目录从 overlay2 移到 bind mount。

#### 3.2 `remove_collaborator()`

```
输入:  container_name: str, user_name: str
输出:  bool
内部:  mv → .legacy_{name}_{timestamp} + userdel + rm -f /home/{name}
```

改动：`userdel -r` + `rm -rf` → `mv` 到 `.legacy_`（不删数据）。

#### 3.3 `update_role()` ROOT 分支

```
输入:  container_name: str, user_name: str, updated_role: ROLE.ROOT
输出:  bool
内部:  mv → .legacy_ + userdel + rm -f /home/{name} + chpasswd root
```

改动：`userdel -r` → 先 `mv .legacy_` 再 `userdel`（不加 `-r`）。

### 4. 测试用例

| 用例 | 描述 |
|---|---|
| `test_add_collaborator_new_path` | mock exec_run，验证命令包含 `/root/.collaborators/` 路径 |
| `test_add_collaborator_symlink` | 验证 `ln -s` 命令出现在 exec_run 中 |
| `test_add_collaborator_no_m_flag` | 验证 `useradd -M`（不大写 `-m`） |
| `test_remove_collaborator_legacy` | 验证 mv 到 `.legacy_` 而非 rm -rf |
| `test_remove_collaborator_rm_symlink` | 验证 `rm -f /home/{name}` 清理符号链接 |
| `test_update_role_root_legacy` | 验证 ROOT 分支也走 `.legacy_` 改名 |
| `test_update_role_root_no_r` | 验证 `userdel` 不带 `-r` |

---

## Phase 3：管控动作

### 0. 常量定义

**文件**: `/home/wyw/FuxiYu_CtrKernel/config.py`

```python
CONTAINER_DISK_SOFT_LIMIT_PERCENT = int(os.getenv("CONTAINER_DISK_SOFT_LIMIT_PERCENT", "80"))
CONTAINER_DISK_HARD_LIMIT_PERCENT = int(os.getenv("CONTAINER_DISK_HARD_LIMIT_PERCENT", "100"))
```

### 1. 影响文件

| 文件 | 操作 |
|---|---|
| `/home/wyw/FuxiYu_NodeKernel/network/api.py` | 新增 `POST /api/pause_container` |
| `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py` | 扩展检测逻辑，加入 soft/hard 判断 |
| `/home/wyw/FuxiYu_CtrKernel/config.py` | 新增 2 个配置项 |

### 2. 完整数据流

```
定期任务 detect():
  total_bytes = overlay_rw_bytes + bind_mount_bytes
  limit_bytes = machine.disk_size_gb / container_count_on_machine  (初期均分)
  usage_percent = total_bytes / limit_bytes * 100

  if usage_percent >= HARD_LIMIT_PERCENT (100):
      → Node POST /api/pause_container { action: "pause" }
      → 发邮件: "容器磁盘已超限冻结"

  elif usage_percent >= SOFT_LIMIT_PERCENT (80):
      → 发邮件: "容器磁盘接近上限，请清理"

  else:
      → 只记录日志
```

### 3. 函数收口

#### 3.1 `POST /api/pause_container`

**文件**: `/home/wyw/FuxiYu_NodeKernel/network/api.py`

```
入参:  { config: { container_name: str, action: "pause" | "unpause" } }
返回:  { success: 1 }

内部:
  container = docker_client.containers.get(container_name)
  if action == "pause":   container.pause()
  if action == "unpause": container.unpause()
```

#### 3.2 定期任务扩展

**文件**: `/home/wyw/FuxiYu_CtrKernel/schemas/container_disk_check_task.py`

在 `check_all_containers_disk_usage_once()` 的逐容器循环中，`total_bytes` 获取后调用 `_evaluate_limits()`:

```
_evaluate_limits(container_id, total_bytes, machine_disk_size_gb, container_count):
  计算 usage_percent
  根据 SOFT/HARD 阈值决定：记录 | 发邮件 | pause
```

### 4. 测试用例

| 用例 | 描述 |
|---|---|
| `test_soft_limit_email` | mock 用量 85%，验证触发邮件发送 |
| `test_soft_limit_no_email` | mock 用量 70%，验证不触发邮件 |
| `test_hard_limit_pause` | mock 用量 105%，验证触发 docker pause |
| `test_hard_limit_email` | mock 用量 105%，验证同时发送硬限邮件 |
| `test_endpoint_pause` | 发请求到 `/api/pause_container`，验证 container.pause() 被调用 |
| `test_endpoint_unpause` | 发请求到 `/api/pause_container` action=unpause，验证 container.unpause() |

---

## Phase 4：前端展示

### 0. 常量定义

无新增常量。

### 1. 影响文件

| 文件 | 操作 |
|---|---|
| `/home/wyw/FuxiYu_Web/src/components/ContainerDetailModal.jsx` | 新增磁盘用量展示 |
| `/home/wyw/FuxiYu_CtrKernel/services/container_tasks.py` | `get_container_detail_information()` 补充 disk_usage |

### 2. 完整数据流

```
前端 ContainerDetailModal
  │ 请求 /api/containers/get_container_detail_information
  ▼
CtrKernel
  │ 查 DB → container 基本信息
  │ 调用 get_container_disk_usage(container_id) → Node
  ▼
前端渲染:
  磁盘用量:  ████████░░░░  8.5GB / 10GB (85%)
             写层: 2.0GB | 数据: 6.5GB
```

### 3. 函数收口

#### 3.1 CtrKernel `get_container_detail_information()` 扩展

在返回值中追加 `disk_usage` 字段：

```
返回 dict 新增: {
    "disk_usage": {
        "overlay_rw_gb": float,
        "bind_mount_gb": float,
        "total_gb": float,
        "limit_gb": float,
        "usage_percent": float
    }
}
```

`limit_gb` 初期 = `machine.disk_size_gb / container_count_on_machine`。

#### 3.2 前端 `ContainerDetailModal.jsx`

在现有资源信息（CPU/内存/GPU/端口）下方加入磁盘用量条，显示 `total_gb / limit_gb` 和百分比。

### 4. 测试用例

| 用例 | 描述 |
|---|---|
| `test_detail_info_includes_disk` | 验证返回 dict 包含 disk_usage 字段 |
| `test_disk_usage_limit_zero` | limit=0 时前端不显示百分比避免除零 |
| `test_disk_usage_display_normal` | `total=5GB limit=10GB` → 显示 50% |
| `test_disk_usage_display_over` | `total=11GB limit=10GB` → 显示 110% 超限状态 |

