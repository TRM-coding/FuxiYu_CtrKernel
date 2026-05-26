import datetime as dt

from ..extensions import db


class ContainerCleanupReminder(db.Model):
    __tablename__ = "container_cleanup_reminders"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    container_id = db.Column(db.Integer, nullable=False, index=True)
    reminder_key = db.Column(db.String(32), nullable=False)
    cleanup_at = db.Column(db.DateTime, nullable=False)
    recipient_email = db.Column(db.String(120), nullable=False)
    sent_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "container_id",
            "reminder_key",
            "cleanup_at",
            "recipient_email",
            name="uq_container_cleanup_reminder_once",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ContainerCleanupReminder container_id={self.container_id} "
            f"key={self.reminder_key} recipient={self.recipient_email}>"
        )
