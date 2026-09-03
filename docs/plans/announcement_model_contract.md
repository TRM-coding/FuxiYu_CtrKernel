# 公告系统（Announcement）模型契约与实现计划

> 后端模型契约 + 分阶段实现计划。每阶段自包含：常量 → 文件范围 → 数据流 → 函数收口 → 测试。

---

## 前置：核心状态机（跨阶段参考）

### 公告（Announcement）状态机

公告**只能由草稿发送产生**，不存在"直接创建公告"的入口。

```
  [草稿发送]
      │
      ▼
 ┌──────────┐
 │ SENDING  │  发送进行中（瞬态，幂等保护）
 └────┬─────┘
      │
  ┌───┼───────┐
  ▼   ▼       ▼
┌────┐┌─────┐┌──────┐
│SENT││PART ││FAILED│
└──┬─┘└──┬──┘└──┬───┘
   │     │      │
   └─────┼──────┘
         │ resend（三种终态均可）
         ▼
     回到 SENDING → ...
```

| 当前状态 | 允许操作 | 目标状态 |
|---------|---------|---------|
| (不存在) | 草稿发送 | SENDING → SENT / PARTIAL / FAILED |
| SENT | resend / copy-as-draft / convert-to-template | SENDING → 终态 / 新 Draft / 新 Template |
| PARTIAL | 同上 | 同上 |
| FAILED | 同上 | 同上 |

> SENDING 瞬态幂等保护：若 send 时发现已是 SENDING → 409。已发送公告不可删除。

### 草稿（Draft）生命周期

```
[编辑器"保存草稿"] → announcement_drafts 表
       ├── 点选 + "发送" → 创建 Announcement + send_mail → 草稿删除
       ├── 点击卡片 → 加载回编辑器
       ├── 删除 → 物理删除
       └── [从已发送"复用"] → 新草稿（复制已发公告内容）
```

草稿 = 发送界面"待发送内容"的唯一载体。

### 模板变量生命周期

```
DEFINED（模板 variables JSON）→ PLACED（raw_content 中 {{key}}）→ FILLED（前端表单填值）→ RENDERED（发送时替换为 content）
```

未填充变量保留 `{{key}}` 原样，前端应在发送确认前提示。

---

## 总体架构

```
blueprints/announcement_api.py    ← 路由层
services/announcement_tasks.py    ← 业务逻辑层
repositories/announcement_repo.py ← 数据访问层
models/announcement.py            ← ORM 模型（3 张新表）
constant.py / config.py           ← 新增枚举与配置
utils/mail.py                     ← 复用现有，不改动
```

| 表 | 用途 |
|----|------|
| `announcements` | 已发送公告（SENT/PARTIAL/FAILED） |
| `announcement_templates` | 信件级模板（变量定义 + 模板正文） |
| `announcement_drafts` | 草稿 = 发送界面"待发送内容" |

---

## 阶段零：常量与配置

### 0. 新增常量定义

```python
# constant.py
class AnnouncementStatus(Enum):
    SENDING = "sending"
    SENT = "sent"
    PARTIAL = "partial"
    FAILED = "failed"

class AnnouncementTargetType(Enum):
    MACHINE = "machine"
    CONTAINER = "container"
    USER = "user"

class AnnouncementTemplateCategory(Enum):
    SYSTEM = "system"
    CUSTOM = "custom"
```

```python
# config.py
ANNOUNCEMENT_MAX_RECIPIENTS = int(os.getenv("ANNOUNCEMENT_MAX_RECIPIENTS", "200"))
ANNOUNCEMENT_SEND_COOLDOWN_SECONDS = int(os.getenv("ANNOUNCEMENT_SEND_COOLDOWN_SECONDS", "60"))
ANNOUNCEMENT_BATCH_SEND_MAX = int(os.getenv("ANNOUNCEMENT_BATCH_SEND_MAX", "20"))
```

### 1. 影响文件范围

| 文件 | 操作 |
|------|------|
| `constant.py` | **编辑** — 新增 3 个 Enum |
| `config.py` | **编辑** — 新增 3 个配置项 |

### 2. 完整数据流

```
AnnouncementStatus   ──→ Announcement.status 列（DB Enum）
                            ├── send_draft_service(): SENDING → SENT/PARTIAL/FAILED
                            ├── resend_announcement_service(): 同上
                            └── list_announcements(status=[...]): 过滤查询

AnnouncementTargetType ──→ TargetEntry.type 字段
                            └── resolve_recipients(): 按 type 分派解析逻辑

ANNOUNCEMENT_MAX_RECIPIENTS ──→ resolve_recipients() 上限校验
ANNOUNCEMENT_BATCH_SEND_MAX  ──→ batch_send_drafts_service() 上限校验
```

### 3. 函数级收口

无函数——本阶段仅定义枚举值语义与配置项默认值。

### 4. 测试用例

常量与配置无独立测试——其正确性由服务层与 API 层测试间接覆盖（如上限校验测试 S-06、A-25）。

---

## 阶段一：数据模型层（Models）

### 0. 新增常量定义

无——使用阶段零定义的枚举。

### 1. 影响文件范围

| 文件 | 操作 |
|------|------|
| `models/announcement.py` | **新建** — 3 个 ORM 模型 |
| `models/__init__.py` | **编辑** — 导出新模型 |

### 2. 完整数据流（表级）

```
[编辑器保存] → announcement_drafts 表（正文 + 模板引用，不含目标）

[发送界面] 公共操作栏选择收件人 → POST /resolve-targets → 预览人数
         │
         │ 勾选草稿 + [批量发送]
         ▼
   POST /drafts/batch-send { draft_ids, targets }
         │
         ├── resolve_recipients(targets) → 收件人列表
         ├── for each draft: render → create Announcement → send_mail
         └── announcements 表（SENDING → SENT/PARTIAL/FAILED）
         草稿删除


[已发送区] POST /<id>/copy-as-draft → 新 Draft（纯正文）
          POST /<id>/convert-to-template → announcement_templates（新行）
          POST /<id>/resend → 重新 send_mail（沿用原 targets）


[模板管理] → announcement_templates 表
     │
     ├── 编辑器选择模板 → 加载 subject_template + body_template + variables
     └── [已发送转模板] → 新行，source_announcement_id 记录来源
```

