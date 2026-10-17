from datetime import datetime

from ..constant import ImageStatus, ImageValidRange
from ..extensions import db


class Image(db.Model):
    """镜像模板主表。

    镜像在 Ctrl 侧保存用户可维护的环境模板内容；最终 Dockerfile 由构建器
    在临时目录中生成，不回写 DB。
    """

    __tablename__ = "images"

    id: int = db.Column(db.Integer, primary_key=True)
    # 无唯一约束（2026-09 决策）：模板的移除是停用而非删除，停用行会继续占用名字，
    # 唯一约束会让该名字永久不可复用。唯一性由应用层在「未停用」的模板之间判定
    # （image_repo 的创建/改名路径）。containers 表为此废弃过 active_name 派生列，
    # 这里不再重蹈——镜像没有 Node 侧 docker daemon 那样的外部守卫，约束必须自己承担。
    name: str = db.Column(db.String(120), nullable=False, index=True)
    description: str | None = db.Column(db.String(500), nullable=True)
    base_image: str = db.Column(db.String(255), nullable=False)
    dockerfile_body: str = db.Column(db.Text, nullable=False, default="")
    # 容器启动命令（2026-09 决策）：建容器时容器里跑什么。
    #
    # 存的是**裸命令**，不是 Dockerfile 指令——与 base_image 存 `ubuntu:24.04` 而不存
    # `FROM ubuntu:24.04` 同一个道理。
    #
    # 可空且**空即默认**：留空表示"用平台默认"，即容器保持存活等你 SSH 进来
    # （`tail -f /dev/null`）。默认值只写在 Node 一处，不冻进数据——否则将来想改默认值
    # 就要写迁移，而且"空"的语义会糊（是用户没填，还是用户就想跑 tail？）。
    #
    # 它**不参与构建**：不进 tag、不进 Dockerfile、不影响"落后"判定。它是运行期参数，
    # 所以刻意不做成 DockerfileParts 的第四个字段。
    entrypoint: str | None = db.Column(db.String(255), nullable=True)
    # 可见范围：**唯一**决定可见性的字段（2026-09 决策）。此前"全员可见"是由
    # created_by_user_id IS NULL 派生的隐式规则，已退役——判定规则与 SQL 谓词都只有一处
    # （repositories/image_repo.py 的 image_is_visible_to / image_visibility_condition）。
    #
    # 默认 CUSTOM 而不是 PRIVATE：旧库里用户建的模板就是"创建者自带一行授权、别人看不见"，
    # CUSTOM 让新建模板与存量模板语义逐字一致；且非 CUSTOM 态下名单接口是拒绝的，
    # 默认 PRIVATE 会把"创建后加授权"变成两个动作。
    valid_range: ImageValidRange = db.Column(
        db.Enum(ImageValidRange, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=ImageValidRange.CUSTOM,
    )
    status: ImageStatus = db.Column(
        db.Enum(ImageStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=ImageStatus.DRAFT,
    )
    created_by_user_id: int | None = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: datetime = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    updated_at: datetime = db.Column(
        db.DateTime,
        default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )

    user_image_links = db.relationship(
        "UserImage",
        back_populates="image",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Image {self.name}>"
