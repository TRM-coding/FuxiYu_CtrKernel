# 串行 NodeKernel 调用并发化 —— 重构契约

## 背景

CtrKernel 的前端请求路径中，`list_all_machine_bref_information` 和 `list_all_container_bref_information`
两个核心接口对每台机器/每个容器**串行**发起 HTTP 调用到 NodeKernel。
N 个实体产生 N 次网络往返，延迟线性叠加。

## NodeKernel 侧 — 已完成（2026-06-11）

| 文件 | 改动 | 效果 |
|------|------|------|
| `services/container_service.py:463-469` | `exec_run` 前检查容器状态，stopped/exited/dead 直接 return None | 停止容器的 SSH 刷新从 4-5s → 毫秒级 |
| `api/__init__.py:231-237` | SSH 检测 4 个 `exec_run`（ss/netstat/pgrep/ps）合并为 1 个 `\|\|` 链 | 运行中容器的 SSH 检测从最多 4 次 Docker roundtrip → 1 次 |
| `run.py:11` | `uvicorn.run()` 加 `threaded=True` | 防止慢请求阻塞其他请求排队 |

## 总体策略

- 工具层抽取一个轻量并发执行器 `parallel_node_calls`，接收 callable 列表，用 `ThreadPoolExecutor` 并行执行，
  统一处理超时与异常。
- 业务层逐个阶段将串行 `for` 循环改为通过该工具并发提交，保持原有单条调用逻辑不变。
- 每个阶段独立可回滚（feature flag 控制）。

---

## Phase 0：新增常量与工具函数

### 0.1 新增常量

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `NODE_REQUEST_POOL_SIZE` | `config.py` / `AppConfig` | `8` | 并发请求线程池最大线程数 |
| `NODE_PARALLEL_ENABLED_MACHINES` | `.env` 可控 | `true` | Phase 2 开关 |
| `NODE_PARALLEL_ENABLED_CONTAINERS` | `.env` 可控 | `true` | Phase 3 开关 |
| `NODE_PARALLEL_ENABLED_SSH_REFRESH` | `.env` 可控 | `true` | Phase 4 开关 |

### 0.2 新增工具函数 `parallel_node_calls`

**文件**：`utils/parallel.py`（新建）

**签名**：
```python
def parallel_node_calls(
    calls: list[Callable[[], T]],
    pool_size: int | None = None,
    timeout_per_call: float | None = None,
) -> list[T | Exception]:
```

**输入**：
- `calls`: 无参 callable 列表，每个 callable 内部完成一次 NodeKernel 请求并返回结果
- `pool_size`: 线程池大小，默认取 `AppConfig.NODE_REQUEST_POOL_SIZE`
- `timeout_per_call`: 单次调用超时秒数，`None` 表示不限（由 callable 内部自行控制）

**输出**：
- `list[T | Exception]`，与 `calls` 顺序一致。成功返回业务结果，失败返回对应的 Exception 对象

**内部逻辑**：
1. `ThreadPoolExecutor(max_workers=pool_size)` 创建线程池
2. 对每个 callable 调用 `executor.submit(c)`
3. `concurrent.futures.as_completed()` 收集结果，通过 index 映射回原始顺序
4. 每个 future 通过 `future.result(timeout=timeout_per_call)` 获取，超时或异常统一捕获为 Exception
5. 返回按原始顺序排列的结果列表
6. 线程池在 with 块结束时自动 shutdown

**测试用例**：
- `test_parallel_all_success`: 3 个快速 callable 全部成功，验证顺序不变
- `test_parallel_partial_failure`: 其中一个 callable 抛异常，验证异常不中断其他调用
- `test_parallel_timeout`: 设置 timeout_per_call=0.5，其中一个 callable sleep 5s，验证超时返回 Exception
- `test_parallel_empty_calls`: 空列表输入，返回空列表
- `test_parallel_pool_size_limit`: 100 个 callable、pool_size=4，验证最多同时 4 线程执行

**测试文件**：`test/utils/test_parallel.py`（新建）

---