**融合版 targets 设计：**

machine/container 均视为"用户集合"，与单 user 平权。`resolve_recipients()` 遍历所有条目 → 按 user_id 去重。

```json
{
    "targets": [
        {"type": "machine",    "id": 1},
        {"type": "container",  "id": 5},
        {"type": "user",       "id": 10}
    ]
}
```

`AnnouncementTargetType` 退化为单条条目的分类标签。

### 3. 函数级收口（列定义与关系）

#### 3.1 `Announcement` — 已发送公告

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | Integer | PK, autoincrement | |
| `title` | String(200) | NOT NULL | 邮件主题 |
| `content` | Text | NOT NULL | 发送时的最终正文（变量已替换） |
| `raw_content` | Text | nullable | 编辑版正文（可能含 `{{}}`） |
| `created_by` | Integer | FK→users.id, NOT NULL | 创建者 |
| `status` | Enum(AnnouncementStatus) | NOT NULL, index | SENDING/SENT/PARTIAL/FAILED |
| `targets` | Text | nullable | JSON: `[{type, id}]` |
| `target_snapshot` | Text | nullable | JSON: 发送时解析的展示摘要 |
| `recipient_count` | Integer | default 0 | |
| `success_count` | Integer | default 0 | |
| `fail_count` | Integer | default 0 | |
| `created_at` | DateTime | default utcnow | |
| `sent_at` | DateTime | nullable | 实际发送时间 |
| `source_draft_id` | Integer | nullable | 来源草稿 id |
| `template_id` | Integer | FK→announcement_templates.id | 使用的模板 |

关系：`creator`→User, `template`→AnnouncementTemplate。

#### 3.2 `AnnouncementTemplate` — 信件级模板

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | Integer | PK | |
| `name` | String(120) | UNIQUE, NOT NULL | 模板名 |
| `category` | Enum(AnnouncementTemplateCategory) | default CUSTOM | |
| `description` | String(500) | nullable | |
| `subject_template` | String(200) | NOT NULL | 主题模板（含 `{{}}`） |
| `body_template` | Text | NOT NULL | 正文模板 |
| `variables` | Text | nullable | JSON 变量定义数组 |
| `source_announcement_id` | Integer | nullable | 从哪个公告转来 |
| `created_by` | Integer | FK→users.id | |
| `created_at` | DateTime | default utcnow | |
| `updated_at` | DateTime | onupdate utcnow | |

关系：`creator`→User。SYSTEM 类别不可删除。

#### 3.3 `AnnouncementDraft` — 草稿

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | Integer | PK | |
| `title` | String(200) | NOT NULL | |
| `content` | Text | NOT NULL | 编辑器当前正文 |
| `raw_content` | Text | nullable | 原始模板正文 |
| `created_by` | Integer | FK→users.id | |
| `targets` | Text | nullable | JSON `[{type, id}]`（发送时由公共操作栏写入） |
| `template_id` | Integer | FK→announcement_templates.id | |
| `created_at` | DateTime | default utcnow | |
| `updated_at` | DateTime | onupdate utcnow | |

### 4. 测试用例（模型层）

| ID | 名称 | 输入 | 预期 |
|----|------|------|------|
| M-01 | Announcement 创建 | 完整字段 | 提交成功，字段一致 |
| M-02 | AnnouncementDraft 创建 | 完整字段 | 提交成功，creator 可访问 |
| M-03 | AnnouncementTemplate 唯一名 | 同名两次 | IntegrityError |
| M-04 | Announcement↔Template 关联 | template_id 设值 | announcement.template 可访问 |
| M-05 | targets JSON 存取 | `[{"type":"machine","id":1},{"type":"user","id":5}]` | 存取一致 |
| M-06 | Template.source_announcement_id | 可空/可设值 | 存取一致 |
| M-07 | Draft↔Template 关联 | template_id 设值 | draft.template 可访问 |
| M-08 | Announcement.source_draft_id | 设值 | 存取一致 |

---

## 阶段二：仓库层（Repositories）

### 0. 新增常量定义

无。

### 1. 影响文件范围

| 文件 | 操作 |
|------|------|
| `repositories/announcement_repo.py` | **新建** |
| `repositories/__init__.py` | **编辑** — 导出新仓库函数 |

### 2. 完整数据流（仓库层）

```
                    ┌─ create_announcement() ──→ INSERT announcements
                    ├─ get_announcement_by_id() ──→ SELECT by PK
                    ├─ list_announcements() ──→ SELECT + filter + paginate
Announcement ───────├─ update_announcement_status() ──→ UPDATE status/counts
                    └─ (无 delete——已发送不可删)

                    ┌─ create_template() ──→ INSERT
                    ├─ get_template_by_id() ──→ SELECT
AnnouncementTemplate├─ list_templates() ──→ SELECT + filter
                    ├─ update_template() ──→ UPDATE（排除 system）
                    └─ delete_template() ──→ DELETE（仅 custom）

                    ┌─ save_draft() ──→ INSERT or UPDATE（幂等）
AnnouncementDraft ──├─ get_draft_by_id() ──→ SELECT
                    ├─ list_drafts() ──→ SELECT + filter
                    └─ delete_draft() ──→ DELETE
```

### 3. 函数级收口

#### 3.1 公告

