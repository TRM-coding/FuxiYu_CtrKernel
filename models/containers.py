from ..extensions import db
from ..constant import *


class Container(db.Model):
    __tablename__ = "containers"

    id: int = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=True)
    name: str = db.Column(db.String(120), nullable=False)
    image: str = db.Column(db.String(200), nullable=False)
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

    __table_args__ = (
        db.UniqueConstraint("name", "machine_id", name="uq_container_name_machine"),
    )