## Phase 1：机器列表并发化 `List_all_machine_bref_information`

### 1.1 影响文件

| 文件 | 改动类型 |
|------|----------|
| `services/machine_tasks.py` | 重构 `List_all_machine_bref_information` |
| `utils/parallel.py` | 新增 `parallel_node_calls` |
| `config.py` | 新增常量 |
| `test/services/test_machine_tasks_concurrency.py` | 新建测试 |

### 1.2 完整数据流（改后）

```
api/machine_api.py
  └─ list_all_machine_bref_information_api()
       │ 解析 request JSON → page_number, page_size, token, ...
       │ 验 token
       └─ MachineTasks.List_all_machine_bref_information(page_number, page_size, user_id=...)
            │
            ├─ 1. DB 查询：Machine.query.filter().order_by().limit().offset()
            │   返回 machines: list[Machine]
            │
            ├─ 2. 并发可达性检查（改动点）：
            │    machines → list[_machine_online_check_lambda(machine)] → parallel_node_calls()
            │    返回 results: list[bool | Exception]
            │    每个元素：True/False 表示 online，Exception 表示网络/超时异常
            │
            ├─ 3. 状态同步（逐条，与改前一致）：
            │    for machine, online in zip(machines, results):
            │      if isinstance(online, Exception): online = False
            │      比较 current_status_val，update_machine / _mark_containers_offline
            │
            └─ 4. 组装返回值（与改前一致）
```

### 1.3 函数级收口

#### 1.3.1 新增辅助函数 `_node_probe_machine`

**签名**：
```python
def _node_probe_machine(machine_id: int) -> bool:
```

**输入**：`machine_id: int`

**输出**：`bool` — True 表示 NodeKernel `/machine_status` 返回 online

**内部逻辑**：
- 调用现有 `is_machine_online_remote(machine_id, timeout=2.0)`
- 等价于原 `for` 循环体内 `online = is_machine_online_remote(...)` 的单次调用

**设计理由**：封装为无参 lambda 以适配 `parallel_node_calls`，同时保留原逻辑完整。

#### 1.3.2 改动函数 `List_all_machine_bref_information`

**当前逻辑**（第 320-381 行）：
```python
for machine in machines:
    online = is_machine_online_remote(machine.id, timeout=2.0)  # 串行 HTTP
    # ... 状态同步逻辑 ...
```

**改后逻辑**：
```python
# 阶段 A：并发收集所有机器的可达性
_callables = [
    lambda mid=m.id: _node_probe_machine(mid)
    for m in machines
]
_probe_results = parallel_node_calls(_callables, timeout_per_call=3.0)

# 阶段 B：逐条同步状态（纯本地操作，不需要并发）
for machine, probe_result in zip(machines, _probe_results):
    online = probe_result if isinstance(probe_result, bool) else False
    # ... 原状态同步逻辑不变 ...
```

**关键注意**：
- 状态同步（DB update）仍为串行，避免 SQLAlchemy session 并发问题
- `timeout_per_call=3.0` 比内部 `is_machine_online_remote(timeout=2.0)` 略大，给线程调度留余量
- 如果 `NODE_PARALLEL_ENABLED_MACHINES` 为 `false`，回退到原串行逻辑

### 1.4 测试用例

**文件**：`test/services/test_machine_tasks_concurrency.py`

| 用例 | 构造 | 预期 |
|------|------|------|
| `test_concurrent_all_online` | mock `is_machine_online_remote` 返回 True，3 台机器 | `parallel_node_calls` 被调用，3 台全部 online，响应时间 < 串行 3× |
| `test_concurrent_partial_timeout` | mock 其中一台机器的 `send()` sleep 3s（超过 timeout=2.0），其余正常 | 超时那台返回 False，其余正常，总时间 ≈ max(各调用耗时) 而非 sum |
| `test_concurrent_all_timeout` | mock 全部超时 | 全部返回 False，触发 _mark_containers_offline |
| `test_feature_flag_off` | `NODE_PARALLEL_ENABLED_MACHINES=false` | 回退到原串行逻辑，`parallel_node_calls` 不被调用 |
| `test_empty_machine_list` | machines=[] | 返回空列表，不抛异常 |
| `test_thread_pool_exhaustion` | 50 台机器，pool_size=8 | 所有结果正确，线程池不会死锁 |
| `test_status_sync_still_serial` | 3 台机器，其中 2 台从 online→offline | 验证 `update_machine` 被调用了正确次数，容器状态正确联动 |

