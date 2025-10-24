from ..extensions import db
from ..constant import *

# This is a test for commit and pr

class Container(db.Model):
    __tablename__ = "containers"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(120), nullable=False)
    image: str = db.Column(db.String(200), nullable=False)
    # 外键列：引用 machines.id
    machine_id: int = db.Column(
        db.Integer, db.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 关系：指向 Machine
    machine = db.relationship("Machine", back_populates="containers")

    container_status: ContainerStatus = db.Column(db.Enum(ContainerStatus), nullable=False, default=ContainerStatus.MAINTENANCE)
    
    port: int = db.Column(db.Integer, nullable=False, index=True)

    users = db.relationship(
        "User",
        secondary="user_containers",
        back_populates="containers",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Container {self.name} on machine={self.machine_id}>"

    __table_args__ = (
        db.UniqueConstraint("name", "machine_id", name="uq_container_name_machine"),
    )