from datetime import datetime
from ..extensions import db
from ..constant import *

class Machine(db.Model):
    __tablename__ = "machines"

    id: int = db.Column(db.Integer, primary_key=True)
    machine_name: str = db.Column(db.String(120), unique=True, nullable=False, index=True)
    machine_ip: str = db.Column(db.String(120), unique=True, nullable=False, index=True)
    machine_type: MachineTypes = db.Column(db.Enum(MachineTypes), nullable=False)
    machine_status: MachineStatus = db.Column(
    db.Enum(MachineStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=MachineStatus.ONLINE
    )
    is_maintenance: bool = db.Column(db.Boolean, nullable=False, default=False)
    cpu_core_number: int = db.Column(db.Integer, nullable=True)
    memory_size_gb: int = db.Column(db.Integer, nullable=True)
    gpu_number: int = db.Column(db.Integer, nullable=True)
    gpu_type: str = db.Column(db.String(120), nullable=True)
    # ── GPU 三集合建模（2026-08-30 决策，见 FuxiYu_Global 速查 · 决策备忘） ──
    # gpu_list：事实——smi 当前枚举的物理卡集合（sys_snapshot 自动更新）
    # gpu_allow_list：许可——管理员允许分配的卡集合（人工维护；空 = 未配置）
    gpu_list: list | None = db.Column(db.JSON, nullable=True)
    gpu_allow_list: list | None = db.Column(db.JSON, nullable=True)
    max_shared_gb: int = db.Column(db.Integer, nullable=True)
    disk_size_gb: int = db.Column(db.Integer, nullable=True)
    machine_description: str = db.Column(db.String(500), nullable=True)
    max_memory_gb: int = db.Column(db.Integer, nullable=True)
    max_gpu_number: int = db.Column(db.Integer, nullable=True)
    max_cpu_core_number: int = db.Column(db.Integer, nullable=True)
    # 磁盘上限（2026-08 语义收敛）：max_disk_size_gb = 容器磁盘可用上限（管理员维护，
    # 冻结/容器展示「已用/上限」用它）；disk_size_gb = 显示用（Node 采集 bind_mount 分区容量）。
    max_disk_size_gb: int = db.Column(db.Integer, nullable=True)
    # ── TOFU 接入凭据（TLS 方案，2026-08） ──
    # uid：Ctrl 首连颁发的高熵 UID（应用层标识，可独立吊销轮换）
    # node_cert_fingerprint：Node 自签证书 SHA-256 指纹（传输层凭证，Ctrl 从 TLS 层计算）
    # 双凭据均唯一；未接入（未首连）时为 None
    node_uid: str | None = db.Column(db.String(128), unique=True, nullable=True, index=True)
    node_cert_fingerprint: str | None = db.Column(db.String(128), unique=True, nullable=True, index=True)
    cert_pinned_at: datetime | None = db.Column(db.DateTime, nullable=True)
    # ── 采集异常轴（数据通路对账契约 C1，2026-08） ──
    # Node 采集异常（docker 卡死）时由 collect_error 帧置位、正常快照清除。
    # 机器轴条件：DB 容器状态保持最后已知值，展示派生 status_unknown——不写容器诊断。
    collect_error_at: datetime | None = db.Column(db.DateTime, nullable=True)
    # 与 Container 的一对多关系（containers 表里有 machine_id 外键）
    containers = db.relationship(
        "Container", back_populates="machine", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Machine {self.machine_name} ({self.machine_type.value})>"
