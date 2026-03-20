from ..extensions import db


class MachinePermission(db.Model):
    __tablename__ = "machine_permissions"

    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.Integer, db.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("machine_id", "user_id", name="uq_machine_permissions_machine_user"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MachinePermission machine_id={self.machine_id} user_id={self.user_id}>"
