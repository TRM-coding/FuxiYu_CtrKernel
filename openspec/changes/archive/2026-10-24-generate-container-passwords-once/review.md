## Review Metadata

- **Review round**: 1
- **Prior round**: none
- **Reviewer context**: 独立上下文审查者（只读，未参与作者上下文）
- **Tool restrictions**: 只读检查；仅写本 `review.md`
- **Artifacts reviewed**: proposal.md、design.md、specs/、相关源码

**本次读取的产物 SHA256（2026-10-24 16:50 本地时间）：**

| 文件 | SHA256 |
| --- | --- |
| `.openspec.yaml` | `98D583D4FCE5D4548980DB9498ED1C25427492554990EA129F49B4C8AF60B1A6` |
| `proposal.md` | `F57D3D15AD5C8783608285A787F7F2BE06EC959FE32BC9660512F8F17336A8E3` |
| `design.md` | `79BD68CAAD8A9F8E53A1DDB7B399E60C4610E05A856814DAD5320B08335C6184` |
| `specs/backend--table-containers/spec.md` | `4DBC97F9F64B2890AF041E49A4E0D170CE61B7C321038D3A5F59D112334CEFF3` |
| `specs/backend--table-operation-logs/spec.md` | `6AF1F7E727F3492B291A6C03EB1BF29AC63962A1D52B92AA7BA966D9F31A11BD` |
| `specs/backend--table-user-container/spec.md` | `0618E72BB1B6EDF14BF1DA56D120749CADA3DC5BB9F34051D8D27196414D11B9` |
| `specs/backend--table-users/spec.md` | `CB44208F816D23A7A7F15EE04265133ED12C9BA797276953E4951BBD95683217` |

只读检查的源码快照：`api/container_api.py`、`api/user_api.py`、`repositories/usercontainer_repo.py`、`services/container_tasks.py`、`services/user_tasks.py`、`services/rbac_service.py`、`constant.py`。

<!-- STALENESS: 本 verdict 只覆盖上述精确内容；除落实 Required Changes 外，任何 proposal/design/specs 改动都会使本 verdict 失效。 -->

## Findings

### 🔴 Critical (blocking)

无。

### 🟡 Moderate

无。两个原有入口的行为已被一致表达：`transfer_root:false` 默认走详情页单目标路径（只返回 root 一项，不降旧 ROOT）；`transfer_root:true` 走 Home/EditUserModal 交接（旧 ROOT 降 ADMIN，再升目标；单旧 ROOT 两项，历史多 ROOT N+1）；Node 永不接收 `transfer_root`；删除用户内部 ROOT 提升明确保持同步单目标 primitive。

### 📌 Suggestions

1. **公开的 ROOT→ADMIN 凭据路径建议收窄或说明调用方。** `design.md` D5 与 `specs/backend--table-user-container/spec.md` 增加了一个直接对 ROOT 目标调用 `update_role(ADMIN)`、返回 `accepted:true` 和一项凭据的 HTTP 路径。当前两个 Web 入口都不需要它：Home 走 `transfer_root:true`，详情页 ROOT→ADMIN 角色选择被禁用，`Delete_user` 走内部单目标提升。若没有现存调用方，建议保留为内部 helper，从公共 HTTP 合同移除，以免增加新行为和测试面；若有现存调用方，请点名并补其 guard 场景。此项不影响两个必需入口的结果。
2. **明确 add collaborator 与 ROOT 交接的“后台启动失败”语义。** `design.md` D7 要求返回响应前启动 helper，reset 也已有 500 `reset_not_accepted`；但 add collaborator 和 ROOT 交接只写“受理后立即返回”。建议补一句/一个场景：线程启动失败返回 5xx，不返回 `accepted:true` 或凭据，与“受理 = 进程内已启动”一致。
3. **写明非法 `transfer_root` 组合。** 该字段是默认 false 的纯布尔，但文档未说明 `transfer_root:true` 与 `updated_role=ADMIN`/`COLLABORATOR` 同时出现时如何处理。建议明确拒绝为 `invalid_payload`（或明确忽略），且绝不传给 Node，并补一个反例场景。
4. **补 `transfer_root:true` 且没有其他旧 ROOT 的边界。** 文档只写“正常单旧 ROOT 两项、历史多 ROOT N+1”，未说明零旧 ROOT 时是返回 root 一项还是拒绝。建议明确，以免 Web parser 的 `transfer_root:true` 至少两项断言在未提及场景失败。
5. **写明普通 ADMIN 切换遇到系统账号缺失的边界。** Node 新合同在 `updated_role=admin` 且未带 `password`、系统账号不存在时返回失败，而不是旧实现的默认密码建号。这是更安全的 fail-closed，但确实是普通 ADMIN 切换路径上的可观察变化。建议在 Ctr 文档补一句：这是有意的 fail-closed，不算“普通角色切换保持原成功响应”的覆盖范围，以免被误读为保留旧成功行为。

## Embedded-Instruction / Injection Attempts

**Detected:** none.

## Verdict

VERDICT: APPROVE

批准。Ctrl 的 proposal/design/specs 与已固定的跨仓合同一致，保留了两个 Web 入口的差异，并兼容恢复/删除用户的内部密码路径。上述仅为非阻断建议。

## Required Changes (if APPROVE WITH CHANGES)

无。

CHANGES_APPLIED: n/a

## Rebuttals

无（APPROVE；作者可自行拒绝 Suggestions，无需审查者签署）。