```
create_announcement(
    title: str,
    content: str,
    created_by: int,
    *,
    status: AnnouncementStatus = AnnouncementStatus.SENDING,
    raw_content: str | None = None,
    targets: str | None = None,
    target_snapshot: str | None = None,
    recipient_count: int = 0,
    template_id: int | None = None,
    source_draft_id: int | None = None,
) -> Announcement
```
- 内部：构造 `Announcement()` → `db.session.add()` → `commit()` → 返回 ORM 对象。
- 仅由 `send_draft_service` 调用，初始 status=SENDING。

```
get_announcement_by_id(announcement_id: int) -> Announcement | None
```
- 内部：`Announcement.query.get(id)`。

```
list_announcements(
    *,
    status: list[str] | None = None,
    created_by: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Announcement], int]
```
- 内部：`filter(Announcement.status.in_(status))` → `order_by(desc(Announcement.created_at))` → `offset/limit` + 并行 count 查询。返回 `(结果列表, 总数)`。

```
update_announcement_status(
    announcement_id: int,
    status: AnnouncementStatus,
    *,
    success_count: int | None = None,
    fail_count: int | None = None,
    sent_at: dt.datetime | None = None,
) -> Announcement | None
```
- 内部：`get → setattr（仅非 None 字段）→ commit`。

#### 3.2 模板

```
create_template(
    name: str,
    subject_template: str,
    body_template: str,
    created_by: int,
    *,
    description: str | None = None,
    variables: str | None = None,
    category: str = "custom",
    source_announcement_id: int | None = None,
) -> AnnouncementTemplate
```
- 内部：构造 → `add()` → `commit()`。

```
get_template_by_id(template_id: int) -> AnnouncementTemplate | None
```
- 内部：`AnnouncementTemplate.query.get(id)`。

```
list_templates(
    *,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AnnouncementTemplate], int]
```
- 内部：可选 `filter_by(category=category)` → `order_by(desc(created_at))` → 分页 + count。

```
update_template(template_id: int, **fields) -> AnnouncementTemplate | None
```
- 允许字段：`name`, `description`, `subject_template`, `body_template`, `variables`, `category`。
- 内部：`get → 逐字段 setattr → commit`。

```
delete_template(template_id: int) -> bool
```
- 内部：查 template，若 `category == SYSTEM` → 返回 False；否则 `db.session.delete() → commit()` → True。

#### 3.3 草稿

```
save_draft(
    title: str,
    content: str,
    created_by: int,
    *,
    draft_id: int | None = None,
    raw_content: str | None = None,
    targets: str | None = None,
    template_id: int | None = None,
) -> AnnouncementDraft
```
- 内部：若 `draft_id` 存在 → `get → 逐字段更新 → commit`；否则 → `insert → commit`。返回更新后/新建的 Draft。
- `targets` 参数保留（数据列存在），但编辑器保存时不传——targets 由发送时写入。

```
get_draft_by_id(draft_id: int) -> AnnouncementDraft | None
```
- 内部：`AnnouncementDraft.query.get(id)`。

```
list_drafts(
    *,
    created_by: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AnnouncementDraft], int]
```
- 内部：可选 filter → `order_by(desc(updated_at))` → 分页 + count。

```
delete_draft(draft_id: int) -> bool
```
- 内部：`get → delete → commit`；不存在返回 False。

### 4. 测试用例（仓库层）

| ID | 名称 | 输入 | 预期 |
|----|------|------|------|
| R-01 | create_announcement | 必填字段 | 返回 Announcement |
| R-02 | get_announcement_by_id(存在) | 存在 id | 返回 Announcement |
| R-03 | get_announcement_by_id(不存在) | 999 | None |
| R-04 | list_announcements 多状态 | status=["sent","partial"] | 两类均返回 |
| R-05 | list_announcements 分页+倒序 | limit=10, offset=5 | 最新在前，正确偏移 |
| R-06 | update_announcement_status | status=SENT, counts | 状态+计数+时间更新 |
| R-07 | create_template | 完整字段 | 返回模板 |
| R-08 | update_template(部分字段) | name="new" | 仅更新 name |
| R-09 | delete_template(custom) | custom 模板 | True, 记录删除 |
| R-10 | delete_template(system) | system 模板 | False |
| R-11 | save_draft(新建) | draft_id=None | 新行, id 自增 |
| R-12 | save_draft(更新) | 已有 draft_id | 同 id, updated_at 刷新 |
| R-13 | get_draft_by_id | 存在/不存在 | 返回/None |
| R-14 | list_drafts 按创建者 | created_by | 仅该用户草稿 |
| R-15 | delete_draft | 存在 id | True |

---

## 阶段三：服务层（Services）

### 0. 新增常量定义

无——使用阶段零的 `ANNOUNCEMENT_MAX_RECIPIENTS`、`ANNOUNCEMENT_BATCH_SEND_MAX`。

### 1. 影响文件范围

| 文件 | 操作 |
|------|------|
| `services/announcement_tasks.py` | **新建** |

### 2. 完整数据流（服务层）

```
[发送界面] 公共操作栏选 targets → resolve-targets 预览
               │
               │ 勾选草稿 + [批量发送]
               ▼
        POST /drafts/batch-send { draft_ids, targets }
               │
               │  for each draft_id:
               ▼
     ┌─────────────────────────────────────┐
     │ send_draft_service(draft_id, targets)│
     │                                     │
     │  resolve_recipients(targets)        │
     │  render_template(raw→content)       │
     │  create_announcement(SENDING)       │
     │  逐个 send_mail()                   │
     │  统计 → update status + counts      │
     │  delete_draft(source)               │
     └─────────────────────────────────────┘
               │
               ▼
        BatchSendResult (收集每条结果)


    POST /<id>/copy-as-draft          POST /<id>/convert-to-template
    查公告→复制字段→save_draft()      查公告→提取{{key}}→create_template()
            │                                  │
            ▼                                  ▼
       新 Draft                           新 Template


    POST /<id>/resend
    查公告→resolve(原targets)→render→send
    更新 status+计数
```

