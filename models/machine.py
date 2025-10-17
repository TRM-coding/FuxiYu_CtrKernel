from ..extensions import db
from ..constant import *


class Machine(db.Model):
    __tablename__ = "machines"

    id: int = db.Column(db.Integer, primary_key=True)
    machine_name: str = db.Column(db.String(120), unique=True, nullable=False, index=True)
    machine_ip: str = db.Column(db.String(120), unique=True, nullable=False, index=True)
    machine_type: MachineTypes = db.Column(db.Enum(MachineTypes), nullable=False)
    machine_status: MachineStatus = db.Column(db.Enum(MachineStatus), nullable=False, default=MachineStatus.MAINTENANCE)
    cpu_core_number: int = db.Column(db.Integer, nullable=True)
    memory_size_gb: int = db.Column(db.Integer, nullable=True)
    gpu_number: int = db.Column(db.Integer, nullable=True)
    gpu_type: str = db.Column(db.String(120), nullable=True)
    disk_size_gb: int = db.Column(db.Integer, nullable=True)
    machine_description: str = db.Column(db.String(500), nullable=True)
    # 与 Container 的一对多关系（containers 表里有 machine_id 外键）
    containers = db.relationship(
        "Container", back_populates="machine", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Machine {self.machine_name} ({self.machine_type.value})>"
