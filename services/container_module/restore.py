from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from ...constant import OperationType, ROLE
from ...extensions import session_scope
from ...repositories import (
    container_mount_cleanup_repo,
    containers_repo,
    deleted_container_restore_snapshot_repo,
    long_term_container_repo,
    user_repo,
)
from ...utils.Container import Container_info
from ..image_tasks import DockerfileParts, format_image_build_tag
from ..operation_log_tasks import log_failure, log_success
from .deleted_containers import (
    delete_restore_artifacts,
    restore_accounts_from_snapshot,
)
from .exceptions import NodeServiceError
from .utils import _container_log_detail, container_dockerfile_parts

####################################################
# 恢复工具族（复活软删容器）
# 门户 resurrect_container / clean_deleted_container_mount 在 services/container_tasks.py。
# 顺序 = 门户调用顺序：读快照 → 读账号 → 组容器 → 复用 Create_container 复活原行
# → 恢复长期态 → 清退恢复产物 → 审计。
# 命名冲突：原名被占用时自动改名 {name}_{YYYYMMDD}_{原 id}（带重试）。
# 恢复失败与 mount 预检失败的审计也在这里（各一条，互不重复）。
####################################################

def _resolve_restore_container_name(
    name: str,
    machine_id: int,
    original_container_id: int,
    removed_at: datetime | None,
) -> tuple[str, bool]:
    with session_scope(commit=False) as session:
        existing_id = containers_repo.get_id_by_name_machine(
            name,
            machine_id,
            session=session,
        )
    if not existing_id or int(existing_id) == int(original_container_id):
        return name, False

    suffix_date = (removed_at or datetime.utcnow()).strftime("%Y%m%d")
    for attempt in range(1, 100):
        suffix = (
            f"_{suffix_date}_{original_container_id}"
            if attempt == 1
            else f"_{suffix_date}_{original_container_id}_{attempt}"
        )
        stem = (name or "container")[: max(2, 115 - len(suffix))]
        candidate = f"{stem}{suffix}"[:115]
        with session_scope(commit=False) as session:
            candidate_id = containers_repo.get_id_by_name_machine(
                candidate,
                machine_id,
                session=session,
            )
        if not candidate_id or int(candidate_id) == int(original_container_id):
            return candidate, True

    raise NodeServiceError(
        "failed to allocate restore container name",
        reason="container_exists",
    )


@dataclass(frozen=True)
class _RestoreTarget:
    """恢复上下文：一次读齐后续步骤要用的快照信息（只读，步骤间不再回查）。"""
    snapshot: dict
    container_id: int
    machine_id: int
    mount_path: str
    mount_cleanup_id: int | None
    removed_at: datetime | None
    # 镜像归属：优先容器行的新列，回落快照。存量快照只有 image 字符串，故可空。
    image_id: int | None = None
    # 该容器上次构建所依据的模板版本时刻（容器行上的留痕）——判定"是否落后"用。
    image_version_at: datetime | None = None
    # 该容器留存的配方（见 models/containers.py）——精确还原的内容来源。
    # 注意平台注入取自**当下设置**而非容器行（它不落库）。
    dockerfile_parts: DockerfileParts | None = None

    # 这里曾有一个 snapshot_tag 属性，从**已删容器快照 JSON** 的 "image" 键取运行标签，
    # 作为标签推导失败时的回落。已删除：那个键是软删时代的数据载体，而标签是**派生值**
    # （fuxi/image-{image_id}:{last_build_at}），两个输入都在容器行上——回落读取等于
    # 让一个多余载体参与业务，且会让"推导不出标签"这种异常状态被静默掩盖。
    # 现在推导不出来就是推导不出来，由 _build_restore_container 的非空校验拦下。
    # 注：JSON 里的 "image" 键**本身仍保留**——已删列表出参要用它展示。


@dataclass(frozen=True)
class _RestoreImage:
    """恢复采用的内容来源解析结果。

    `needs_choice` 为真表示**这里存在真正的二选一**——两份内容不同，用户可选。
    它**不是**"拒绝"信号，描述的是处境而不是传参：调用方没指定内容来源、且确实面临
    二选一时，恢复门户据此把两份内容交回去让他选（见 container_tasks.resurrect_container）。

    公布由后端裁决而不是由调用方传参触发：容器留痕是完整配方，不因为有人调了接口
    就交出去——只有在这台容器确实面临二选一时才给。
    """
    mode: str                             # template / snapshot
    image_tag: str                        # 运行镜像标签（Node 的 config.image）
    image_build: dict | None              # 发给 Node 的构建段
    image_id: int | None
    version_at: datetime | None           # 落库的构建版本戳
    dockerfile_parts: DockerfileParts | None   # 本次采用的那份配方（渲染前的形态）
    needs_choice: bool = False


