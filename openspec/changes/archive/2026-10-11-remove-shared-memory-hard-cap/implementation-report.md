# Implementation Report — remove-shared-memory-hard-cap

本文件记录本次 DSH 实施子代理的实际改动、行为变化与验证边界（含第一、二轮主审补修与确定性收尾）。**本实施会话未运行任何命令**（DSH Windows 沙箱 shell 全程 `SetNamedSecurityInfoW Win32 5` 失败，按授权不反复尝试、不提升权限），全部改动仅用文件工具完成；测试与 CLI 校验由父代理执行，运行证据见第 4 节。

## 1. 改动文件

| 文件 | 改动 |
| --- | --- |
| `services/machine_tasks.py` | `Update_machine` 第 565-636 行：移除固定 8GB 上限；输入契约（负数/不可解析/非整小数拒绝、整数字符串兼容）与**按实际落库状态**计算的组合不变量（有效 shared ≤ 有效 mem，显式 null 沿用当前记录） |
| `openspec/changes/.../specs/backend--table-machines/spec.md` | delta：ADDED Requirement（正文约 330 chars）+ 9 Scenario |
| `openspec/changes/.../specs/backend--table-containers/spec.md` | delta：MODIFIED Requirement + 双重上限 Scenario（保留原 Scenario） |
| `test/machine/test_machine_tasks_status.py` | 更新过时用例（原把 `9` 当非法值），新增服务层回归共 13 条 |
| `test/machine/test_machine_api_crud.py` | 新增真实服务路径 API 回归共 9 条（含 `max_memory_gb` 组合与显式 null 绕过场景） |
| `test/container/test_container_shared_memory_limit.py` | 新文件：创建容器双重上限 4 条 |
| `openspec/specs/backend--table-machines/spec.md` | 主 SPEC 同步：新增 Requirement（组合不变量 + 分层错误，正文与 delta 逐字一致）、Source references |
| `openspec/specs/backend--table-containers/spec.md` | 主 SPEC 同步：创建侧双重上限显式化 + Scenario |
| `openspec/changes/.../tasks.md` | 全部勾选（1.1-1.7、2.1），剩余 checkbox：0 |
| `openspec/changes/.../implementation-report.md` | 本文件 |

`repositories/containers_repo.py`、`schemas/machine.py`、`api/machine_api.py` **未改**：`validate_shared_request`(420-448) 已同时校验「≤机器 `max_shared_gb`」与「≤本次 `MEMORY`」，创建入口 `validate_create_params`→`creation.py::_validate_create_params` 原样上抛 `invalid_config`，无真实缺口。

## 2. 行为变化

改动前（`services/machine_tasks.py:565-599`）：`shared_size`/`shared_gb`/`max_shared_gb` 任一出现即取共享值，`ss < 0 or ss > 8` → `update_failed`（`out of range (0-8 GB)`）；仅当传入 `max_shared_gb` 时才与目标内存上限比较。

改动后（第 565-636 行）：
1. **8GB 硬码删除**：逐机器可配置，16GB 等更大合法值在内存上限内可保存。
2. **输入契约**：不可解析为整数 → `update_failed`；`ss < 0` → `update_failed`；**非整小数（3.5）显式拒绝**（`no fractional part`），不再被 `int()` 静默截断成 3；整数字符串（`"16"`）与整值浮点（`16.0`）兼容；可写键 `max_shared_gb` 写库前归一成整数。**不扩张其它机器字段策略**（`max_memory_gb` 仍沿用原有 `int()` 语义）。
3. **组合不变量（一、二轮主审补修）**：只要本次更新携带共享上限**或**内存上限任一字段，就以**实际落库后的状态**计算有效值并校验 `有效 shared ≤ 有效 mem`——本次携带非 null 值取本次值；未携带**或显式传 null** 都沿用当前记录（`exclude_unset` 会把显式 null 送进服务层，而仓库层除 `port` 外一律跳过 None、不执行清空，所以 null 的落库结果就是原值）。因此「只下调 `max_memory_gb`」「`{max_shared_gb: null, max_memory_gb: 8}`」「`{max_memory_gb: null, max_shared_gb: 40}`」都不能把记录推成 `shared > mem`；超限 → `update_failed`，**不静默改用户的值**、失败不落任何字段（含同请求其它字段）。
4. **NULL 空值语义（未知，不发明上限）**：当前记录该字段本身为 NULL 的旧记录跳过比较，不发明任何默认/全局上限；显式传 null 不改变该字段（仍为 NULL），因此仍按未知处理。**仓库层 NULL 契约未改**。
5. **校验先于写库与审计**：拒绝路径不写 `Update_machine` 审计行。
6. **错误边界准确区分**（SPEC 同一表述）：请求模型层非法值 → 400 + `invalid_payload`；服务层校验 → 422 `update_failed`（不是所有 API 错误的唯一原因）；容器创建侧越界 → `invalid_config`。Web 既有映射不受影响。

## 3. 新增/更新的回归（已写，未运行）