---

## Phase 2：容器列表并发化 `list_all_container_bref_information`

### 2.1 影响文件

| 文件 | 改动类型 |
|------|----------|
| `services/container_tasks.py` | 重构 `list_all_container_bref_information` |
| `test/services/test_container_tasks_concurrency.py` | 新建测试 |

### 2.2 完整数据流（改后）

```
api/container_api.py
  └─ list_all_containers_bref_information_api()
       └─ container_tasks.list_all_container_bref_information(...)
            │
            ├─ 1. 权限过滤 + DB 分页查询（与改前一致）
            │   返回 containers: list[Container]
            │
            ├─ 2. 预过滤（与改前一致）：
            │    对每台 machine 判断 offline/maintenance → do_node_check=False
            │
            ├─ 3. 并发状态查询（改动点）：
            │    need_check = [c for c in containers if do_node_check and machine_ip]
            │    skip = [c for c in containers if not do_node_check or not machine_ip]
            │    _callables = [lambda c=c: _node_probe_container(c, machine_ip) for c in need_check]
            │    results = parallel_node_calls(_callables, timeout_per_call=12.0)
            │
            ├─ 4. 结果处理 + 404清理 + 状态持久化（逐条，与改前一致）
            │
            └─ 5. 组装 container_bref_information + 分页信息（与改前一致）
```

### 2.3 函数级收口

#### 2.3.1 新增辅助函数 `_node_probe_container`

**签名**：
```python
def _node_probe_container(container, machine_ip: str) -> dict | None:
```

**输入**：
- `container`: 容器 ORM 对象（含 `.id`, `.name`, `.machine_id` 等属性）
- `machine_ip`: 宿主机 IP 字符串

**输出**：`dict | None` — NodeKernel `/container_status` 的返回 dict，或 None（网络异常/超时）

**内部逻辑**：
- 封装现有的单次 `get_container_status(machine_ip, container.name)` 调用
- 将其从原 `for` 循环体（第 1226 行）提取为独立函数

#### 2.3.2 改动函数 `list_all_container_bref_information`

**当前逻辑**（第 1202-1291 行）：
```python
for container in containers:
    ...
    st = get_container_status(machine_ip, container.name)  # 串行 HTTP，timeout=5s + 2 次重试
    ...
```

**改后逻辑**：
```python
# 阶段 A：分离需要检查和不需检查的容器
need_check = []
skip = []
for container in containers:
    ...  # 现有 do_node_check / machine_ip 判断 ...
    if do_node_check and machine_ip:
        need_check.append((container, machine_ip))
    else:
        skip.append(container)

# 阶段 B：并发查询 NodeKernel
_callables = [
    lambda c=c, ip=ip: _node_probe_container(c, ip)
    for c, ip in need_check
]
_results = parallel_node_calls(_callables, timeout_per_call=12.0)

# 阶段 C：合并结果 + 逐条处理
result_map = {c.id: r for (c, _), r in zip(need_check, _results)}
for container in containers:
    if container in skip:
        st = None
    else:
        st = result_map.get(container.id)
    # ... 后续 404 处理、状态持久化、组装 info 不变 ...
```

**关键注意**：
- `timeout_per_call=12.0` 给足余量：内部 `get_container_status` 有 2 次重试 × 5s = 10.5s 最坏情况
- DB 写入（状态持久化、404 删除）保持串行，避免 SQLAlchemy session 竞态
- 如果 `NODE_PARALLEL_ENABLED_CONTAINERS` 为 `false`，回退到原串行逻辑

### 2.4 测试用例

**文件**：`test/services/test_container_tasks_concurrency.py`