# 恢复时的内容来源选择（仅用于「模板 READY 但已是新版」那一支）
CONTENT_SOURCE_SNAPSHOT = "snapshot"
CONTENT_SOURCE_TEMPLATE = "template"
RESTORE_MODES = (CONTENT_SOURCE_SNAPSHOT, CONTENT_SOURCE_TEMPLATE)


def _audit_restore_failure(deleted_id, operator_user_id, exc) -> None:
    """失败审计：尽力从快照回捞容器身份；查不到也照记（target_id=0），不吞原异常。"""
    target_id = 0
    container_name = None
    machine_id = None
    try:
        with session_scope(commit=False) as session:
            deleted = deleted_container_restore_snapshot_repo.get_by_id(
                int(deleted_id),
                session=session,
            )
            if deleted is not None:
                snapshot = dict(deleted.snapshot or {})
                target_id = int(
                    snapshot.get("container_id")
                    or deleted.original_container_id
                    or 0
                )
                container_name = snapshot.get("container_name")
                machine_id = deleted.machine_id or snapshot.get("machine_id")
    except Exception:
        pass
    log_failure(
        OperationType.CREATE_CONTAINER,
        target_id,
        target_type="container",
        operator_user_id=operator_user_id,
        container_name=container_name,
        machine_id=machine_id,
        error_reason=getattr(exc, "reason", None)
        or getattr(exc, "error_reason", None)
        or str(exc),
        detail={"trigger": "resurrect", "deleted_id": deleted_id},
    )


def _load_restore_target(deleted_id: int) -> _RestoreTarget:
    """读恢复上下文，并做可恢复性预检。

    预检不过一律抛 NodeServiceError（reason 供 api 层映射状态码）：
    快照缺失 / 快照为空 / 无保留挂载路径 / 挂载已被清理 / 缺 machine_id 或原容器 id。
    """
    try:
        deleted_id = int(deleted_id)
    except Exception:
        raise NodeServiceError("invalid deleted_id", reason="invalid_payload")

    with session_scope(commit=False) as session:
        deleted = deleted_container_restore_snapshot_repo.get_by_id(
            deleted_id,
            session=session,
        )
        if deleted is None:
            raise NodeServiceError(
                "deleted container snapshot not found",
                reason="not_found",
            )
        cleanup = (
            container_mount_cleanup_repo.get_by_id(
                deleted.mount_cleanup_id,
                session=session,
            )
            if deleted.mount_cleanup_id
            else None
        )
        snapshot = dict(deleted.snapshot or {})
        if not snapshot:
            raise NodeServiceError(
                "deleted container snapshot is empty",
                reason="data_not_recoverable",
            )
        original_container_id = int(
            snapshot.get("container_id")
            or deleted.original_container_id
            or 0
        )
        container_record = (
            containers_repo.get_by_id(
                original_container_id,
                session=session,
                include_invalid=True,
            )
            if original_container_id
            else None
        )
        mount_path = (
            getattr(container_record, "bind_mount_path", None)
            or (getattr(cleanup, "mount_path", None) if cleanup else None)
            or snapshot.get("bind_mount_path")
        )
        if not mount_path:
            raise NodeServiceError(
                "deleted container has no retained mount path",
                reason="data_not_recoverable",
            )
        if bool(getattr(deleted, "mount_cleaned", False)):
            raise NodeServiceError(
                "deleted container mount has been cleaned",
                reason="data_not_recoverable",
            )
        machine_id = int(deleted.machine_id or snapshot.get("machine_id") or 0)
        if container_record is not None:
            machine_id = int(container_record.machine_id)
        mount_cleanup_id = deleted.mount_cleanup_id
        removed_at = deleted.removed_at
        # 快照优先（记录删除当刻的归属），回落容器行 —— 容器行的 image_id 可能已被
        # 启动回填补齐，而旧快照里根本没有这个键。
        image_id = snapshot.get("image_id") or getattr(container_record, "image_id", None)
        # 版本戳与配方只存在于容器行（快照 JSON 里没有），且容器行可能为 None
        # （原容器行已被清理）——两者都可空。
        image_version_at = getattr(container_record, "last_build_at", None)
        dockerfile_parts = container_dockerfile_parts(container_record) if container_record else None

    if not machine_id:
        raise NodeServiceError(
            "deleted container snapshot has no machine_id",
            reason="invalid_payload",
        )
    if not original_container_id:
        raise NodeServiceError(
            "deleted container snapshot has no original container id",
            reason="data_not_recoverable",
        )

    return _RestoreTarget(
        snapshot, original_container_id, machine_id, mount_path, mount_cleanup_id, removed_at,
        int(image_id) if image_id else None,
        image_version_at,
        dockerfile_parts,
    )


