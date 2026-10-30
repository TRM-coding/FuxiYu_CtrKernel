# backend--table-machines Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: machines 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_get_detail_information_success
  - [X] test/machine/test_machine_repository_integration.py::test_update_machine_with_real_repository
  - [X] test/repository/test_anvil_machine_images.py::test_machine_model_roundtrip_preserves_columns_and_null_semantics
- Assertion scope: 既有用例按 id 读回详情与更新后的 machine_name，断言 status、containers、port 的读取口径。`[X]` 行核对 SQLite 往返的主键稳定、machine_name/machine_ip 唯一且非空、node_uid/node_cert_fingerprint 唯一且可空、port 与各类上限/GPU JSON 可空、machine_status/is_maintenance Python 默认落库，并核对数据附录列名与类型。
- Coverage note: 既有断言覆盖详情与仓库读取的部分字段；完整表级约束与空值语义见对应 `[X]` 行。

### Requirement: machines 生产职责与生命周期

#### Scenario: 维护或离线窗口

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_offline_window_adds_deferral_on_recovery
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_maintenance_window_opens_and_closes
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_deferral_applies_to_all_records_of_machine
  - [X] test/machine/test_machine_tasks_crud.py::test_register_machine_persists_identity_hardware_and_limits
  - [X] test/machine/test_machine_node_endpoint.py::test_register_blank_port_falls_back_and_stores_null
  - [X] test/machine/test_machine_tasks_crud.py::TestGpuAllowance::test_allow_list_length_wins
  - [X] test/machine/test_machine_tasks_status.py::test_apply_sys_snapshot_drift_updates_db_and_trims_limits
  - [X] test/machine/test_machine_tasks_status.py::test_apply_sys_snapshot_gpu_enum_updates_gpu_list_not_allow
  - [X] test/machine/test_cleanup_deferral_window.py::TestLastSeenHeartbeat::test_snapshot_batch_updates_last_seen
  - [X] test/machine/test_node_link.py::test_run_machine_link_marks_online_on_connect_offline_on_close
- Assertion scope: 注册写入 node_uid、证书指纹、硬件事实和资源上限；port 留空存 NULL；gpu_allow_list 决定许可上限；WSS 快照把 gpu_list 作为事实更新、允许列表保持人工维护，并写 last_seen_at；链路连接成功写 online、断开写 offline；离线/维护开窗，恢复时给该机器全部 SSH 记录累加 deferral。Requirement 正文的 Node 注册固定 uid/证书、端口空值、GPU 事实/许可与 WSS 更新由这些断言覆盖。

### Requirement: machines 共享内存上限为机器可配置限额

#### Scenario: 超过 8GB 但在内存上限内可保存

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_accepts_shared_above_8_within_memory
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_saves_shared_above_8_within_memory
- Assertion scope: 32GB 内存的机器通过服务层和真实 API 把 max_shared_gb 从 8GB 更新为 16GB 均成功并落库，不再有固定 8GB 上限。

#### Scenario: 只下调内存上限到既有共享之下被拒

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_memory_lowered_below_existing_shared
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_memory_lowered_below_existing_shared
- Assertion scope: 既有 shared=16/mem=32，请求只把 mem 改为 8 并夹带改名时，服务层与 API 均以 update_failed/422 拒绝；两个上限与机器名都不落库。

#### Scenario: 内存下调到等于既有共享上限可保存

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_accepts_memory_lowered_to_existing_shared
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_accepts_memory_lowered_to_shared
- Assertion scope: shared=16/mem=32，请求把 mem 改为 16 成功；shared 保持 16，mem 落库为 16。

#### Scenario: 同请求把共享与内存设为相等可保存

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_accepts_equal_shared_and_memory_in_one_request
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_accepts_equal_shared_and_memory
- Assertion scope: 同一请求把 max_shared_gb 与 max_memory_gb 都设为 8 时，服务层与 API 均成功，两个字段都落库为 8。

