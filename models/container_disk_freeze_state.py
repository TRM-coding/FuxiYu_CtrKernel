import datetime as dt

from ..extensions import db


class ContainerDiskFreezeState(db.Model):
    """磁盘超限冻结升级状态。

    记录存在 = 容器当前处于冻结升级倒计时。
    唯一退出：容量回落至 limit 的 95% 以下（不区分长期/短期）。
    """

    __tablename__ = "container_disk_freeze_state"

    container_id = db.Column(
        db.Integer,
        db.ForeignKey("containers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    first_frozen_at = db.Column(
        db.DateTime, nullable=False
    )
    grace_until = db.Column(
        db.DateTime, nullable=True
    )
    created_at = db.Column(
        db.DateTime, default=dt.datetime.utcnow, nullable=False
    )

    container = db.relationship("Container")
