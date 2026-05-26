import datetime as dt

from ..extensions import db


class LongTermContainer(db.Model):
    __tablename__ = "long_term_containers"

    container_id = db.Column(
        db.Integer,
        db.ForeignKey("containers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    created_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)

    container = db.relationship("Container")
    created_by_user = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LongTermContainer container_id={self.container_id}>"