#### Scenario: 共享上限超过有效内存上限被拒

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_max_shared_greater_than_target_memory
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_shared_above_current_memory
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_shared_above_memory
- Assertion scope: 组合后的有效 shared 大于有效 mem 时，服务层与 API 均以 update_failed 拒绝且不落库；覆盖本次请求值和当前记录值两种来源。

#### Scenario: 负值、非整数与非整小数被拒

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_non_integer_or_negative_shared_size
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_fractional_shared_size
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_invalid_shared_input
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_accepts_integral_string_and_float_shared_size
- Assertion scope: 服务层拒绝负数、不可解析值和 3.5，返回 update_failed，3.5 不被截断为 3；请求模型层对同一组非法值返回 400 与 invalid_payload；可解析的整数字符串和整值浮点仍兼容。

#### Scenario: 显式 null 不能绕过组合约束

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_null_shared_with_memory_lowered
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_null_memory_with_shared_raised
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_null_shared_with_memory_lowered
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_null_memory_with_shared_raised
- Assertion scope: 显式 null 不写入字段，落库后另一侧仍是原值；两种组合都因有效 shared 大于有效 mem 被 update_failed/422 拒绝，同请求其它字段也不变。

#### Scenario: 没有内存上限的旧记录保持空值语义

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_skips_comparison_when_memory_limit_is_null
  - [X] test/repository/test_anvil_machine_images.py::test_null_shared_limit_with_known_memory_skips_comparison
- Assertion scope: 既有用例覆盖当前内存上限为 NULL 时设置 shared=16 成功、显式传 null 不写入且内存仍为 NULL。`[X]` 行核对当前共享上限为 NULL 而内存已知的对称分支：请求只设置 max_memory_gb，断言 NULL 共享视为未知、跳过比较、内存值可保存，且不把 NULL 顶替成数值或发明全局默认值。
- Coverage note: 内存 NULL 分支已有断言；共享 NULL 的对称分支见对应 `[X]` 行。

#### Scenario: 错误边界分层

- Test/check:
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_invalid_shared_input
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_shared_above_memory
  - [X] test/container/test_container_shared_memory_limit.py::test_create_params_sequence_enforces_machine_limit
- Assertion scope: 请求模型层的非整小数返回 400 与 invalid_payload；更新服务层的组合越界返回 422 与 update_failed；容器创建边界的共享越界返回 invalid_config。三者是不同边界，未互相替代或合并错误原因。

### Requirement: machines Node 端点解析

#### Scenario: 默认端口改动对已登记机器生效

- Test/check:
  - [X] test/machine/test_machine_node_endpoint.py::test_default_is_read_at_call_time_not_frozen
  - [X] test/machine/test_machine_node_endpoint.py::test_register_blank_port_falls_back_and_stores_null
  - [X] test/machine/test_machine_node_endpoint.py::test_empty_port_falls_back_to_global_default
  - [X] test/machine/test_machine_node_endpoint.py::test_resolve_endpoint_pairs_host_and_port
  - [X] test/machine/test_machine_node_endpoint.py::test_bare_host_drops_port_segment
  - [X] test/machine/test_machine_node_endpoint.py::test_https_action_url_uses_machine_port
  - [X] test/machine/test_machine_node_endpoint.py::test_link_url_uses_machine_port
  - [X] test/machine/test_machine_node_endpoint.py::test_peer_cert_probe_uses_machine_port
- Assertion scope: 全局默认端口在调用时现读，导入期不冻结；已登记机器 port 留空时记录保持 NULL，端点解析使用改动后的全局默认；不会把旧默认值固化进机器记录；裸主机与端口配对，HTTPS 动作、WSS 拨号与 TOFU 取证书三条出站路径分别使用机器端口。

### Requirement: machines 端点登记与链路重拨

