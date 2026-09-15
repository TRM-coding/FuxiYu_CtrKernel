import datetime as dt
from ..extensions import db


class ContainerSSHLogin(db.Model):
    __tablename__ = "container_ssh_login_records"

    # 复合主键：宿主机 + 容器，满足“宿主机id-容器id”维度唯一
    machine_id = db.Column(
        db.Integer,
        db.ForeignKey("machines.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    container_id = db.Column(
        db.Integer,
        db.ForeignKey("containers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    # 节点返回的上次 SSH 登录时间原样存储；无记录时允许为空
    last_ssh_login_time = db.Column(db.String(255), nullable=True)
    # 累计顺延秒数（机器不可用窗口补偿，Ctrl 自有列、不被 Node 帧覆盖）：
    # 窗口关闭时批量 += 故障时长；真登录（last_ssh_login_time 值变化）时清零。
    deferral_seconds = db.Column(db.Integer, nullable=True, default=0)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=dt.datetime.utcnow,
        onupdate=dt.datetime.utcnow,
    )

    machine = db.relationship("Machine")
    container = db.relationship("Container")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ContainerSSHLogin machine_id={self.machine_id} "
            f"container_id={self.container_id} last={self.last_ssh_login_time}>"
        )