| 用例 | 构造 | 预期 |
|------|------|------|
| `test_concurrent_all_online` | mock `get_container_status` 返回 online，10 容器 | 全部成功，总时间远小于 10× 单次耗时 |
| `test_concurrent_404_cleanup` | mock 其中 2 个返回 `{"status_code": 404}` | 触发 `remove_binding` + `delete_container`，不影响其他容器 |
| `test_concurrent_offline_machine_skip` | 部分容器的 machine 状态为 offline | 这些容器不发起 NodeKernel 调用 |
| `test_concurrent_partial_timeout` | mock 部分容器超时 | 超时返回 None，其余正常 |
| `test_feature_flag_off` | `NODE_PARALLEL_ENABLED_CONTAINERS=false` | 回退串行 |
| `test_db_write_still_serial` | mock 多个容器需要状态持久化 | `update_container` 调用次数正确，session 无异常 |

---

## Phase 3：后台 SSH 刷新并发化（低优先级）

### 3.1 影响文件

| 文件 | 改动类型 |
|------|----------|
| `schemas/container_ssh_refresh_task.py` | 重构 `refresh_all_containers_last_ssh_login_time_once` |
| `test/schemas/test_ssh_refresh_concurrency.py` | 新建测试 |

### 3.2 完整数据流（改后）

`refresh_all_containers_last_ssh_login_time_once(page_size=200)`：
1. 分页遍历全部容器（与改前一致）
2. 对每页的容器列表，使用 `parallel_node_calls` 并发调用 `get_container_last_ssh_login_time`
3. 异常处理保持逐条 try/except 不变

### 3.3 函数级收口

**改动函数**：`refresh_all_containers_last_ssh_login_time_once`（`schemas/container_ssh_refresh_task.py:6-33`）

**当前逻辑**：
```python
for c in containers:
    container_tasks.get_container_last_ssh_login_time(c.id)  # 串行
```

**改后逻辑**：
```python
_callables = [
    lambda cid=c.id: container_tasks.get_container_last_ssh_login_time(cid)
    for c in containers
]
_results = parallel_node_calls(_callables, timeout_per_call=8.0)
# 异常由 callable 内部捕获并 print，parallel_node_calls 只做超时兜底
```

### 3.4 测试用例

| 用例 | 构造 | 预期 |
|------|------|------|
| `test_concurrent_ssh_refresh_page` | mock 20 容器，部分 stopped 部分不存在 | 全部在并发窗口内完成 |
| `test_feature_flag_off` | `NODE_PARALLEL_ENABLED_SSH_REFRESH=false` | 回退串行 |

---

## Phase 4：（可选）heartbeat 类长轮询不变

`container_starting_status_heartbeat` 和 `start_machine_maintenance_transition_heartbeat`
已使用独立 `threading.Thread` 实现后台轮询，每次轮询仅涉及单个容器/机器，
不需要并发化改造。

---

## 回滚策略

每个 Phase 有独立 feature flag（`.env` 控制），出问题设置对应 flag 为 `false` 即可回退：

```
NODE_PARALLEL_ENABLED_MACHINES=false
NODE_PARALLEL_ENABLED_CONTAINERS=false
NODE_PARALLEL_ENABLED_SSH_REFRESH=false
```

## 风险与约束

1. **SQLAlchemy session 线程安全**：`parallel_node_calls` 内部仅执行 HTTP 调用，不持有 DB session。
   状态同步/DML 仍在主线程串行执行，避免 session 竞争。
2. **NodeKernel 瞬时压力**：并发数上限由 `NODE_REQUEST_POOL_SIZE` 控制（默认 8），
   不会对 NodeKernel 造成请求风暴。
3. **RSA 加密开销**：`send()` 内部的 RSA sign/encrypt 在各自线程中执行，
   多线程会短暂增加 CPU 压力（当前 4 核 37% idle，有充足余量）。
4. **原有错误语义不变**：每个 callable 的异常被捕获为 Exception 对象返回，
   调用方统一按 `isinstance(result, Exception)` 判错，等价于原串行 try/except。