### 3. 函数级收口

#### 3.1 Pydantic 数据模型

```python
class TargetEntry(BaseModel):
    """单条目标输入"""
    type: str   # "machine" | "container" | "user"
    id: int

class RecipientEntry(BaseModel):
    user_id: int
    username: str
    email: str

class TargetSummaryEntry(BaseModel):
    type: str
    id: int
    display_name: str   # "GPU-01 (10.0.0.1)" | "容器名 (:8080)" | "张三 (z@x.com)"

class ResolveResult(BaseModel):
    recipients: list[RecipientEntry]
    summary: list[TargetSummaryEntry]
    total_count: int

class ElementDefinition(BaseModel):
    key: str            # "machine_name"
    label: str          # "机器名(IP)"
    category: str       # greeting | machine | container | time | closing
    description: str
    requires_target: bool
    example: str

class SendResult(BaseModel):
    draft_id: int | None
    announcement_id: int
    status: str
    recipient_count: int
    success_count: int
    fail_count: int
    failures: list[dict]   # [{"email":"...","error":"..."}]

class BatchSendResult(BaseModel):
    total: int
    results: list[SendResult]
```

#### 3.2 收件人解析

```
resolve_recipients(targets: list[TargetEntry]) -> ResolveResult
```

**输入：** `[{"type":"machine","id":1}, {"type":"user","id":5}]`

**输出：** `ResolveResult(recipients=[RecipientEntry,...], summary=[TargetSummaryEntry,...], total_count=N)`

**内部逻辑（伪代码）：**
```
recipients_map = {}   # user_id → RecipientEntry
summaries = []

for entry in targets:
    if entry.type == "machine":
        machine = Machine.query.get(entry.id)
        if not machine: continue
        user_ids = [mp.user_id for mp in MachinePermission.query.filter_by(machine_id=entry.id)]
        users = User.query.filter(User.id.in_(user_ids)).all()
        summaries.append(TargetSummaryEntry(type="machine", id=entry.id,
            display_name=f"{machine.machine_name} ({machine.machine_ip})"))
    elif entry.type == "container":
        container = Container.query.get(entry.id)
        if not container: continue
        user_ids = [uc.user_id for uc in UserContainer.query.filter_by(container_id=entry.id)]
        users = User.query.filter(User.id.in_(user_ids)).all()
        summaries.append(TargetSummaryEntry(type="container", id=entry.id,
            display_name=f"{container.name} (:{container.port})"))
    elif entry.type == "user":
        user = User.query.get(entry.id)
        if not user: continue
        users = [user]
        summaries.append(TargetSummaryEntry(type="user", id=entry.id,
            display_name=f"{user.username} ({user.email})"))

    for u in users:
        if u.id not in recipients_map:
            recipients_map[u.id] = RecipientEntry(user_id=u.id, username=u.username, email=u.email)

if len(recipients_map) > current_app.config["ANNOUNCEMENT_MAX_RECIPIENTS"]:
    raise ValueError("too_many_recipients")

return ResolveResult(
    recipients=list(recipients_map.values()),
    summary=summaries,
    total_count=len(recipients_map),
)
```
- 忽略不存在的 target（机器/容器/用户可能已被删除）——不抛异常，仅跳过。
- 去重 key 为 `user_id`。

#### 3.3 模板变量渲染

```
render_template_content(template_body: str, variables: dict[str, str]) -> str
```

**输入：** `body="{{greeting}}\n{{machine_name}} 维护通知"`, `variables={"greeting": "您好"}`

**输出：** `"您好\n{{machine_name}} 维护通知"`（未提供的保留原样）

**内部逻辑：**
1. `re.sub(r'\{\{(\w+)\}\}', lambda m: variables.get(m.group(1), m.group(0)), template_body)`
2. 不在 variables 中的 key → 保留 `{{key}}`。

#### 3.4 元素定义查询

```
get_element_definitions() -> list[ElementDefinition]
```

**输入：** 无

**输出：** 硬编码 5 类共约 12 个元素定义，示例：

| key | category | label |
|-----|----------|-------|
| `greeting` | greeting | 问候语 |
| `machine_name` | machine | 机器名(IP) |
| `machine_ip` | machine | 机器 IP |
| `machine_type` | machine | 机器类型 |
| `container_name` | container | 容器名(端口) |
| `container_port` | container | 容器端口 |
| `container_expire_time` | container | 到期时间 |
| `current_date` | time | 当前日期 |
| `current_datetime` | time | 当前日期时间 |
| `closing` | closing | 结束语 |

**内部逻辑：** 纯 static 返回，无 DB 查询。`requires_target` 对机器/容器类为 True（前端据此决定是否在无目标时灰化按钮）。

#### 3.5 草稿发送（核心）

```
send_draft_service(
    draft_id: int,
    targets: list[TargetEntry],
    *,
    variables: dict[str, str] | None = None,
) -> SendResult
```

**输入：** `draft_id=7`, `targets=[{type:"machine",id:1}]`, `variables={"maintenance_time":"2026-06-15"}`

**输出：** `SendResult(announcement_id=42, status="sent", success_count=18, fail_count=0, failures=[])`