服务层 `test/machine/test_machine_tasks_status.py`
- `test_update_machine_rejects_non_integer_or_negative_shared_size`（`"bad"`、`-1`）——移除原参数 `9`。
- `test_update_machine_accepts_shared_above_8_within_memory`——32GB 内存 + 16GB 共享保存并落库。
- `test_update_machine_rejects_max_shared_greater_than_target_memory`、`test_update_machine_rejects_shared_above_current_memory`——共享越内存拒绝。
- `test_update_machine_rejects_fractional_shared_size`——3.5 拒绝且 DB 不变（不截断成 3）。
- `test_update_machine_accepts_integral_string_and_float_shared_size`——`"16"`、`12.0` 兼容并落库为整数。
- `test_update_machine_rejects_memory_lowered_below_existing_shared`——shared16/mem32 只降 mem=8（并夹带改名）→ 拒绝，两字段与机器名都不变。
- `test_update_machine_accepts_memory_lowered_to_existing_shared`——只降 mem 到 16（=shared）成功。
- `test_update_machine_accepts_equal_shared_and_memory_in_one_request`——同请求 shared=8/mem=8 成功。
- `test_update_machine_skips_comparison_when_memory_limit_is_null`——NULL 内存旧记录可设共享 16；显式传 null 内存仍为 NULL、按未知跳过、不拒绝。
- `test_update_machine_rejects_null_shared_with_memory_lowered`——现存 shared16/mem32 传 `{max_shared_gb: null, max_memory_gb: 8, machine_name: ...}` → 拒绝；落库后仍是 shared16/mem32，改名不落。
- `test_update_machine_rejects_null_memory_with_shared_raised`——现存 shared16/mem32 传 `{max_memory_gb: null, max_shared_gb: 40}` → 拒绝；两字段不变。

真实 API 路径 `test/machine/test_machine_api_crud.py`（未 monkeypatch `Update_machine`）
- `test_update_machine_api_saves_shared_above_8_within_memory`——200，DB 由 8 变 16。
- `test_update_machine_api_rejects_shared_above_memory`——422 + `update_failed` + `cannot be greater`，DB 不变。
- `test_update_machine_api_accepts_memory_lowered_to_shared`——只降 mem 到 16 → 200，两字段落库。
- `test_update_machine_api_accepts_equal_shared_and_memory`——mem=8/shared=8 → 200。
- `test_update_machine_api_rejects_memory_lowered_below_existing_shared`——shared16/mem32 只请求 mem=8 + 改名 → 422，两字段与名字都不变。
- `test_update_machine_api_rejects_null_shared_with_memory_lowered`——真实 API 传 `{max_shared_gb: null, max_memory_gb: 8, machine_name: ...}` → 422 `update_failed`；DB 仍是 shared16/mem32，改名不落。
- `test_update_machine_api_rejects_null_memory_with_shared_raised`——真实 API 传 `{max_memory_gb: null, max_shared_gb: 40}` → 422；DB 两字段不变。
- `test_update_machine_api_rejects_invalid_shared_input`（`-1`、`"bad"`、`3.5`）——400 + `invalid_payload`。

容器创建 `test/container/test_container_shared_memory_limit.py`
- `>8GB` 且两上限都没越 → 放行；越机器上限 / 越本次内存 → `invalid_config` 且带具体数值；`validate_create_params` 完整序列同样生效。

## 4. 未运行的验证与运行前静态核对

## 4. 验证证据与未完成项

- 已由父代理实测并接受（本实施会话未运行命令）：
  - **Ctrl strict：27/0 通过**。
  - **资源定向：107 passed**（机器两个测试文件 + `test/container/test_container_shared_memory_limit.py`）。
  - **Web 前后端联动：Windows 与 Linux 各 28 文件 / 156 测试全过**，整体验证四项资源需求（无 8GB 硬码、shared ≤ mem 组合、显式 null 沿用落库值、错误分层）。
  - **Ctrl 全套：1048 passed / 3 failed / 6 deselected**。3 个失败是基线旧测试引用仓库中并不存在的 `docs/testing.md`、`docs/testing_legacy_migration.md`、`test/README.md`（HEAD 确无），已按 Global Q31 记录；**属保留的基线限制，MUST NOT 声称 Ctrl 全套全绿**，也不得归因于本次 shared 逻辑。
- 未完成项：仅剩上述基线文档缺失（Global Q31）与下方漂移/Node 边界说明；本变更范围内的验收项已全部勾选（剩余 checkbox：0）。
- 静态核对（逐行走查，非执行结果）：
  - 硬件漂移路径（`snapshots.py::_persist_hardware_changes`）走 `machine_repo.update_machine`，不经过本次服务校验；仓库内无其它 Update_machine 调用携带 `max_memory_gb`（仅 `link.py` 传 `machine_status`）。
  - 缩短后的 Requirement 正文未丢失任何契约：shared ≤ mem 组合、显式 null 沿用实际落库、可解析整数且非负、无全局 8GB、400/422 分层、不部分写入；容器创建 `invalid_config` 与旧记录 NULL unknown 语义保留在 Scenario 中。
- 未做：未 archive，未 Git stage/commit/push，未动 hook/CI/.env/凭据，未生成 AGENT.md/AGENTS.md，未改 Web/Node/Global 与其它 Ctrl 业务文件。

## 5. 剩余问题（交主代理判断）

1. Ctrl 全套的 3 个失败为基线旧测试引用缺失文档（Global Q31），与本次改动无关，但**验收口径上不得表述为全绿**。
2. 硬件漂移（Node 上报内存缩水）经仓库层直接 trim `max_memory_gb`，可在 DB 留下 `max_shared_gb > max_memory_gb` 的既有状态；此后任何触碰共享/内存的 `Update_machine` 都会按新不变量拒绝，直到管理员把共享调回内存以内。这是既有漂移语义，本次**未改漂移路径**（避免越界改其它业务缺陷）；容器创建侧的 `shared ≤ 本次 MEMORY` 使其不产生实际超配。
3. Node 侧 `shm_size` 上限未触碰（属另一仓库）。
4. `shared_size`/`shared_gb` 旧键名仍不在 `MachineUpdateFields`、也不在仓库白名单（写了不落库），本次只保留其校验，未扩大键名收益。