#### Scenario: 端点变更不改信任

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_update_machine_ip_change_is_pure_registration
  - [X] test/machine/test_machine_tasks_crud.py::test_update_machine_ip_change_succeeds_while_new_address_unreachable
  - [X] test/machine/test_node_link.py::test_sync_links_restarts_link_when_host_changes
  - [X] test/machine/test_node_link.py::test_sync_links_restarts_link_when_port_changes
  - [X] test/machine/test_node_link.py::test_sync_links_restarts_link_when_uid_changes
  - [X] test/machine/test_machine_tasks_crud.py::test_update_machine_rejects_address_carrying_port
  - [X] test/machine/test_machine_node_endpoint.py::test_register_rejects_address_carrying_port
  - [X] test/machine/test_machine_node_endpoint.py::test_pin_written_and_read_under_the_same_bare_host_key
  - [X] test/machine/test_machine_node_endpoint.py::test_pin_survives_port_change
  - [X] test/repository/test_anvil_machine_images.py::test_endpoint_update_keeps_pin_fingerprint_without_probe
- Assertion scope: 修改 machine_ip 或 port 只更新登记字段，不发出站取证；新地址不可达仍可登记；链路按新主机/端口重建，uid 变化也作为链路目标变化处理；machine_ip 拒绝 host:port 写法，pin 文件按裸主机命名且换端口不影响既有 pin。`[X]` 行核对证书指纹与 pin 文件字节不变、没有 TLS 取证或 pin 重写。
- Coverage note: 既有用例分别覆盖纯登记与链路重拨；证书指纹和 pin 文件内容不变见对应 `[X]` 行。规格要求 machine_ip 只承载纯 IPv4，当前实现只拒绝冒号写法；本映射不声称 IPv4 字面校验已覆盖，该规格差异交父任务按 Global 登记处理。

### Requirement: machines 信任重钉与身份处理

#### Scenario: 重钉失败不动旧信任

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_unreachable_leaves_everything_intact
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_writes_op_log_on_failure
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_writes_op_log_on_success
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_keeps_uid_when_certificate_only_changed
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_reissues_uid_when_peer_lost_identity
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_adopts_reported_uid_when_db_has_none
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_flags_uid_mismatch_without_overwriting
  - [X] test/repository/test_anvil_machine_images.py::test_renew_profile_failure_keeps_pin_and_credentials
- Assertion scope: 取对端证书失败时返回 machine_unreachable，node_uid、证书指纹与 pin 集合保持原值，并写失败操作日志；成功与失败均写操作日志；对端身份牌完好时保留 uid，丢失时重发，库中无 uid 时采纳对端自报值，两侧都有且不一致时保持库值并报告 mismatch。`[X]` 行核对 enrollment profile 取证失败同样不改动 pin 与全部凭证字段，且写失败日志。
- Coverage note: 既有用例覆盖证书取证失败；enrollment profile 失败分支见对应 `[X]` 行。pin 文件写入失败不在当前规格的已定义分支内，本映射不新增该承诺；该未定义策略交父任务按 Global 登记处理。

### Requirement: machines 信任重钉持久化失败边界

#### Scenario: 数据库持久化失败不承诺 pin 回滚

- Test/check:
  - [X] test/repository/test_anvil_machine_images.py::test_renew_persist_failure_keeps_pin_file_and_returns_persist_failed
- Assertion scope: `[X]` 行先让 pin 文件成功写入，再以 SQLite `BEFORE UPDATE ON machines` 触发器使数据库更新失败；断言返回 persist_failed、写失败日志、数据库指纹保持旧值、pin 文件仍保留新证书，并且不声称文件与数据库为原子回滚。
- Coverage note: 该场景见对应 `[X]` 行；失败注入使用数据库触发器，不替换被测仓储或服务的成功路径。

### Requirement: machines 不可用窗口与期限顺延