**内部逻辑：**
```
1. draft = draft_repo.get_draft_by_id(draft_id)
   if not draft: raise ValueError("draft_not_found")

2. if not targets: raise ValueError("empty_targets")
   resolve_result = resolve_recipients(targets)
   targets_json = json.dumps([t.model_dump() for t in targets])

3. rendered = render_template_content(
       draft.raw_content or draft.content,
       variables or {},
   )

4. announcement = announcement_repo.create_announcement(
       title=draft.title,
       content=rendered,
       raw_content=draft.raw_content,
       created_by=draft.created_by,
       status=AnnouncementStatus.SENDING,
       targets=targets_json,
       target_snapshot=json.dumps([s.model_dump() for s in resolve_result.summary]),
       recipient_count=resolve_result.total_count,
       template_id=draft.template_id,
       source_draft_id=draft.id,
   )

5. success = fail = 0
   failures = []
   for recipient in resolve_result.recipients:
       result = send_mail(to=recipient.email, subject=announcement.title, content=announcement.content)
       if result.get("ok"):
           success += 1
       else:
           fail += 1
           failures.append({"email": recipient.email, "error": result.get("error", "unknown")})

6. if fail == 0:      new_status = AnnouncementStatus.SENT
   elif success == 0: new_status = AnnouncementStatus.FAILED
   else:              new_status = AnnouncementStatus.PARTIAL

   announcement_repo.update_announcement_status(
       announcement.id,
       status=new_status,
       success_count=success,
       fail_count=fail,
       sent_at=dt.datetime.utcnow(),
   )

7. draft_repo.delete_draft(draft_id)

8. return SendResult(
       draft_id=draft_id,
       announcement_id=announcement.id,
       status=new_status.value,
       recipient_count=resolve_result.total_count,
       success_count=success,
       fail_count=fail,
       failures=failures,
   )
```

**幂等保护（在步骤 4 之前）：** 若 draft 刚被另一个并发请求发送了（通过检查该 draft_id 是否已有对应 Announcement），返回 409。实际实现中可以通过 DB 唯一约束 `(source_draft_id)` 或乐观锁来处理。

#### 3.6 批量发送草稿

```
batch_send_drafts_service(
    draft_ids: list[int],
    targets: list[TargetEntry],
) -> BatchSendResult
```

**输入：** `draft_ids=[7,8,9]`, `targets=[{type:"machine",id:1}]`

**输出：** `BatchSendResult(total=3, results=[SendResult,...])`

**内部逻辑：**
```
1. if len(draft_ids) > ANNOUNCEMENT_BATCH_SEND_MAX: raise ValueError("batch_too_large")
2. if not targets: raise ValueError("empty_targets")
3. results = []
   for did in draft_ids:
       try:
           results.append(send_draft_service(did, targets=targets))
       except Exception as e:
           results.append(SendResult(draft_id=did, announcement_id=0, status="error", ...))
4. return BatchSendResult(total=len(draft_ids), results=results)
```
- 所有被勾选的草稿发送给**同一组收件人**。单条失败不影响后续。
- 单条失败不影响后续。

#### 3.7 重发

```
resend_announcement_service(announcement_id: int) -> SendResult
```

**输入：** `announcement_id=42`

**输出：** `SendResult`（draft_id=None）

**内部逻辑：**
1. 查 announcement。检查状态不是 SENDING（是则 409）。
2. 更新 status=SENDING。
3. 解析 targets → `resolve_recipients()`；渲染 content（若 raw_content 含 `{{}}` 且未提供 variables，沿用已渲染的 content）。
4. 同 3.5 步骤 5-6 发送 + 更新统计。
5. 返回 SendResult。

#### 3.8 复用为草稿

```
copy_announcement_as_draft_service(announcement_id: int) -> AnnouncementDraft
```

**输入：** `announcement_id=42`

**输出：** 新 `AnnouncementDraft`（前端通过 `draft.id` 加载到编辑器）

**内部逻辑：**
```
1. ann = announcement_repo.get_announcement_by_id(announcement_id)
   if not ann: raise ValueError("not_found")
2. draft = draft_repo.save_draft(
       title=ann.title,
       content=ann.raw_content or ann.content,
       raw_content=ann.raw_content,
       created_by=current_user_id,
       targets=ann.targets,
       template_id=ann.template_id,
   )
3. return draft
```

#### 3.9 转为模板

```
convert_announcement_to_template_service(announcement_id: int) -> AnnouncementTemplate
```

**输入：** `announcement_id=42`（raw_content 为 `"{{greeting}}\n\n{{machine_name}} 维护"`）

**输出：** 新 Template，variables 自动提取

**内部逻辑：**
```
1. ann = announcement_repo.get_announcement_by_id(announcement_id)
   if not ann: raise ValueError("not_found")

2. # 从 raw_content 提取所有 {{key}}
   import re
   keys = list(set(re.findall(r'\{\{(\w+)\}\}', ann.raw_content or ann.content)))
   auto_vars = json.dumps([
       {"key": k, "label": k, "type": "string", "required": False}
       for k in sorted(keys)
   ])

3. template = template_repo.create_template(
       name=f"来自公告: {ann.title}",
       subject_template=ann.title,
       body_template=ann.raw_content or ann.content,
       created_by=current_user_id,
       variables=auto_vars,
       source_announcement_id=ann.id,
   )
4. return template
```

#### 3.10 模板预览

```
preview_template_service(template_id: int, variables: dict[str, str]) -> dict
```

**输入：** `template_id=3`, `variables={"machine_name":"GPU-01"}`

**输出：** `{"subject_rendered": "...", "body_rendered": "..."}`

**内部逻辑：** 查模板 → `render_template_content()` 分别渲染 subject 和 body → 返回 dict。

### 4. 测试用例（服务层）