def _load_restore_accounts(snapshot: dict) -> tuple[dict, list[dict]]:
    """读账号：root（owner）必须仍存在；协作者逐个回查系统用户名，已注销的直接跳过。"""
    root_account, restored_accounts = restore_accounts_from_snapshot(snapshot)
    owner_user_id = root_account.get("user_id")
    if not owner_user_id:
        raise NodeServiceError(
            "deleted container snapshot has no owner user",
            reason="invalid_payload",
        )
    with session_scope(commit=False) as session:
        owner_name = user_repo.get_name_by_id(owner_user_id, session=session)
    if not owner_name:
        raise NodeServiceError(
            "deleted container owner no longer exists",
            reason="data_not_recoverable",
        )

    existing_accounts = []
    for account in restored_accounts:
        user_id = account.get("user_id")
        role_value = account.get("role") or ROLE.COLLABORATOR.value
        try:
            role = ROLE(role_value) if not isinstance(role_value, ROLE) else role_value
        except Exception:
            role = ROLE.COLLABORATOR
        if user_id is None or role == ROLE.ROOT:
            continue
        with session_scope(commit=False) as session:
            system_username = user_repo.get_name_by_id(user_id, session=session)
        if not system_username:
            continue
        existing_accounts.append(
            {
                **account,
                "user_id": int(user_id),
                "system_username": system_username,
                "role": role.value,
                "container_username": account.get("container_username")
                or system_username,
            }
        )

    return root_account, existing_accounts


def _is_behind(image_version_at, template_updated_at) -> bool:
    """容器是否落后于模板（口径与展示出口共用，见 utils.is_version_behind）。"""
    from .utils import is_version_behind

    return is_version_behind(image_version_at, template_updated_at)


def _restore_from_snapshot(target: _RestoreTarget) -> _RestoreImage:
    """用容器留存的配方重建。

    留痕**就是产出该标签的那份配方**，标签与内容由构造保证一致——因此这条路径
    不违反"不能旧标签配新内容"（那会让同一个标签指向不同内容，破坏 Node 的标签缓存）。

    标签**只由归属标识 + 版本戳推导，没有回落**：那个回落曾读已删快照 JSON 里的 tag，
    是让多余载体参与业务，而且会掩盖"推导不出标签"这种异常状态。推不出来就让它推不出来，
    由 `_build_restore_container` 的非空校验拦下（干净设计下不该发生——容器一定有归属）。

    **没有留痕时直接抛错，不降级。** 容器恒有留痕（Create 与 Resurrect 都写），没有就是
    数据损坏。这里曾经降级成"不发构建段、按标签直接跑"，那会让一个损坏状态**看起来像
    一次成功恢复**，并且把能否恢复交给"宿主机上还留着旧制品吗"去赌——正是本次改造要
    消灭的那种赌。
    """
    # 标签由「归属标识 + 构建版本戳」推导（format_image_build_tag），没有回落：那个回落曾读
    # 已删快照 JSON 里的 tag，是让多余载体参与业务，还会掩盖"推导不出来"这种异常状态。
    # 推不出来就让它推不出来，由 _build_restore_container 的非空校验拦下。
    #
    # ⚠ **刻意不传 machine_id**：这条路径的配方是**容器自己那份**（target.dockerfile_parts），
    # 而新鲜度预检查返回的是机器级的**当前**标签。两者拼在一起就成了"新标签配旧内容"——
    # 与"旧标签配新内容"同样是让同一个标签指向不同内容，同样破坏 Node 的标签缓存。
    # 版本戳必须沿用该容器原有的值，标签也必须由同一对输入推出。
    tag = format_image_build_tag(target.image_id, target.image_version_at)
    parts = target.dockerfile_parts
    if parts is None:
        raise NodeServiceError(
            "container has no image snapshot to restore from",
            reason="data_not_recoverable",
        )
    return _RestoreImage(
        mode=CONTENT_SOURCE_SNAPSHOT,
        image_tag=tag,
        image_build={"image_tag": tag, "dockerfile_text": parts.render()},
        image_id=target.image_id,
        # 内容没变，版本戳沿用该容器原有的值——不能刷新成当前时间，否则会谎称
        # 它是按最新模板建的。
        version_at=target.image_version_at,
        dockerfile_parts=parts,
    )


