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
    # 冻结期内机器不可用的累计时长（"业务正常时间"之外的时长不计入冻结天数）。
    # 窗口关闭时累加，读侧用 now - first_frozen_at - deferral 得有效冻结天数。
    # 随记录生灭：容量回落重置会删除整行，故不需要单独清零。
    deferral_seconds = db.Column(db.Integer, nullable=True, default=0, server_default=db.text("0"))

    container = db.relationship("Container")