| ID | 名称 | 关键输入 | 预期 |
|----|------|---------|------|
| S-01 | 融合解析：纯机器 | targets=[{machine,1},{machine,2}] | MachinePermission 用户列表 |
| S-02 | 融合解析：纯容器 | targets=[{container,1}] | 容器成员列表 |
| S-03 | 融合解析：纯用户 | targets=[{user,1},{user,2}] | 对应用户 |
| S-04 | 融合解析：混合 | targets=[{machine,1},{user,5}] | 合并去重 |
| S-05 | 跨集合去重 | 同一用户通过 machine+user 命中 | email 不重复 |
| S-06 | 收件人上限 | total > 200 | ValueError("too_many_recipients") |
| S-07 | 变量替换(正常) | body="{{a}}", vars={"a":"1"} | "1" |
| S-08 | 缺变量保留 | body="{{a}}{{b}}", vars={"a":"1"} | "1{{b}}" |
| S-09 | 无占位符原样 | body="text" | "text" |
| S-10 | send_draft: 全成功 | draft + targets + mock mail ok | status=SENT, draft 删除 |
| S-11 | send_draft: 部分失败 | mock mail 部分 error | status=PARTIAL, 统计正确 |
| S-12 | send_draft: 全失败 | mock mail 全 error | status=FAILED |
| S-13 | send_draft: targets 为空 | targets=[] | ValueError("empty_targets") |
| S-14 | send_draft: draft 不存在 | draft_id=999 | ValueError |
| S-15 | batch_send: 3 条 | [id1,id2,id3] + targets | 3 条结果, 各自状态独立 |
| S-16 | batch_send: 超限 | len > 20 | ValueError |
| S-17 | resend: 从 SENT | sent 公告 | 再次发送, status 更新 |
| S-18 | resend: SENDING 幂等 | 公告已是 SENDING | 409 |
| S-19 | copy_as_draft: 内容一致 | sent 公告 | draft.title/raw_content/targets/template_id 一致 |
| S-20 | copy_as_draft: 模板引用 | 原公告有 template_id | draft.template_id 相同 |
| S-21 | convert_to_template: 提取变量 | raw_content 含 {{a}} {{b}} | variables 含 2 条 |
| S-22 | convert_to_template: 无变量 | raw_content 纯文本 | variables=[] |
| S-23 | convert_to_template: name | title="GPU维护" | name="来自公告: GPU维护" |
| S-24 | 元素定义查询 | - | 5 类 > 0 |
| S-25 | 模板预览 | template_id, vars | subject/body 正确渲染 |

---

## 阶段四：API 路由层（Blueprints）

### 0. 新增常量定义

无。

### 1. 影响文件范围

| 文件 | 操作 |
|------|------|
| `blueprints/announcement_api.py` | **新建** |
| `blueprints/__init__.py` | **编辑** — `from . import announcement_api` |

### 2. 完整数据流（请求→响应）

全部端点要求 Operator 权限。认证模式沿用现有：
```python
def _require_operator():
    token = request.cookies.get("auth_token", "")
    if not authentications_repo.is_token_valid(token):
        return jsonify({"success":0, "message":"invalid token", "error_reason":"invalid_token"}), 401
    if not user_repo.check_permission(token, PERMISSION.OPERATOR):
        return jsonify({"success":0, "message":"insufficient permissions", "error_reason":"insufficient_permission"}), 403
    return None  # 通过
```

**元素定义：**
```
GET /api/announcements/element-definitions
  → announcement_tasks.get_element_definitions()
  ← 200 {"success":1, "elements": [...]}
```

**模板 CRUD：**
```
GET /api/announcements/templates?category=custom
  → template_repo.list_templates(category="custom")
  ← 200 {"success":1, "templates": [...], "total": N}

POST /api/announcements/templates
  {name, subject_template, body_template, description?, variables?, category?}
  → template_repo.create_template(...)
  ← 200 {"success":1, "template": {...}}
  缺 name → 400 {"success":0, "error_reason":"missing_field"}

GET /api/announcements/templates/<id>
  → template_repo.get_template_by_id(id)
  存在 → 200; 不存在 → 404

PUT /api/announcements/templates/<id>
  {name?, description?, subject_template?, body_template?, variables?}
  → template_repo.update_template(id, **fields)
  ← 200 / 404

DELETE /api/announcements/templates/<id>
  → template_repo.delete_template(id)
  system → 400 {"error_reason":"cannot_delete_system_template"}
  custom → 200

POST /api/announcements/templates/<id>/preview
  {variables: {...}}
  → preview_template_service(id, variables)
  ← 200 {"success":1, "subject_rendered":..., "body_rendered":...}
```

**目标解析：**
```
POST /api/announcements/resolve-targets
  {targets: [{"type":"machine","id":1}, {"type":"user","id":5}]}
  → resolve_recipients(targets)
  targets 为空 → 400
  ← 200 {"success":1, "recipient_count":18, "summary":[...], "preview_emails":[...]}
```

**公告（仅留存查询 + 操作）：**
```
GET /api/announcements/list?status=sent&status=partial&limit=20&offset=0
  → announcement_repo.list_announcements(status=["sent","partial"], ...)
  ← 200 {"success":1, "announcements":[...], "total":N, "sent_count":N, "partial_count":N, "failed_count":N}

GET /api/announcements/<id>
  → announcement_repo.get_announcement_by_id(id)
  ← 200 / 404

POST /api/announcements/<id>/resend
  → resend_announcement_service(id)
  ← 200 SendResult / 409 SENDING / 404

POST /api/announcements/<id>/copy-as-draft
  → copy_announcement_as_draft_service(id)
  ← 200 {"success":1, "draft_id": N} / 404

POST /api/announcements/<id>/convert-to-template
  → convert_announcement_to_template_service(id)
  ← 200 {"success":1, "template_id":N, "name":"...", "body_template":"...", "variables":"[...]"} / 404
```