def _restore_from_template(build) -> _RestoreImage:
    """用当前模板的配方重建（正常拼装流程）。"""
    return _RestoreImage(
        mode=CONTENT_SOURCE_TEMPLATE,
        image_tag=build.payload["image_tag"],
        image_build=build.payload,
        image_id=build.image_id,
        version_at=build.version_at,
        dockerfile_parts=build.dockerfile_parts,
    )


def _resolve_restore_image(
    target: _RestoreTarget, content_source: str | None = None,
) -> _RestoreImage:
    """解析恢复采用哪份内容（design D3）。

    **默认一律取容器自己的快照**——它记录着该容器实际跑过的那份配方，是这个容器唯一
    权威的内容来源。模板只在两处进入：

    1. **归属为空，或所用模板不处于 READY**（草稿 / 已停用）→ 只能取快照。
       非 READY 的当前内容不是"该容器曾使用的配方"：草稿尚未定稿，停用已被撤下。
       这条也覆盖"把模板退回草稿去编辑"的窗口——恢复不会拿到改了一半的内容。
       取模板走 `get_by_id` 原语，不受停用过滤影响。
    2. **调用方显式指定 `template`** → 才用当前模板渲染。这是唯一会让容器内容改变的
       路径，因而必须显式；"按新"永不作为默认。

    容器恒有快照（Create 与 Resurrect 都写），因此这里不假设它可能缺失。
    """
    from ..image_tasks import ImageStatus, resolve_image_build

    # ── 分支①：归属为空 ──
    if not target.image_id:
        return _restore_from_snapshot(target)

    build = resolve_image_build(int(target.image_id), target.machine_id)
    template = _load_template_row(int(target.image_id))

    # ── 分支①续：模板不存在或非 READY ──
    if build is None or template is None or template.status != ImageStatus.READY:
        return _restore_from_snapshot(target)

    # ── 分支③：模板 READY 但容器落后 —— **这里存在真正的二选一** ──
    # 两份内容会不同（容器留痕 vs 当前模板），因此在这里标 needs_choice。
    # 恢复门户**只在这个标记为真时**才把两份内容交回去（含容器的留痕）——
    # 不因为"调用方传了参数"就公布：那等于把容器的完整配方泄给任何会调这个接口的人。
    #
    # 内容本身**默认取留痕**（容器实际跑过的那份）；要应用最新模板必须显式指定
    # `template`。"按新"永远不是默认，那等于替用户换掉他容器里的内容。
    # 比的是**模板的当前版本**（不是 build.version_at——那是这次的制品版本戳，
    # 现造时等于 now()，拿它比会把每个容器都判成落后）
    if _is_behind(target.image_version_at, template.updated_at):
        resolved = (
            _restore_from_template(build)
            if content_source == CONTENT_SOURCE_TEMPLATE
            else _restore_from_snapshot(target)
        )
        # 没有留痕就没有"二选一"可言（只剩模板一份内容），不标记——因而也不交回。
        return replace(resolved, needs_choice=target.dockerfile_parts is not None)

    # ── 分支②：模板 READY 且版本符合 ──
    return _restore_from_template(build)


