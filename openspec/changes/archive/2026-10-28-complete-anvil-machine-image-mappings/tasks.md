# Tasks

## 1. images 计划测试

- [x] 1.1 在 `test/repository/test_anvil_machine_images.py` 实现 `test_image_model_roundtrip_preserves_id_and_null_semantics`，覆盖 `backend--table-images` / `images 持久化结构` / `读取有效记录`；运行该 nodeid 通过。
- [x] 1.2 实现 `test_rename_checks_active_names_and_allows_disabled_name`，覆盖 `backend--table-images` / `images 模板名称唯一性` / `同名判定只看未停用`；运行该 nodeid 通过。
- [x] 1.3 实现 `test_machine_image_row_stays_readable_after_template_disabled`，覆盖 `backend--table-images` / `images 模板启停与构建记录失效` / `停用后可重新启用`；运行该 nodeid 通过。
- [x] 1.4 实现 `test_seed_legacy_name_converges_in_place_without_overwriting_status`，覆盖 `backend--table-images` / `images 内置模板幂等收敛` / `内置模板改名收敛`；运行该 nodeid 通过。
- [x] 1.5 实现 `test_platform_injection_change_keeps_ownership_grants_and_old_container`，覆盖 `backend--table-images` / `平台注入改变构建缓存版本` / `注入变化后派发`；运行该 nodeid 通过。
- [x] 1.6 运行 `test/repository/test_anvil_machine_images.py` 中 `backend--table-images` 的 5 个新测试全部通过。

## 2. machine_image 计划测试

- [x] 2.1 实现 `test_machine_image_model_roundtrip_enforces_composite_identity`，覆盖 `backend--table-machine-image` / `machine_image 持久化结构` / `读取有效记录`；运行该 nodeid 通过。
- [x] 2.2 实现 `test_base_image_change_changes_cached_recipe`，覆盖 `backend--table-machine-image` / `machine_image 生产职责与生命周期` / `模板构建内容变化`；运行该 nodeid 通过。
- [x] 2.3 实现 `test_entrypoint_change_changes_cached_recipe`，覆盖 `backend--table-machine-image` / `machine_image 生产职责与生命周期` / `模板构建内容变化`；运行该 nodeid 通过。
- [x] 2.4 实现 `test_node_rejection_keeps_reserved_row_and_next_dispatch_still_sends_build`，覆盖 `backend--table-machine-image` / `machine_image 派发记录与构建缓存` / `构建失败也留观测`；运行该 nodeid 通过。
- [x] 2.5 实现 `test_reservation_write_failure_prevents_dispatch_without_cache_row`，覆盖 `backend--table-machine-image` / `machine_image 缓存新鲜度与失败回退` / `陈旧行退回现造`；走真实 `Create_container` 路径并用 Node spy 断言未被调用；运行该 nodeid 通过。
- [x] 2.6 实现 `test_same_value_confirmation_is_idempotent_noop`，覆盖 `backend--table-machine-image` / `machine_image 缓存新鲜度与失败回退` / `陈旧行退回现造`；断言同值确认不产生新行或新版本；运行该 nodeid 通过。
- [x] 2.7 运行 `backend--table-machine-image` 的 6 个新测试全部通过。

## 3. machines 持久化与共享上限

- [x] 3.1 实现 `test_machine_model_roundtrip_preserves_columns_and_null_semantics`，覆盖 `backend--table-machines` / `machines 持久化结构` / `读取有效记录`；运行该 nodeid 通过。
- [x] 3.2 实现 `test_null_shared_limit_with_known_memory_skips_comparison`，覆盖 `backend--table-machines` / `machines 共享内存上限为机器可配置限额` / `没有内存上限的旧记录保持空值语义`；运行该 nodeid 通过。
- [x] 3.3 运行上述 2 个新测试全部通过。

## 4. machines 端点与重钉

- [x] 4.1 实现 `test_endpoint_update_keeps_pin_fingerprint_without_probe`，覆盖 `backend--table-machines` / `machines 端点登记与链路重拨` / `端点变更不改信任`；运行该 nodeid 通过。
- [x] 4.2 实现 `test_renew_profile_failure_keeps_pin_and_credentials`，覆盖 `backend--table-machines` / `machines 信任重钉与身份处理` / `重钉失败不动旧信任`；运行该 nodeid 通过。
- [x] 4.3 实现 `test_renew_persist_failure_keeps_pin_file_and_returns_persist_failed`，覆盖 `backend--table-machines` / `machines 信任重钉持久化失败边界` / `数据库持久化失败不承诺 pin 回滚`；运行该 nodeid 通过。
- [x] 4.4 运行上述 3 个新测试全部通过。

## 5. machines 窗口与心跳

- [x] 5.1 实现 `test_window_close_failure_keeps_window_open`，覆盖 `backend--table-machines` / `machines 不可用窗口与期限顺延` / `窗口关闭后一次结算`；构造 OFFLINE 机器、已有 SSH 行、delta>0，用真实表触发器证明失败命中；运行该 nodeid 通过。
- [x] 5.2 实现 `test_last_seen_write_failure_does_not_block_snapshot_apply`，覆盖 `backend--table-machines` / `machines 采集心跳与启动窗口回填` / `停机期间的进窗被兜住`；清空节流并断言 warning 与实际触发器命中；运行该 nodeid 通过。
- [x] 5.3 运行上述 2 个新测试全部通过。

## 6. machines 链路退避

- [x] 6.1 实现 `test_link_backoff_is_per_machine_and_resets_on_connect`，覆盖 `backend--table-machines` / `machines 出站链路集合对齐` / `机器集合变化保持其他存活链路`；运行该 nodeid 通过。
- [x] 6.2 运行该新测试通过。

## 7. 相关既有套件与 apply 校验

- [x] 7.1 运行 `test/image` 与 `test/repository/test_machine_image_repo.py`、`test/repository/test_machine_image_interleaving.py` 的相关既有测试，确认 19 个新测试未破坏镜像/缓存断言。
- [x] 7.2 运行 `test/machine/test_machine_node_endpoint.py`、`test/machine/test_machine_tasks_crud.py`、`test/machine/test_node_link.py`、`test/machine/test_cleanup_deferral_window.py` 的 enrollment、窗口与心跳相关既有测试。
- [x] 7.3 运行 `openspec validate --strict`、`openspec instructions apply --json`，确认 tasks 全部完成且无 blocked。

## Workflow follow-up

- 官方 `openspec-verify-change` advisory，不创建 verify.md。
- 精确 no-op sync，保持 Ctrl 27 个主规格 SHA 不变（父核全 65）。
- 按 `anvil-test-plan` 更新三个 capability 的 canonical sidecar，并保持 archive 目录 test-plan 与实施状态一致。
- 官方 archive（北京时间 2026-10-28）；按真实已完成范围汇报，Git 由父任务验收。