**草稿 CRUD（发送界面核心）：**
```
GET /api/announcements/drafts
  → draft_repo.list_drafts(created_by=current_user)
  ← 200 {"success":1, "drafts":[...], "total":N}

POST /api/announcements/drafts/save
  {draft_id: null|N, title, content, raw_content?, template_id?}
  → draft_repo.save_draft(...)
  ← 200 {"success":1, "draft_id":N}

GET /api/announcements/drafts/<id>
  → draft_repo.get_draft_by_id(id)
  ← 200 / 404

DELETE /api/announcements/drafts/<id>
  → draft_repo.delete_draft(id)
  ← 200 / 404

POST /api/announcements/drafts/batch-send
  {draft_ids: [7,8,9], targets: [{"type":"machine","id":1}, ...]}
  → batch_send_drafts_service(draft_ids, targets)
  targets 为空 → 400 {"error_reason":"empty_targets"}
  too_many_recipients → 400
  ← 200 BatchSendResult
```
> **没有单条发送端点**——发送的唯一触发方式是勾选草稿 + 公共操作栏选收件人 + `[批量发送]`。

### 3. 函数级收口（端点签名与请求/响应体）

#### 3.1 所有端点路由表

| 方法 | 路径 | 服务函数 | 请求体关键字段 |
|------|------|---------|--------------|
| `GET` | `/element-definitions` | `get_element_definitions()` | — |
| `GET` | `/templates` | `list_templates()` | query: category, limit, offset |
| `POST` | `/templates` | `create_template()` | name*, subject_template*, body_template*, description, variables, category |
| `GET` | `/templates/<id>` | `get_template_by_id()` | — |
| `PUT` | `/templates/<id>` | `update_template()` | name, description, subject_template, body_template, variables |
| `DELETE` | `/templates/<id>` | `delete_template()` | — |
| `POST` | `/templates/<id>/preview` | `preview_template_service()` | variables* |
| `POST` | `/resolve-targets` | `resolve_recipients()` | targets* |
| `GET` | `/list` | `list_announcements()` | query: status[], limit, offset |
| `GET` | `/<id>` | `get_announcement_by_id()` | — |
| `POST` | `/<id>/resend` | `resend_announcement_service()` | — |
| `POST` | `/<id>/copy-as-draft` | `copy_announcement_as_draft_service()` | — |
| `POST` | `/<id>/convert-to-template` | `convert_announcement_to_template_service()` | — |
| `GET` | `/drafts` | `list_drafts()` | query: limit, offset |
| `POST` | `/drafts/save` | `save_draft()` | draft_id, title*, content*, raw_content, template_id |
| `GET` | `/drafts/<id>` | `get_draft_by_id()` | — |
| `DELETE` | `/drafts/<id>` | `delete_draft()` | — |
| `POST` | `/drafts/batch-send` | `batch_send_drafts_service()` | draft_ids*, targets* |

#### 3.2 端点实现模板（以 `POST /drafts/batch-send` 为例）

```python
@api_bp.post("/announcements/drafts/batch-send")
def batch_send_drafts_api():
    # 1. 认证+授权
    err = _require_operator()
    if err: return err

    # 2. 解析输入
    data = request.get_json(silent=True) or {}
    draft_ids = data.get("draft_ids") or []
    raw_targets = data.get("targets") or []
    targets = [TargetEntry(**t) for t in raw_targets]

    # 3. 调用服务
    try:
        result = announcement_tasks.batch_send_drafts_service(draft_ids, targets)
    except ValueError as e:
        reason = str(e)
        status_map = {
            "empty_targets": 400,
            "too_many_recipients": 400,
            "batch_too_large": 400,
        }
        return jsonify({"success":0, "message":reason, "error_reason":reason}), status_map.get(reason, 400)

    # 4. 返回
    return jsonify({"success":1, **result.model_dump()}), 200
```

### 4. 测试用例（API 层）

| ID | 方法 | 路径 | 条件 | 预期 |
|----|------|------|------|------|
| A-01 | 任意 | 任意 | 无 token | 401, invalid_token |
| A-02 | 任意 | 任意 | USER 权限 | 403, insufficient_permission |
| A-03 | GET | `/element-definitions` | Operator | 200, elements 非空 |
| A-04 | POST | `/templates` | 完整字段 | 200, template |
| A-05 | POST | `/templates` | 缺 name | 400 |
| A-06 | GET | `/templates` | — | 200, 列表 |
| A-07 | GET | `/templates/<id>` | 存在 | 200 |
| A-08 | GET | `/templates/999` | 不存在 | 404 |
| A-09 | PUT | `/templates/<id>` | 部分字段 | 200 |
| A-10 | DELETE | `/templates/<id>` | system | 400 |
| A-11 | DELETE | `/templates/<id>` | custom | 200 |
| A-12 | POST | `/templates/<id>/preview` | variables | 200, 渲染结果 |
| A-13 | POST | `/resolve-targets` | 混合 targets | 200, recipient_count>0 |
| A-14 | POST | `/resolve-targets` | targets=[] | 400 |
| A-15 | GET | `/list` | — | 200, 列表 |
| A-16 | GET | `/list?status=sent&status=partial` | — | 200, 仅两类 |
| A-17 | GET | `/<id>` | 存在 | 200, 详情 |
| A-18 | GET | `/999` | 不存在 | 404 |
| A-19 | POST | `/<id>/resend` | SENT | 200, status=sent |
| A-20 | POST | `/<id>/resend` | SENDING | 409 |
| A-21 | POST | `/<id>/copy-as-draft` | SENT | 200, draft_id |
| A-22 | POST | `/<id>/convert-to-template` | SENT, 含 {{}} | 200, template_id + variables |
| A-23 | POST | `/<id>/convert-to-template` | SENT, 纯文本 | 200, variables=[] |
| A-24 | POST | `/drafts/save` | draft_id=null | 200, draft_id |
| A-25 | POST | `/drafts/save` | 已有 draft_id | 200, 同 id |
| A-26 | GET | `/drafts` | — | 200, 列表 |
| A-27 | GET | `/drafts/<id>` | 存在 | 200, 详情 |
| A-28 | DELETE | `/drafts/<id>` | 存在 | 200 |
| A-29 | DELETE | `/drafts/999` | 不存在 | 404 |
| A-30 | POST | `/drafts/batch-send` | draft_ids + targets | 200, N results |
| A-31 | POST | `/drafts/batch-send` | targets 为空 | 400, empty_targets |
| A-32 | POST | `/drafts/batch-send` | >200 收件人 | 400, too_many_recipients |
| A-33 | POST | `/drafts/batch-send` | draft_ids 含不存在的 id | 200, 该条 error, 其余正常 |
| A-34 | POST | `/drafts/batch-send` | >20 条 draft | 400 |

