"""独立会话交错写入时，旧读取不能覆盖已占用标签的配方。"""

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ...models.machine_image import MachineImage
from ...repositories import machine_image_repo


def test_stale_session_cannot_relabel_another_sessions_reserved_tag(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'cache-interleave.db').as_posix()}")
    try:
        MachineImage.__table__.create(engine)
        previous = datetime(2026, 10, 15)
        tag = "fuxi/image-1:20261015T000001Z"
        with Session(engine) as seed:
            machine_image_repo.record_dispatch(
                1, 1, "fuxi/image-1:20261015T000000Z", previous, "previous", session=seed,
            )
            seed.commit()
        with Session(engine) as first, Session(engine) as second:
            stale = machine_image_repo.get_by_machine_image(1, 1, session=second)
            machine_image_repo.record_dispatch(
                1, 1, tag, previous + timedelta(seconds=1), "winner", session=first,
            )
            first.commit()
            assert stale.recipe_fingerprint == "previous"
            machine_image_repo.record_dispatch(
                1, 1, tag, previous + timedelta(seconds=1), "late-request", session=second,
            )
            second.commit()
        with Session(engine) as check:
            persisted = machine_image_repo.get_by_machine_image(1, 1, session=check)
            assert persisted.recipe_fingerprint == "winner"
            assert persisted.image_tag == tag
    finally:
        engine.dispose()
