import datetime as dt

from ..extensions import db

# reminder_key 在"本周期尚未提醒"时的取值。
# 复位（真登录 = 新周期）把档位打回它，而不是删行——行的存在即状态。
NEVER_REMINDED = "NEVER"


class ContainerCleanupReminder(db.Model):
    __tablename__ = "container_cleanup_reminders"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    container_id = db.Column(db.Integer, nullable=False, index=True)
    # 状态位，不是"某次发送的记录"：该 (容器, 收件人) 已提醒到的**最深档位**。
    # 取值 NEVER_REMINDED 或 "72h"/"24h"/"12h"（跟随 container.cleanup_reminder_hours）。
    # 档位随时间单调加深（NEVER → 72h → 24h → 12h），所以"存的是不是正好这一级"
    # 就足以判定该不该发——不需要任何会随顺延漂移的量参与比较。
    reminder_key = db.Column(db.String(32), nullable=False)
    # 仅作审计：最近一次发信时报出的到期时刻。已退出身份判定（见 repositories 注释）。
    cleanup_at = db.Column(db.DateTime, nullable=False)
    recipient_email = db.Column(db.String(120), nullable=False)
    sent_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)

    __table_args__ = (
        # 一行一状态：每个收件人在每个容器上只有一条记录
        db.UniqueConstraint(
            "container_id",
            "recipient_email",
            name="uq_container_cleanup_reminder_once",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ContainerCleanupReminder container_id={self.container_id} "
            f"key={self.reminder_key} recipient={self.recipient_email}>"
        )
