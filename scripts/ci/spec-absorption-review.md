# Ctrl（FuxiYu_CtrKernel）规范吸收复核记录

主审说明：以下保留 DSH 原始过程记录。主审随后修正了部分语义及检查能力表述，条款数量也可能因拆分改变；本报告不作为实施或验收依据，现行规则以本仓库 `openspec/specs` 为准。

- 范围：本仓库 `openspec/specs/**/spec.md`（25 份既有业务规格）与 **Global 归档的 12 份旧业务 SPEC**、以及**旧 AGENTS 流程规范**的对照
- 基线：仓库工作区当前内容（逆向基线标识 `d6d0d0e26fb6（chester-next）`，2026-10-11）
- 性质：**过程记录，不是 SPEC**；不放入 `openspec/`
- 授权边界：本次未编辑 `AGENTS.md`、`githooks/`、`scripts/ci/check_pr.py`、`.github/`、`FuxiYu_Global`、Git 配置与暂存区；未 `commit` / `push` / `stage`；未读取任何 `.local/` 或凭据文件；未修改任何业务代码
- 写入所有权（严格限于下列文件）：本仓库 4 份既有业务 `spec.md`、1 份新建本地流程规范、以及本记录自身

## 1. 结论

本次分两条**互不相关**的轨道，结论分别是：

**轨道 A —— 旧 Global 业务 SPEC 的退役吸收：最小吸收，改 4 份既有业务规格，未新增/改名任何能力。**

