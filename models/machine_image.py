from datetime import datetime

from ..extensions import db


class MachineImage(db.Model):
    """Ctrl 向某台机器派发过的镜像构建记录（2026-09 决策）。

    **语义是「Ctrl 请求过」，不是「制品确实建成过」。** 写入时机是构建请求被派发之时，
    因此构建失败也会留下记录——这是刻意的：它回答的是 Ctrl 的派发历史，不是宿主机的
    镜像清单。宿主机上的制品被外部清理（prune 等）时，本表不会、也无法自动更正。

    **它不在执行链上。** 只用于观测，MUST NOT 参与任何执行决策——尤其不能因为"记录
    已存在"而跳过下发构建段。构建是否真正需要执行由 Node 在本机判定（先查
    `images.get(tag)`，命中即返回，未命中则依 Dockerfile 构建），那条回退链路保证
    任何"未命中"都能自愈。拿本表做决策会让它的假阳性从"显示不准"升级为"容器起不来"。

    按 `(machine_id, image_tag)` 组织且**不设删除逻辑**：模板更新会让标签本身变化，
    从而自然产生新行，旧行作为派发历史保留。写删除路径只会引入一条容易被遗忘的
    维护入口，并销毁审计线索。
    """

    __tablename__ = "machine_image"

    id: int = db.Column(db.Integer, primary_key=True)
    machine_id: int = db.Column(
        db.Integer, db.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_tag: str = db.Column(db.String(200), nullable=False)
    created_at: datetime = db.Column(db.DateTime, default=db.func.now(), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("machine_id", "image_tag", name="uq_machine_image_tag"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MachineImage machine={self.machine_id} tag={self.image_tag}>"