#### Scenario: 窗口关闭后一次结算

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_offline_window_adds_deferral_on_recovery
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralAppliesToOtherDeadlines::test_window_close_credits_freeze_state
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralAppliesToOtherDeadlines::test_window_close_credits_pending_deleted_snapshot
  - [X] test/repository/test_anvil_machine_images.py::test_window_close_failure_keeps_window_open
- Assertion scope: 恢复为 online 且非维护时，SSH 登录、磁盘冻结与删除挂载保留记录在同一事务内各累加整段故障时长，随后清空 unavailable_since；已有用例覆盖三类期限。`[X]` 行先构造真实已存在的 `container_ssh_login_records` 行，并把 unavailable_since 设为过去使结算 delta>0；恢复时用 `BEFORE UPDATE OF deferral_seconds ON container_ssh_login_records` 触发器命中实际 UPDATE 后失败，断言恢复调用抛出 DB 错误、事务回滚、机器状态与 unavailable_since 未部分更新。
- Coverage note: 既有用例覆盖三类期限的同事务累加；同场景 `test_offline_window_adds_deferral_on_recovery` 是同一 SSH 记录与 delta 路径的无触发器正常控制组，证明触发组不是无条件失败。事务失败时窗口不关闭见对应 `[X]` 行。

#### Scenario: 窗口未关时倒计时照延

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestCleanupInfoDeferral::test_open_window_freezes_the_countdown
  - [X] test/machine/test_cleanup_deferral_window.py::TestCleanupInfoDeferral::test_open_window_adds_on_top_of_settled_deferral
  - [X] test/machine/test_cleanup_deferral_window.py::TestCleanupInfoDeferral::test_detail_read_path_picks_up_the_open_window
- Assertion scope: 窗口未关闭时读侧同时计入已结算的 deferral_seconds 与 unavailable_since 起的进行中窗口；两者叠加而非二选一；详情读路径与纯函数口径一致。

### Requirement: machines 采集心跳与启动窗口回填

#### Scenario: 停机期间的进窗被兜住

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestLastSeenHeartbeat::test_snapshot_batch_updates_last_seen
  - [X] test/machine/test_cleanup_deferral_window.py::TestLastSeenHeartbeat::test_collect_error_batch_still_counts_as_heard
  - [X] test/machine/test_cleanup_deferral_window.py::TestLastSeenHeartbeat::test_throttle_writes_once_within_window
  - [X] test/machine/test_cleanup_deferral_window.py::TestSeedUnavailableWindows::test_seeds_window_from_last_seen
  - [X] test/machine/test_cleanup_deferral_window.py::TestSeedUnavailableWindows::test_skips_machine_without_last_seen
  - [X] test/machine/test_cleanup_deferral_window.py::TestSeedUnavailableWindows::test_does_not_touch_open_window
  - [X] test/machine/test_cleanup_deferral_window.py::TestSeedUnavailableWindows::test_is_idempotent
  - [X] test/machine/test_node_link.py::test_run_links_forever_seeds_windows_before_first_dial
  - [X] test/repository/test_anvil_machine_images.py::test_last_seen_write_failure_does_not_block_snapshot_apply
- Assertion scope: 成功应用快照批（含 collect_error 批）会更新 last_seen_at；启动扫描只对窗口未开且有 last_seen_at 的机器回填起点，已有窗口不改写、无心跳不凭空开窗、重复扫描幂等，并且先于链路首次拨号。`[X]` 行以 SQLite `BEFORE UPDATE OF last_seen_at ON machines` 触发器让心跳写入失败，断言只告警且本批快照仍落库。
- Coverage note: 既有用例覆盖心跳更新、播种边界与拨号顺序；last_seen_at 写失败不影响本批快照见对应 `[X]` 行。

### Requirement: machines 出站链路集合对齐

#### Scenario: 机器集合变化保持其他存活链路