def build_restore_choice(target: _RestoreTarget) -> dict:
    """存在二选一时，给出两份内容与分段差异（design D14）。

    **由恢复请求本身触发**（不带内容来源、且确实面临二选一时返回它），不是一个独立的
    查询接口。这样公布面只有一处：只有真的发起恢复、且这台容器确实有两份可选内容时，
    容器留痕才会被交出去——不会因为"有人调了某个接口"就泄露。

    差异**按配方分段**组织（基础镜像 / 业务片段）。**平台注入段刻意不列**：它两侧都取
    当下的系统设置，按构造恒等——列一个永远"无变化"的段只是噪音，而它曾经会变，是因为
    旧实现把注入也存进了容器留痕（已废弃，见 models/containers.py）。
    """
    from ..image_tasks import resolve_image_build

    snapshot_parts = target.dockerfile_parts
    if snapshot_parts is None:
        # 调用点保证非 None（needs_choice 正是由它派生的）。真到了这里说明有代码绕过了
        # 那个判断——抛错，不要渲染出一份空配方冒充"容器的内容"。
        raise NodeServiceError(
            "restore choice requested but the container has no recipe",
            reason="unexpected_response",
        )
    template_parts = resolve_image_build(int(target.image_id)).dockerfile_parts
    return {
        "requires_choice": True,
        "snapshot": {"dockerfile": snapshot_parts.render()},
        "template": {"dockerfile": template_parts.render()},
        "sections": _diff_dockerfile_sections(template_parts, snapshot_parts),
    }


def _diff_dockerfile_sections(
    template_parts: DockerfileParts, snapshot_parts: DockerfileParts,
) -> list[dict]:
    """逐段比较两份配方，标出哪一段变了。

    段的边界就是配方的字段本身（FROM / 业务片段），因此这里做的是**逐字段比对**，不需要
    从渲染后的文本里反解段边界。这正是"存输入而不是存渲染结果"换来的收益之一：
    那套"文本是否仍整体出现在对方里"的启发式已经删除。

    平台注入不在比较之列——两侧都取当下的系统设置（见 container_dockerfile_parts），
    按构造恒等。

    两侧都空的段不列——没变，也没什么可看的（内置模板的业务片段就是空的）。
    """
    pairs = (
        ("base_image", template_parts.base_image, snapshot_parts.base_image),
        ("dockerfile_body", template_parts.dockerfile_body, snapshot_parts.dockerfile_body),
    )
    sections = []
    for name, template_text, snapshot_text in pairs:
        template_text = (template_text or "").strip()
        snapshot_text = (snapshot_text or "").strip()
        if not template_text and not snapshot_text:
            continue
        sections.append({"name": name, "changed": template_text != snapshot_text})
    return sections


def _load_template_row(image_id: int):
    """取模板行；模板不存在返回 None。

    刻意走 `get_by_id` 原语（不过滤停用）：过滤了就分辨不出"不存在"与"已停用"，
    而这两种情形在本判定里都要落到快照分支，诊断信息却不同。

    返回**整行**而不只是状态：落后判定要比容器那一版与模板的**当前版本**
    （`images.updated_at`），而新口径下 `build.version_at` 是**制品自己的版本戳**，
    两者已经不是同一个东西了（2026-09 决策）。
    """
    from ...repositories import image_repo

    with session_scope(commit=False) as session:
        return image_repo.get_by_id(int(image_id), session=session)


def _build_restore_container(target: _RestoreTarget, image_tag: str) -> tuple[Container_info, bool]:
    """组包：按快照重建 Container_info；原名被占用时用改名结果（返回 renamed 供审计）。

    image_tag 由 _resolve_restore_image 解析后传入，进 Node 的 config.image；它恒等于
    同一份解析结果里 image_build 的标签（Node 用它作构建产物的名字，两者必须是同一个，
    否则同一个标签会指向不同内容，破坏 Node 侧按标签判定的构建缓存）。
    """
    snapshot = target.snapshot
    restore_name, restore_renamed = _resolve_restore_container_name(
        str(snapshot.get("container_name") or ""),
        target.machine_id,
        target.container_id,
        target.removed_at,
    )
    container = Container_info(
        gpu_list=list(snapshot.get("gpu_chosen_list") or []),
        cpu_number=int(snapshot.get("cpu_number") or 0),
        memory=int(snapshot.get("memory_gb") or 0),
        shared_memory=int(snapshot.get("shared_gb") or 0),
        name=restore_name,
        image=image_tag,
        port=0,
    )
    if not container.NAME or not container.image:
        # 两个成因相互独立，错误信息要分开——否则用户会去查错的东西：
        # - 名字为空：快照损坏
        # - 标签为空：推不出运行标签。标签是派生值（归属标识 + 构建版本戳），
        #   没有回落可退；推不出来意味着该容器缺少归属或缺少版本戳，
        #   而干净设计下两者都不该缺失（容器一定有归属，构建必然留下版本戳）。
        raise NodeServiceError(
            "deleted container snapshot lacks name"
            if not container.NAME
            else "cannot derive image tag for restore: container lacks image_id or last_build_at",
            reason="invalid_payload",
        )

    return container, restore_renamed