`FuxiYu_Global\bak\2026-10-11\Global\openspec\changes\` 下 7 个变更、12 份 `spec.md`、共 65 条 Requirement，逐条对照 Ctrl 实际源码后的归宿：

| 归宿 | 条数 | 说明 |
|---|---|---|
| 已吸收（写入既有业务 spec.md） | 42 | 已实现且既有 SPEC 未覆盖的事实 |
| 已覆盖（既有 SPEC 已载，不重复） | 9 | 同一事实已在既有条文中，重复即漂移 |
| 已实现·未吸收（有实现，本次不写） | 7 | 属一次性迁移、入口/响应/审计形状、回归不变量或既有一般行为 |
| 与实现相反 / 过时（**不得写成现状**） | 1 | `machine-image-cache-record` 的「记录不设失效与删除逻辑」 |
| 本仓库不适用（Node 侧 / Web 侧） | 6 | 见 §5.4 |
| 合计 | 65 | 12 份 spec.md 的 Requirement 总数 |

**轨道 B —— 旧 AGENTS 流程规范的退役吸收：1 份本地规范，独立可执行。**

新增 `openspec/specs/procedure--repository-workflow/spec.md`（1 份，非 3 篇搬运）：把提交信息、钩子启用与书写、能力命名、PR 正文四件事写在一处，并明确划出「规范要求」与「已实现的自动检查」的边界。该规范不依赖 Global 即可执行，各仓库同类规范彼此独立。

**未做的事**：未恢复此前暂缓的 Container 大规模细节补写；未借吸收之名修业务代码；未复制 Global 文件；未新建业务 capability。

## 2. 本次实际改动清单

| 文件 | 性质 | 吸收来源（Global 归档件） |
|---|---|---|
| `openspec/specs/backend--table-containers/spec.md` | 新增 1 条 Requirement（5 Scenario） | `container-image-provenance`（provenance / binding / restore 中的 Ctrl 侧共 20 条） |
| `openspec/specs/backend--table-machines/spec.md` | 新增 2 条 Requirement（7 Scenario） | `per-machine-node-port`、`renew-machine-trust`、`track-machine-last-seen`、`reverse-wss-dial-direction/node-link`、`unify-action-task-scope`、`defer-freeze-and-mount-windows`（窗口机制部分） |
| `openspec/specs/backend--table-images/spec.md` | 新增 1 条 Requirement（4 Scenario） | `image-template-lifecycle`（6 条中吸收 4、已覆盖 2） |
| `openspec/specs/backend--table-machine-image/spec.md` | 新增 1 条 Requirement（3 Scenario） | `machine-image-cache-record`（4 条中的 3 条） |
| `openspec/specs/procedure--repository-workflow/spec.md` | **新建**（7 条 Requirement） | 旧 `AGENTS.md` / `AGENT.md` 中的提交、钩子、命名、PR 四类规范 |
| `scripts/ci/spec-absorption-review.md` | 改写为双轨结论 | 本记录 |

未改动：25 份既有规格中其余 21 份、所有 `models/`、`services/`、`api/`、`scripts/` 业务代码。

## 3. 轨道 A 逐条判定

判定口径：只有当某条要求**与 Ctrl 实际源码一致**、且在既有业务 `spec.md` 中**确有缺口**时，才做最小吸收。新增/改写的事实一律以 `path:line` 佐证；未被吸收的逐条给出理由。

### 3.1 `defer-freeze-and-mount-windows/specs/unavailable-window-deferral`（5 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 顺延覆盖全部「起点 + 窗口」型到期判定 | 三类锚点各有 `deferral_seconds`：`models/container_ssh_login.py:27`、`models/container_disk_freeze_state.py:33`、`models/deleted_container_restore_snapshot.py:23` | **已覆盖**：三份既有 SPEC 分别写明（`container-ssh-login-records:29`、`container-disk-freeze-state:24`、`deleted-container-restore-snapshot:24`） | 无 |
| 2 | 顺延的结算与进行中窗口（两来源叠加） | 读侧同时折算：`services/container_module/queries.py:111-132`、`schedulers/container_cleanup_task.py:148-186`、`schedulers/container_disk_check_task.py:200`、`repositories/deleted_container_restore_snapshot_repo.py:55-71` | **吸收** | `machines` 新增 Requirement 的正文与「窗口未关时倒计时照延」Scenario |
| 3 | 结算与 ssh 清理同事务、失败不半途生效 | `services/machine_tasks.py:213-215`（同一 session 内三表批量累加，`:216-217` 才清起点） | **吸收** | `machines` 新增 Requirement 正文与「窗口关闭后一次结算」Scenario |
| 4 | 起点复位时顺延归零 | `repositories/container_ssh_login_repo.py:69`（真登录清零）；冻结重建新锚点 | **已覆盖**：`container-ssh-login-records:24`、`container-disk-freeze-state:29` | 无 |
| 5 | 无顺延时行为不变（空值等同零） | `func.coalesce(...)` + 模型 `default=0` / `server_default=text("0")` | **已覆盖**：既有 SPEC 的数据附录已载默认值与 server_default 的区分 | 无 |

### 3.2 `unify-action-task-scope/specs/machine-scope-gate`（4 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 单一定义机器的管辖范畴（可达且非维护） | `services/machine_tasks.py:297-306` `machine_in_scope`；机器缺失并入范畴外（`:304-305`） | **吸收** | `machines` 新增 Requirement 正文 +「范畴外不动作也不留痕」Scenario |
| 2 | 动作任务在范畴外不动作 | 三个动作任务共用同一判据：`schedulers/container_cleanup_task.py:207-212`、`schedulers/container_mount_cleanup_task.py:61-64`、`schedulers/container_disk_check_task.py:89-94` | **吸收**（判据与三处共用已写入；「手动入口不受约束」未写） | 同上 |
| 3 | 范畴外不产生任何记录 | 三个 scheduler 在范畴外静默跳过；`machine_in_scope` 仅被这三个 scheduler 导入（全仓库 grep 被导入点仅 3 处 + 定义处），手动入口在服务层不经过它 | **吸收** | 同上 |
| 4 | 范畴内失败仍照常留痕 | 既有失败审计通道照常工作（`test/container/test_container_cleanup_task.py:151`） | **已实现·未吸收**：属既有审计通道的一般行为，非该表新增契约 | 无 |

### 3.3 `per-machine-node-port/specs/machine-node-endpoint`（6 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 每台机器的 Node 端点（留空回落默认、默认唯一来源、不在导入期固化、指定即覆盖） | `services/container_module/node_comms_modules/endpoint.py:8-10,21-30`（`default_node_port()` 每次调用现读 `CommsConfig.NODE_PORT`）；`models/machine.py:11-14` | **吸收** | `machines` 第一新增 Requirement 正文 +「默认端口改动对已登记机器生效」Scenario |
| 2 | 端口在机器建档时录入（留空/指定/超范围拒绝） | `services/machine_tasks.py:311-324`（`Register_machine(..., port=None)`，`enrollment._validate_node_port`） | **已实现·未吸收**：留空与「不固化」已吸收；取值范围校验属入口校验，未写入表规格 | 部分落 `machines` |
| 3 | 三条出站路径共用同一端口来源 | `endpoint.py:1-6`（模块自述「三条出站路径…都从这里取值」）；WSS 拨号 `node_comms_modules/link.py:12,62`；HTTPS/TOFU 经 `machine_endpoint`（`services/machine_tasks.py:399`、`node_comms_modules/enrollment.py`） | **吸收** | `machines` 第一新增 Requirement 正文 |
| 4 | pin 文件键统一为裸主机 | `endpoint.py:33-40` `bare_host()`，键与 URL 主机段同源 | **吸收** | 同上 |
| 5 | 端点变更后链路跟随（重拨 / 未变不重连） | `services/machine_tasks.py:606-609`（端点纯登记）；`link.py:275-300`（`sync_links` 按新地址重建任务）；`link.py:214,241-243` 独立退避 | **吸收** | `machines` 第二新增 Requirement 正文（含自动跟随与退避） |
| 6 | 端点变更只改登记，不涉信任（改地址不取证、不可达也可登记、身份判据在对端、只改端口无需重建信任） | `services/machine_tasks.py:606-618`（含 `machine_ip` 拒绝携带端口，reason=`invalid_machine_ip`）；`link.py:250-273`（身份由 uid 校验） | **吸收** | `machines` 第一新增 Requirement 正文 +「端点变更不改信任」Scenario |

### 3.4 `renew-machine-trust/specs/machine-trust-renewal`（6 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 只对已登记的机器重钉（存在则更新原行、不存在不建行、不触碰唯一约束字段） | `services/machine_tasks.py:363-380,383-396`（只 UPDATE；不写 `machine_name`/`machine_ip`） | **吸收** | `machines` 第一新增 Requirement 正文 |
| 2 | 重抓对端证书并覆盖 pin | `services/machine_tasks.py:420-425,458-467`（`_fetch_peer_cert` → `_persist_peer_pin` → 更新指纹与 `cert_pinned_at`） | **吸收** | 同上 |
| 3 | 失败时整体不落地 | `services/machine_tasks.py:372-376,413-418`（阶段一取齐证据，任何一步失败都在改动本地状态之前退出） | **吸收** | 同上 +「重钉失败不动旧信任」Scenario |
| 4 | uid 按需重发 | `services/machine_tasks.py:438-455`（对端丢牌才重发；库中无则采纳自报；两侧都有保持库值）、`:471-476` 报不一致 | **吸收** | 同上 |
| 5 | 重钉全程留痕（成功/失败） | `services/machine_tasks.py:386-393,405-408,413-418,478-501`；操作类型 `constant.py:91` | **吸收** | 同上 |
| 6 | 可从机器详情页触发 | Ctrl 侧只有 API 入口 `api/machine_api.py:176-190`；界面在 Web 仓库 | **本仓库不适用**（界面部分） | API 入口已存在，未写入表规格 |

### 3.5 `track-machine-last-seen/specs/machine-last-seen`（5 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 记录机器最后一次被成功采集的时刻（收到即更新、采集异常也算听到、取不到不更新、写入有节流） | `services/container_module/node_comms_modules/snapshots.py:293-319`（`:302-317` Ctrl 自身时钟、`:296-298,312-313` 60s 节流、失败只告警）；写入点 `repositories/machine_repo.py:186` | **吸收**（既有 `machines:24` 仅一句「WSS 更新…last_seen_at」） | `machines` 第二新增 Requirement 正文 |
| 2 | 以最后可见时刻兜住窗口起点（播种/已有窗口不动/无值跳过/幂等） | `services/machine_tasks.py:220-256` | **吸收** | 同上 +「停机期间的进窗被兜住」Scenario |
| 3 | 扫描必须先于链路拨号 | `services/machine_tasks.py:233-234`（顺序注释与理由）；顺序由 `link.py:302-315`（`_seed_windows_before_first_dial` → `run_links_forever`）保证 | **吸收** | 同上 |
| 4 | 不修改结算与消费口径 | 回归不变量，无新增事实 | **已实现·未吸收**：无新事实可写 | 无 |
| 5 | 迁移携带该信号 | `__init__.py:410`（`ALTER TABLE machines ADD COLUMN last_seen_at DATETIME NULL`） | **已实现·未吸收**：一次性存量迁移，属迁移过程；既有 SPEC 的 Source references 已声明 `create_all` 不推定列迁移 | 无 |

### 3.6 `reverse-wss-dial-direction/specs/node-link`（5 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 连接集合由 machines 表驱动（启动即全表、OFFLINE 同样尝试、离线发现由退避承担） | `link.py:32-75`（分页读全量机器行，含 OFFLINE；表里有行就拨） | **吸收** | `machines` 第二新增 Requirement 正文 |
| 2 | 机器集合变更自动跟随（新注册自动接入、删除后终止、对齐不打断存活链路） | `link.py:275-300`（`sync_links` 只对差异动手） | **吸收** | 同上 |
| 3 | 按机器独立退避重连 | `link.py:214,228-229,241-243`（每任务独立计数器，成功后复位） | **吸收** | 同上 |
| 4 | 连接结果即机器在线状态（成功 ONLINE、断开离线） | `link.py:197-243`（`:200` 自述「拨号结果是第一手证据，不再二次探测」）；`link.py:250-273` 不在清单即 OFFLINE | **吸收** | 同上 |
| 5 | 快照帧的接收与落库保持不变（四种 topic、队列满丢最旧、delete 限本机作用域） | 帧落库在 `snapshots.py`；队列满丢最旧已实现 `node_comms_modules/websocket.py:19-25,89`（`QueueFull` → `get_nowait()` 丢最旧） | **部分已覆盖**：既有 `backend--table-containers:24` 已载「Node WSS 状态对账更新运行事实」；delete 帧的本机作用域本次未逐条核对 | 未吸收（不新增未核对的条文） |

### 3.7 `reverse-wss-dial-direction/specs/node-snapshot-endpoint`（4 条）

| # | Global 要求 | Ctrl 实际状态 | 判定 |
|---|---|---|---|
| 1 | Node 在既有 HTTPS 监听上提供 WSS 端点 | Node 侧实现 | **本仓库不适用** |
| 2 | 端点校验 Ctrl 出示的 uid | Node 侧实现 | **本仓库不适用** |
| 3 | 接受连接后按周期推送快照 | Node 侧实现 | **本仓库不适用** |
| 4 | 推送线程与重连职责移交 Ctrl | 职责移交后的 **Ctrl 侧**已由 §3.6 吸收；推送线程本体在 Node | **本仓库不适用**（Ctrl 侧对应项见 §3.6-1/3/4） |

### 3.8 `container-image-provenance/specs/container-image-provenance`（5 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 容器记录其构建所依据的模板版本时刻（**取值是模板版本而非当前时间**） | ⚠ **口径不同**：Ctrl 存的是**制品版本戳**——缓存命中取 `machine_image.created_at`，现造取派发时刻（`services/image_tasks.py:63-115`，尤其 `:114`；`:240-244` 明确「缓存命中时是行里那个 `created_at`，现造时是 `now()`」「⚠ 它不是模板最后一次被改的时刻」） | **吸收（按实际语义改写，不照抄 Global 措辞）** | `containers` 新增 Requirement 正文；偏差见 §5.1 |
| 2 | 落后判据由版本戳与模板版本比较得出（不依赖容器创建时间） | `services/container_module/restore.py:399-401`（比模板当前版本，注明「不是 build.version_at…现造时等于 now()」）；`test/container/test_container_image_id.py:1413` | **吸收** | `containers` 正文 +「落后判据只看版本戳」Scenario |
| 3 | 运行基底展示的唯一出口一律取容器侧留痕 | `services/container_module/utils.py:250-272`（`container_image_dockerfile`，纯留痕渲染）；出口 `information.py:124` | **吸收** | `containers` 正文 +「运行基底展示不随模板编辑失真」Scenario |
| 4 | 容器留存构建配方的输入，而非渲染结果（平台注入不落库、判据看 `base_image`、业务片段可为空、不参与身份判定） | `models/containers.py:31-60`；落库 `creation.py:155-172`；渲染 `utils.py:236-247`（`:230-231` 自述判据看 `base_image`） | **吸收** | `containers` 正文 |
| 5 | 镜像标签可推导且不落库（唯一实现、缺一不编造） | `services/image_tasks.py:118-142`（唯一构造实现，`:131-133` 刻意不用 `now()` 兜底）；`models/containers.py:57-60`、`models/machine_image.py:11` | **吸收** | `containers` 正文 +「标签推导不出时不编造」Scenario |

### 3.9 `container-image-provenance/specs/container-image-binding`（4 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 容器的镜像归属由外键保持完整（移除不抹掉归属） | `models/containers.py:19-26`（FK，无 `ondelete`） | **吸收** | `containers` 正文首句 |
| 2 | 创建容器必须指定镜像归属（拒绝形状：缺失/不存在/无权/已停用） | `api/container_api.py:201-232`（`:207` 缺失 400 `invalid_payload`、`:224/:232` 404 `image_not_found`、`:226` 400 `image_not_ready`、`:228` 403 `image_access_denied`） | **已覆盖**：既有 `backend--table-images:24` 已载「创建容器只使用 ready 模板并保存 image_id」；拒绝形状属 API 契约 | 无 |
| 3 | 运行镜像由平台解析，调用方不得指定 | `api/container_api.py:234-236`（请求体里的 `image`/`IMAGE` 不再采信） | **吸收** | `containers` 正文末句 +「运行镜像由平台解析」Scenario |
| 4 | 存量容器的归属按标签回填 | `__init__.py:515-804`（改名 → 补列 → 建索引 → 清悬挂 → 回填；`:580,707-804` 退役旧列） | **已实现·未吸收**：一次性存量迁移，属迁移过程；既有 SPEC 已声明 `create_all` 不推定列迁移 | 无 |

### 3.10 `container-image-provenance/specs/container-image-restore`（11 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 恢复以配方留痕为前提，不以镜像归属为前提 | `restore.py:381-390`（归属为空/模板非 READY 走留痕） | **吸收** | `containers` 恢复句 |
| 2 | 内容来源由模板状态与新鲜度共同判定 | `restore.py:362-411`（四分支：无归属 / 非 READY / 落后 / 正常） | **吸收** | 同上 |
| 3 | 内容发生变化时不得静默替换 | `restore.py:392-408`（默认取留痕，仅显式 `template` 走当前模板） | **吸收** | 同上 |
| 4 | 内容会变时先给人看两份内容 | `restore.py:414-441`（`requires_choice`、两份内容、按配方分段、不列平台注入段）；调用点 `services/container_tasks.py:242-246`、`api/container_api.py:401-420` | **吸收** | 「内容会变时先交回两份」Scenario |
| 5 | 恢复接口的入参与响应形状固定（含非法取值被拒） | `schemas/container.py:148-188`（`content_source` 与 `requires_choice` 契约）；`api/container_api.py:401-403`（非法取值 400） | **已实现·未吸收**：`requires_choice` 与 `container_id` 空已在 Scenario 覆盖；响应/入参字段级形状未逐条写入 | 部分落 `containers` |
| 6 | 恢复必须有内容可依（无留痕时拒绝） | `restore.py:518-521`（推导不出标签即拒绝，`invalid_payload`） | **部分已覆盖**：前提句已写；拒绝分支属错误形状 | 部分落 `containers` |
| 7 | 恢复必须刷新构建版本戳与配方留痕 | `restore.py:323-356`（按来源重算标签与留痕）；`creation.py:137-151` | **吸收** | `containers` 恢复句 |
| 8 | 恢复来源可事后分辨 | `restore.py:561-588`（`:567-570,586` 把 `restore_image` 记进审计 detail）；来源常量 `:119-121` | **已实现·未吸收**：属审计 detail 形状 | 无 |
| 9 | 恢复的挂载行为与镜像来源无关 | `restore.py` 以 `target.mount_path` 独立传入；`test/container/test_container_image_id.py:1308` 断言两种来源挂载一致 | **吸收** | `containers` 正文末句 |
| 10 | 容器改名不改变数据位置 | `restore.py:489-524`（`_resolve_restore_container_name` 只改名字，挂载路径仍取 `target.mount_path`） | **吸收** | 同上 |
| 11 | 账号重建后家目录属主被修正 | Ctrl 只组包账号（`services/container_module/collaborators.py:17-18`、`restore.py:257`），家目录属主由 Node 侧处理 | **本仓库不适用** | 无 |

### 3.11 `container-image-provenance/specs/image-template-lifecycle`（6 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 镜像模板的移除是停用而非删除 | `repositories/image_repo.py:271-272`；`services/image_tasks.py:518-565` | **已覆盖**：`backend--table-images:24,26-29` | 无 |
| 2 | 停用状态在业务读点一致生效（列表/计数/创建/可见性） | `repositories/image_repo.py:10,107,135,160`；`services/image_tasks.py:305-322` | **已覆盖**（列表与新建已载）；计数与可见性共用同一过滤器（`:135,:160`） | 无 |
| 3 | 管理路径必须仍能取到已停用的模板（含收敛逻辑能看见停用行） | `services/image_tasks.py:258-259`；`utils.py:263-264`；`image_tasks.py:785-788`（seed 必须看见停用行，否则插入第二个同名模板） | **吸收** | `images` 新增 Requirement 正文 + Scenario |
| 4 | 停用可撤销 | `services/image_tasks.py:518-525`（「重新启用走 Update_image（status 在可更新白名单里）」） | **吸收** | 同上 +「停用后可重新启用」Scenario |
| 5 | 模板名唯一性由应用层保证 | `repositories/image_repo.py:100-107`（只查未停用）；`services/image_tasks.py:393,471-473` | **吸收** | 同上 +「同名判定只看未停用」Scenario |
| 6 | 内置模板的收敛只作用于系统行 | `services/image_tasks.py:737-819`（`:755-764` 限定 `created_by_user_id IS NULL`；`:788-789` 同名跳过不覆盖人工修改；`:791-808` 就地改名且不覆盖停用状态；`:817` 新行 `valid_range=EVERYONE`） | **吸收** | 同上 +「内置模板改名收敛」Scenario |

> 该文件不含「模板更新产生新行 / 没有删除入口」条目；对应要求在第 4 份 `machine-image-cache-record`，见 §3.12-4。

### 3.12 `container-image-provenance/specs/machine-image-cache-record`（4 条）

| # | Global 要求 | Ctrl 实际状态（证据） | 判定 | 落点 |
|---|---|---|---|---|
| 1 | 派发过的构建被记录在案（同一组合不重复、不同机器彼此独立） | `repositories/machine_image_repo.py:34-65`（`record_dispatch` 有行即返回）；唯一约束 `models/machine_image.py:37-41` | **已覆盖**：`backend--table-machine-image:24,26-29` 与表级约束 | 无 |
| 2 | 记录的语义是「请求过」而非「建成过」 | `models/machine_image.py:15`（构建失败也留记录） | **吸收** | `machine_image` 新增 Requirement 正文 +「构建失败也留观测」Scenario |
| 3 | 该记录不在执行链上 | `models/machine_image.py:9-20`；`machine_image_repo.py:88-96`（`list_by_machine` 自述「观测用，不参与任何决策」） | **吸收** | 同上 |
| 4 | **记录不设失效与删除逻辑**（模板更新产生新行、没有删除入口） | ⚠ **与实现相反**：`services/image_tasks.py:480-482` 在模板更新时调用 `machine_image_repo.delete_by_image` 删掉整行（`:68-85` 自述「本表唯一合法的删除入口」「宁可多删」） | **过时/相冲突，不吸收** | 见 §5.2；既有 SPEC 已记载实现行为，未改写 |

### 3.13 轨道 A 小结

- 「已覆盖」9 条全部落在既有摘要句上：`machines:24,26-29`、`images:24,26-29`、`machine_image:24,26-29`、`container-ssh-login-records:24,29`、`container-disk-freeze-state:24,29`、`deleted-container-restore-snapshot:24,29`、`containers:24`。这些不再重复书写，否则同一事实两处维护。
- 「已实现·未吸收」7 条全部是**一次性迁移**（2 条：`machine-last-seen` 第 5、`container-image-binding` 第 4）、**入口/响应/审计形状**（3 条：`machine-node-endpoint` 第 2、`container-image-restore` 第 5 与第 8）、**回归不变量**（1 条）、**既有审计通道的一般行为**（1 条）——均无表级新契约可写。
- 唯一「与实现相反」的 1 条已在 §5.2 单列，**未按 Global 措辞写入现状**。

## 4. 轨道 B：旧 AGENTS 流程规范 → 单篇本地规范

新增 `openspec/specs/procedure--repository-workflow/spec.md`，共 7 条 Requirement。逐项覆盖情况：

| 要求的规范内容 | 规范中的落点 |
|---|---|
| 提交条目 `- NEW`/`- AMEND`/`- FIX` + 中文短语；描述真实变更；不写工具署名与生成标记；真实 merge 默认信息豁免 | Requirement「提交信息条目格式」+ 3 个 Scenario（实现证据：`githooks/commit-msg:37-39,45-49,63-80`） |
| 每克隆 `git config --local core.hooksPath githooks`，启用前先检查已有 hooks | Requirement「钩子启用与书写」+ Scenario「目标克隆已有钩子配置」 |
| 新增/修改的 shell 钩子 LF + Git 100755 | 同上 + Scenario「换行与可执行位」（证据：`.gitattributes:2-3`；`githooks/*` 头部注释） |
| 新 capability 四类前缀 standard/frontend/backend/procedure，不叠加 | Requirement「能力命名与粒度」+ 2 个 Scenario（证据：`githooks/pre-commit:82-99`） |
| Ctrl 按表 / Node 8 个能力单元（需完整类型契约）/ Web 按页面 | 同上的粒度段 |
| 根 README 保留；openspec 内不放 README | 同上 + Scenario（现状已合规） |
| pre-commit 只检查暂存区新增标记；既有 delta/改名/归档不强制迁移 | Requirement「命名检查的作用边界」+ 2 个 Scenario（证据：`githooks/pre-commit:47-53,68-70,100`） |
| 各仓库规范独立，不依赖 Global SPEC | Requirement「规范独立与问题登记」 |
| 问题集中登记 Global/QUESTIONS，区分复现/源码确认/待验证/已修复 | 同上 + Scenario |
| 规范≠业务问题已修复 | Purpose 段 + 同上 Requirement |
| PR 四栏（WHAT'S NEW / Bug Fixes / Enhancements & Patches / Coming Up）；前三栏至少一栏有真实条目；计划栏可选且不计交付；空栏可删或「- 无」；验证与通过率可选；标题为自然描述、不强制 conventional 前缀；旧 NEW/FIX 仅过渡兼容；占位/注释/代码块不计交付 | Requirement「PR 正文栏目」+ 3 个 Scenario（实现证据：`scripts/ci/check_pr.py:20-42,167-186,228-279`；`.github/pull_request_template.md`） |
| workflow 读事件 JSON、优先 base 检查器、首次接入用固定 SHA | Requirement「校验实现与其边界」（证据：`.github/workflows/pr-format.yml:20-34,59-61`） |
| commit 关键词与 PR 栏目是两套独立体系 | Requirement「提交信息条目格式」末句 |
| **不得声称** hook 会校验中文真实性、PR 标题等未实现的自动检查 | Requirement「校验实现与其边界」+ Scenario「未实现的自动检查不得声称」 |

未做：未搬运 Global 三篇（编码风格 / 规范命名 / PR 格式）原文，未按三篇分章；未把规范条款混入任何业务表规格或类型契约；未编辑 `AGENTS.md`（该文件已不在仓库内）、`githooks/`、检查器、模板、工作流。

## 5. 冲突与偏差（只报告，不修）

### 5.1 `last_build_at` 的口径以代码为准，与 Global 措辞不同（且代码注释自相矛盾）

- Global 要求：版本戳「取值是模板版本（`images.updated_at`）而非当前时间」。
- Ctrl 实现：**制品版本戳** —— `services/image_tasks.py:63-115`（缓存命中取 `machine_image.created_at`，`:114` 现造时取 `utcnow()`），`:240-244` 明确写出「⚠ 它不是『模板最后一次被改的时刻』」；`restore.py:399-400` 同样注明 `build.version_at`「现造时等于 `now()`」。
- **同一仓库内注释互相矛盾**（未修改，仅登记）：
  - `models/containers.py:27-29`：「= 派发构建时读到的 `images.updated_at`，不是 `now()`」
  - `services/container_module/creation.py:142-143`：「模板路径下是当前 `images.updated_at`」
  - 与上面两处相反的实际口径：`services/image_tasks.py:240-244`、`restore.py:399-400`
- 本次吸收**按实际代码语义**书写（§2 的 `containers` 条文），未把 Global 措辞写成现状。两处陈旧注释属代码注释缺陷，按授权边界**不由本次修复**，建议登记到 Global/QUESTIONS.md。

### 5.2 `machine-image-cache-record` 第 4 条与实现相反

- Global 要求：记录不设失效与删除逻辑，模板更新产生新行。
- Ctrl 实现：模板更新即**删行**（`services/image_tasks.py:480-482` → `repositories/machine_image_repo.py:68-85`），下次派发重新插入。既有 `backend--table-machine-image:24,26-29` 正是按实现书写的。
- 处置：**不吸收**，未改为 Global 口径，也未把冲突写进业务规格。

### 5.3 既有规格内的已知差异备注（保留原样）

- `openspec/specs/backend--table-machine-image/spec.md:24` 末尾仍写「实际渲染以 image_tasks 为准，模型内仍有旧注释，差异见 Global QUESTIONS」。该备注与 `models/machine_image.py` 文档字符串并存，本次按「不扩大修复范围」保留。

### 5.4 「本仓库不适用」6 条的归属

- Node 侧 4 条：`node-snapshot-endpoint` 的 WSS 端点、uid 校验、周期推送、推送线程。
- Web 侧 1 条：`machine-trust-renewal` 的「机器详情页触发」界面部分（Ctrl 侧 API 已存在，`api/machine_api.py:176-190`）。
- Node 侧 1 条：`container-image-restore` 的「账号重建后家目录属主被修正」（Ctrl 只组包账号，见 `services/container_module/collaborators.py:17-18`）。

## 6. 检查结果

### 已执行（只读 + 文件写入）

- 逐份读取 Global 归档的 12 份业务 `spec.md` 全文与 65 条 Requirement 标题
- 逐份读取被改的 4 份既有业务规格、25 份规格清单、`models/` 相关模型、`services/` 相关服务、`schedulers/`、`repositories/`、`api/`、`githooks/` ×2、`scripts/ci/check_pr.py`、`.github/pull_request_template.md`、`.github/workflows/pr-format.yml`、`.gitattributes`
- grep 对照：`last_build_at` / `deferral_seconds` / `last_seen_at` / `renew_machine_trust` / `machine_in_scope` / `content_source` / `machine_image_repo` / 四类前缀等关键标识的调用点与实现点
- 已用文件工具完成全部写入（4 份既有规格 + 1 份新规范 + 本记录）

### 未执行（本会话环境阻塞，已明示交由父代理接管的命令类检查）

| 待跑命令 | 目的 |
|---|---|
| `openspec validate --specs --strict` | 本次新增条文与新增规范的结构/格式校验 |
| `python -m unittest discover -s scripts/ci/tests -p test_check_pr.py` | PR 检查器单测（父代理已报告 40 项通过） |
| `python scripts/ci/check_pr.py --body-file .github/pull_request_template.md` | 反向验收：模板原样应失败（预期退出码 1） |
| `git ls-files -s githooks/pre-commit githooks/commit-msg` | 核验 100755 执行位 |
| `git status --porcelain` | 确认本记录与本次改动未触碰暂存区与用户改动 |
| `sha256sum scripts/ci/check_pr.py` | 核对 `.github/workflows/pr-format.yml:59` 的固定摘要 |

**阻塞原因**：本会话文件沙箱在工作区写授权时失败（`SetNamedSecurityInfoW failed (Win32 5): grantWrite(E:\AI\Fuxi\FuxiYu_CtrKernel)`），`pwsh` 完全无法启动。按用户要求，本次不再做 ACL 诊断、不提权重试、不建探针；上述命令类检查一律**交由父代理执行**，本次只报告静态证据。文件读写工具不受影响，故全部条文核对与写入均已完成。

## 7. 未决问题

1. **命令类检查待父代理补跑**（§6 表），本次结论建立在静态核对之上。
2. **`last_build_at` 的两处陈旧注释**（§5.1）：建议登记到 Global/QUESTIONS.md 的现有问题体系，不在本次吸收中修。
3. **`machine-image-cache-record` 第 4 条与实现相反**（§5.2）：已按实现书写、未按 Global 措辞改写，供上层决定该 Global 条目的最终退役处置。
4. **`node-link` 第 5 条的 delete 帧本机作用域**未逐条核对（§3.6-5）：未据此新增条文。
5. **本记录目录下的排障遗留**：`E:\AI\Fuxi\FuxiYu_CtrKernel\.dsh-write-probe.tmp`（内容为 `probe`）为上一轮确认写入通道所建，因 `pwsh` 不可用无法删除，待有执行权限的一方清理。另注：`E:\AI\Fuxi\FuxiYu_Web\scripts\ci\.spec-absorption-write-test.tmp` 属 Web 侧，未触碰。
6. **PR 检查器单测未接入工作流**：`ctrl-tests.yml:31-36` 只跑业务 pytest，`pr-format.yml` 只跑 `--event` 校验；属测试接入的工程问题，建议登记而非在本次规范吸收中处理。
7. **25 份既有规格记载的 `992 passed / 6 deselected` 未复跑**：属回归留痕，非吸收判定依据。

## 8. 保留与未改动声明

- 25 份既有业务规格中，**21 份一字未改**；被改的 4 份只做了「新增 Requirement + Scenario」的最小追加，未删除、未改写既有条文，未改文件名与能力标识。
- 新增能力目录仅 `procedure--repository-workflow` 一个，符合四类前缀且不叠加；`openspec/` 内未新增 README。
- 未修改 `AGENTS.md`（已不在仓库内）、`githooks/`、`scripts/ci/check_pr.py`、`.github/`、`FuxiYu_Global`、`.git/config`、暂存区。
- 未执行 `git add` / `git commit` / `git push`；未改动 Git 配置；未运行依赖真实外部服务的业务测试。
- 未读取任何 `.local/` 或凭据文件；未修改任何业务代码。
- 本轮新建文件：`openspec/specs/procedure--repository-workflow/spec.md`。