- Test/check:
  - [X] test/machine/test_node_link.py::test_load_link_targets_includes_offline_machines
  - [X] test/machine/test_node_link.py::test_sync_links_starts_link_for_new_machine
  - [X] test/machine/test_node_link.py::test_sync_links_keeps_live_links_untouched
  - [X] test/machine/test_node_link.py::test_sync_links_cancels_link_for_removed_machine
  - [X] test/machine/test_node_link.py::test_sync_links_restarts_dead_link
  - [X] test/machine/test_node_link.py::test_run_machine_link_marks_online_on_connect_offline_on_close
  - [X] test/machine/test_node_link.py::test_undialable_machine_without_uid_is_marked_offline
  - [X] test/repository/test_anvil_machine_images.py::test_link_backoff_is_per_machine_and_resets_on_connect
- Assertion scope: 链路清单包含 OFFLINE 行；新增机器起链路、存活链路不重建、删除机器取消链路、死亡链路重起；连接成功写 ONLINE，断开写 OFFLINE，不做二次探活；不在拨号清单内的机器被置为 OFFLINE。`[X]` 行核对单机连续失败独立退避、其他机器链路不受影响，连接成功后退避恢复初始值。
- Coverage note: 既有用例覆盖集合对齐与连接状态；单机独立退避及成功后恢复见对应 `[X]` 行。

### Requirement: machines 动作任务管辖范围

#### Scenario: 范畴外不动作也不留痕

- Test/check:
  - [X] test/machine/test_machine_scope.py::test_online_without_maintenance_is_in_scope
  - [X] test/machine/test_machine_scope.py::test_offline_machine_is_out_of_scope
  - [X] test/machine/test_machine_scope.py::test_maintenance_machine_is_out_of_scope_while_online
  - [X] test/machine/test_machine_scope.py::test_missing_machine_is_out_of_scope
  - [X] test/machine/test_machine_scope.py::test_none_machine_id_is_out_of_scope
  - [X] test/container/test_container_cleanup_task.py::test_out_of_scope_produces_no_records_across_rounds
  - [X] test/container/test_container_cleanup_task.py::test_maintenance_machine_is_out_of_scope
  - [X] test/container/test_container_cleanup_task.py::test_in_scope_failure_is_still_audited
  - [X] test/container/test_container_mount_cleanup_task.py::TestMountCleanupTask::test_skips_when_machine_unreachable
  - [X] test/container/test_container_mount_cleanup_task.py::TestMountCleanupTask::test_skips_when_machine_in_maintenance
  - [X] test/container/test_container_disk_check_task.py::TestEvaluateLimitsMachineGate::test_offline_machine_skips_evaluate
  - [X] test/container/test_container_disk_check_task.py::TestEvaluateLimitsMachineGate::test_maintenance_machine_skips_evaluate
- Assertion scope: 共享判据是“可达且非维护”；OFFLINE、维护中、记录缺失与 machine_id=None 均为范畴外且不抛异常；容器清理不动作且 op-log/常规日志零增长；挂载清理不发请求、不标记 cleaned；磁盘检测不触发 handler、不写冻结状态且不留日志。范畴内失败仍照常审计的对照断言也保留。

### Requirement: 机器详情保留配置端口

#### Scenario: 自定义端口可读取

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_get_detail_information_returns_configured_port
  - [X] test/machine/test_machine_api_crud.py::test_get_machine_detail_returns_configured_port
- Assertion scope: 服务层详情与真实 API 响应都保留 port=6789；响应模型没有过滤或覆盖为全局默认。

#### Scenario: 空配置仍使用平台默认

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_get_detail_information_success
  - [X] test/machine/test_machine_api_crud.py::test_get_machine_detail_keeps_null_port_without_default_filling
  - [X] test/machine/test_machine_node_endpoint.py::test_register_blank_port_falls_back_and_stores_null
- Assertion scope: 机器记录 port 为空时详情响应保留 null；数据库记录仍为 NULL；出站端点解析按当前全局默认端口执行，不把默认值写回机器记录。
