from datetime import datetime

from ..extensions import db
from ..constant import *


class Container(db.Model):
    __tablename__ = "containers"

    id: int = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=True)
    name: str = db.Column(db.String(120), nullable=False)
    is_valid: bool = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("1"))
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_trigger: str = db.Column(db.String(64), nullable=True)
    deleted_reason: str = db.Column(db.String(255), nullable=True)
    deleted_by_user_id: int = db.Column(db.Integer, nullable=True)
    # ── 镜像归属与构建留痕（2026-09 决策） ──
    # image_id：逻辑真源。容器由哪个镜像模板（images.id）而来；重建/恢复据此解析。
    #   此前是拿 tag 字符串正则反解 id —— 格式一变就断。
    #   外键**不带 ondelete**（默认 NO ACTION）：模板的移除表现为「停用」而非删除
    #   （见 image-template-lifecycle），因此外键永不触发，归属标识的值也永不改变。
    #   "当初构建自哪个模板"是一个**事实**，不能因为模板被移除就抹掉。
    image_id: int | None = db.Column(
        db.Integer, db.ForeignKey("images.id"), nullable=True, index=True
    )
    # last_build_at：本次构建所依据的**模板版本时刻**（= 派发构建时读到的 images.updated_at，
    #   不是 now()）。承担两件事：判定容器是否落后于模板；让镜像标签可推导
    #   （fuxi/image-{image_id}:{last_build_at}），因此标签本身不落库。
    last_build_at: datetime | None = db.Column(db.DateTime, nullable=True)
    # ── 本次构建的配方留痕：模板侧的两个输入（2026-09 二次决策） ──
    # 存**输入**而不是渲染后的整段文本：渲染结果是派生值（拼一下就有的东西），落库就等于
    # 给同一个事实造第二个来源。名字与 images 表的列、与渲染函数的形参逐一对应：
    #   base_image      ← images.base_image（FROM 那一段）
    #   dockerfile_body ← images.dockerfile_body（业务片段那一段）
    #
    # **平台注入不在这里**，它永远取当下的系统设置
    # （services/settings_tasks.get_image_platform_injection_content）。理由是它不是用户的
    # 内容而是平台设施：容器该带的是**现在这一版** sshd 那套注入，不是它当年那版。因此
    # 存一份旧的就成了"谁也不需要的历史副本"，而它偏偏还是会被抄进每一行新数据的派生值。
    #
    # 判"有没有留痕"看 base_image：FROM 是 Dockerfile 的结构必需项，业务片段可以合法为空
    # （内置模板就是空的）。渲染文本由 services/container_module/utils 的
    # container_image_dockerfile 现算，不落库。
    # 两者 MUST NOT 参与身份与新鲜度的判断：归属只看 image_id，落后只看 last_build_at。
    base_image: str | None = db.Column(db.String(255), nullable=True)
    dockerfile_body: str | None = db.Column(db.Text, nullable=True)
    # 这里曾有 runtime_image（旧版写入的镜像标签字符串）。已退役：标签是**派生值**
    #   （format_image_build_tag 由归属标识 + 版本戳算出），存一份就是本变更一路在清理的
    #   那种"第二来源"。它的读点（展示回落）本就在推导成功时永远轮不到，写点却每行都抄一份。
    #   退役时机见 __init__._retire_runtime_image——旧库里它是 NOT NULL，不删掉就插不进新行。
    # 外键列：引用 machines.id
    machine_id: int = db.Column(
        db.Integer, db.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 关系：指向 Machine
    machine = db.relationship("Machine", back_populates="containers")

    #只是修复了注释性错误，之前写成了 "MachineStatus" 而不是 "ContainerStatus"
    container_status: ContainerStatus = db.Column(
        db.Enum(ContainerStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=ContainerStatus.CREATING
    )
    failed_reason: str = db.Column(db.String(255), nullable=True)
    failed_detail: str = db.Column(db.Text, nullable=True)
    # ── 容器轴 unknown 标记（2026-09-03 决策，仿机器轴 collect_error） ──
    # 容器自身状态不可知（node 冷启动复核中/对账异常等）时置位，不改 container_status
    # （保持最后已知为真）；展示派生 status_unknown。恢复由正常快照清除。
    status_unknown_since = db.Column(db.DateTime, nullable=True)
    status_source: str = db.Column(db.String(40), nullable=True)
    port: int = db.Column(db.Integer, nullable=False, index=True)

    memory_gb: int = db.Column(db.Integer, nullable=False)
    shared_gb: int = db.Column(db.Integer, nullable=False)
    gpu_number: int = db.Column(db.Integer, nullable=False)
    cpu_number: int = db.Column(db.Integer, nullable=False)
    # ── GPU 三集合建模（2026-08-30 决策） ──
    # gpu_chosen_list：分配——创建时在机器 allow_list 内选定并锁定的物理卡集合
    gpu_chosen_list: list | None = db.Column(db.JSON, nullable=True)
    # 端口映射（2026-08 决策）：docker 自动分配后由 WSS 快照回填，
    # [{container_port, host_port, protocol}]；port = 22 的宿主端口。
    port_mappings: list | None = db.Column(db.JSON, nullable=True)

    # 磁盘用量快照（bytes），定期检测时更新。
    # disk_limit_bytes 已移除（2026-09-01 决策）：容器磁盘上限统一以
    # machine.max_disk_size_gb 现算派生，不再落库机器级快照拷贝。
    disk_overlay_rw_bytes: int = db.Column(db.BigInteger, nullable=True)
    disk_bind_mount_bytes: int = db.Column(db.BigInteger, nullable=True)
    disk_total_bytes: int = db.Column(db.BigInteger, nullable=True)
    disk_checked_at = db.Column(db.DateTime, nullable=True)

    # 宿主机 bind mount 路径，磁盘检测时由 NodeKernel 返回并持久化
    # 示例: /home/alice/containers/test_container/
    bind_mount_path: str = db.Column(db.String(512), nullable=True)

    users = db.relationship(
        "User",
        secondary="user_container",
        back_populates="containers",
        overlaps="user_container_links"  # 添加此参数
    )

    user_container_links = db.relationship(
        "UserContainer",
        back_populates="container",
        cascade="all, delete-orphan",
        overlaps="containers,users"  # 添加此参数
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Container {self.name} on machine={self.machine_id}>"

    # 无 (name, machine_id) 唯一约束：软删要求「删掉即释放名字」，而唯一索引会让已删行
    # 继续占名（除非再引入一个派生列做 NULL 技巧，那套已废弃）。
    # 「单机内活容器名唯一」这个不变式的真正守卫在 Node 侧——docker daemon 本身就拒绝
    # 同名容器，而创建链路是「请求 Node → 成功才落库」，失败发生在落库之前，不会留下重复行。
    # Ctrl 侧的 validate_create_params → check_duplicate_container_name 只负责给出可读的 409。
    __table_args__ = (
        db.Index("idx_containers_is_valid", "is_valid"),
    )