def _get_restored_container_id(container_name: str, machine_id: int) -> int:
    """回查复活后的容器 id（Create_container 只返回 bool，id 需按名字+机器再查一次）。"""
    with session_scope(commit=False) as session:
        container_id = containers_repo.get_id_by_name_machine(
            container_name=container_name,
            machine_id=machine_id,
            session=session,
        )
    if not container_id:
        raise NodeServiceError(
            "resurrected container record not found",
            reason="unexpected_response",
        )

    return int(container_id)


def _restore_long_term_state(container_id: int, snapshot: dict, operator_user_id: int | None) -> None:
    """恢复长期态：快照里是长期容器才补长期标记（否则不动）。"""
    if snapshot.get("is_long_term"):
        with session_scope() as session:
            long_term_container_repo.add(
                container_id,
                created_by_user_id=operator_user_id,
                session=session,
            )


def _delete_restore_artifacts(deleted_id: int, mount_cleanup_id: int | None) -> None:
    """清退恢复产物：恢复成功后删除 deleted 快照与 mount 清理记录（容器已复活）。"""
    with session_scope() as session:
        delete_restore_artifacts(deleted_id, mount_cleanup_id, session=session)


def _audit_restore_success(
    deleted_id, target, container_id, container, restore_renamed, restored_accounts_count,
    operator_user_id, restore_image: dict | None = None,
) -> None:
    """成功审计：恢复记一条 CREATE_CONTAINER（trigger=resurrect），含改名与原始名字对照。

    restore_image 记下这次恢复用的是哪份内容（template = 此刻的模板 / snapshot = 容器
    自己那份配方）——用模板重建出来的是「此刻的模板」而非容器当初那个制品，不记就无从
    事后分辨。
    """
    log_success(
        operator_user_id=operator_user_id,
        operation=OperationType.CREATE_CONTAINER,
        target_type="container",
        target_id=container_id,
        detail={
            "trigger": "resurrect",
            "deleted_id": deleted_id,
            "original_container_id": target.snapshot.get("container_id"),
            "restore_original_name": str(target.snapshot.get("container_name") or ""),
            "restore_renamed": restore_renamed,
            **_container_log_detail(container.NAME),
            "machine_id": target.machine_id,
            "restore_mount_path": target.mount_path,
            "restored_accounts": restored_accounts_count,
            **(restore_image or {}),
        },
    )


def _audit_mount_preflight_failure(deleted_id, mount_cleanup_id, operator_user_id, exc) -> None:
    """失败审计：手动 mount 清理在"解析入参"阶段就失败的场景（还没走到 clean_mount_path）。"""
    detail = {
        "trigger": "manual_clean_mount",
        "deleted_id": deleted_id,
        "mount_cleanup_id": mount_cleanup_id,
    }
    try:
        with session_scope(commit=False) as session:
            deleted = (
                deleted_container_restore_snapshot_repo.get_by_id(
                    int(deleted_id),
                    session=session,
                )
                if deleted_id is not None
                else None
            )
            legacy_cleanup = (
                container_mount_cleanup_repo.get_by_id(
                    int(mount_cleanup_id),
                    session=session,
                )
                if mount_cleanup_id is not None
                else None
            )
            context = deleted if deleted is not None else legacy_cleanup
            if context is not None:
                detail.update(_container_log_detail(context.container_name))
                detail["machine_id"] = context.machine_id
    except Exception:
        pass
    log_failure(
        operation=OperationType.DELETE_CONTAINER,
        target_type="container_mount_cleanup",
        target_id=int(mount_cleanup_id or 0),
        operator_user_id=operator_user_id,
        detail=detail,
        error_reason=getattr(exc, "reason", None) or str(exc),
    )