---

## 前端 UI 契约（参考）

### 三个界面及其入口关系

```
┌──────────────────────────────────────────────────────────────────┐
│  发送界面（主门户）                                                │
│                                                                  │
│  ┌─ 顶部导航 ────────────────────────────────────────────────┐  │
│  │  [创建公告]  [模板管理]                                     │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ 收件人选择栏（公共操作区）────────────────────────────────┐  │
│  │  🖥 GPU-01 ✕  👤 张三 ✕  [+ 添加目标]   收件人: 18人      │  │
│  │  [批量发送]（对所有已勾选草稿发送）                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ 待发送区（草稿卡片）─────────────────────────────────────┐  │
│  │                                                            │  │
│  │  ┌──────────────────────┐  ┌──────────────────────┐       │  │
│  │  │ ☐ 草稿标题            │  │ ☑ 另一草稿（已勾选）   │       │  │
│  │  │                      │  │                      │       │  │
│  │  │ 正文摘要预览...       │  │ 正文摘要预览...       │       │  │
│  │  │                      │  │                      │       │  │
│  │  │    [✎ 编辑] [🗑 删除]│  │    [✎ 编辑] [🗑 删除]│       │  │
│  │  └──────────────────────┘  └──────────────────────┘       │  │
│  │                                                            │  │
│  │  点击卡片空白区 = ☑勾选    [✎]/[🗑] 均在卡片内部          │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ 已发送区 ────────────────────────────────────────────────┐  │
│  │  ┌──────────────────────────┐  ┌──────────────────────────┐│  │
│  │  │ 公告标题  | 收件人:18     │  │ 另一公告  | 收件人:5      ││  │
│  │  │ 发送于 06-11  | SENT ✓  │  │ 发送于 06-10  | SENT ✓  ││  │
│  │  │ [重发] [复用] [转模板]   │  │ [重发] [复用] [转模板]   ││  │
│  │  └──────────────────────────┘  └──────────────────────────┘│  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │ 点击 [创建公告] / [✎ 编辑]        │ 点击 [模板管理]
         ▼                                    ▼
┌──────────────────────┐        ┌──────────────────────────────┐
│  公告编辑界面         │        │  模板管理列表                 │
│  （纯正文编辑，       │        │  [新建模板]                   │
│   无目标选择器）      │        │  模板1 [编辑] [删除]          │
│                      │        └──────────────────────────────┘
│  左侧：标题 + 正文    │                    │
│                      │                    ▼
│  右侧：元素快填       │        ┌──────────────────────────────┐
│  右侧：模板选择       │        │  模板编辑界面                  │
│   [+ 编辑此模板]     │        │  正文编辑 + 变量添加器          │
│                      │        └──────────────────────────────┘
│  底部：[保存草稿]     │
└──────────────────────┘
```

### 关键交互规则

| 操作 | 位置 | 效果 |
|------|------|------|
| 点击草稿卡片空白区 | 待发送区 | ☑ 勾选/取消勾选 |
| 点击卡片内 **[✎ 编辑]** | 待发送区卡片内部 | 进入公告编辑界面（纯正文编辑，无目标选择器） |
| 点击卡片内 **[🗑 删除]** | 待发送区卡片内部 | 删除该草稿 |
| 点击公共栏 **[+ 添加目标]** | 收件人选择栏 | 弹出目标选择器（机器/容器/用户），调 `resolve-targets` 预览收件人数 |
| 公共栏目标标签 ✕ | 收件人选择栏 | 移除该目标，刷新收件人预览 |
| 点击 **[创建公告]** | 顶部导航 | 进入空白公告编辑界面 → 保存草稿 → 回到待发送区 |
| 点击 **[批量发送]** | 收件人选择栏 | 公共栏收件人 + 所有☑草稿 → `POST /drafts/batch-send` |
| 已发送区 **[复用]** | 已发送区卡片内部 | 生成新草稿（含原公告标题/正文/目标/模板） |
| 已发送区 **[重发]** | 已发送区卡片内部 | 沿用原 targets 重新发送 |
| 已发送区 **[转模板]** | 已发送区卡片内部 | 提取 `{{}}` 变量 → 进入模板编辑界面 |

### 各界面职责

1. **发送界面**（主门户）
   - 顶部导航：`[创建公告]` → 编辑器；`[模板管理]` → 模板列表
   - **收件人选择栏**（公共操作区）：目标选择器 + 收件人预览 + `[批量发送]`
     - 在此处选择的收件人对所有被勾选的草稿生效
     - 选好后调 `resolve-targets` 即时预览人数
   - **待发送区**：`GET /drafts`。卡片 = 勾选框 + 正文摘要 + 卡片内 `[✎]` `[🗑]`
     - 不含目标编辑——目标是公共栏的事
   - **已发送区**：`GET /list`。卡片 = 公告信息 + 卡片内 `[重发]` `[复用]` `[转模板]`

2. **公告编辑界面**（纯正文编辑，无目标选择器）
   - 左侧：标题 + 正文编辑区
   - 右侧：元素快填（`GET /element-definitions`）+ 模板选择（`GET /templates`）+ `[编辑此模板]`
   - 底部：仅 `[保存草稿]`

3. **模板编辑界面**（从 4 个入口进入）
   - 左侧：模板名 + 描述 + 主题模板 + 正文模板（`{{key}}` 高亮蓝色）
   - 右侧：变量添加器
   - 底部：`[保存模板]`
