"""预留被另一份配方占用时，解析器不得把冲突标签交给调用方。"""

from datetime import datetime, timedelta

from ...repositories import machine_image_repo
from ...services import image_tasks
from ..factories import create_machine


def test_conflicting_reservation_does_not_return_other_recipe_tag(db_session, monkeypatch):
    machine = create_machine()
    previous = datetime.utcnow().replace(microsecond=0) + timedelta(seconds=30)
    machine_image_repo.record_dispatch(
        machine.id, 1, image_tasks.format_image_build_tag(1, previous), previous,
        recipe_fingerprint="previous-recipe", session=db_session,
    )
    db_session.commit()
    original = machine_image_repo.record_dispatch
    claimed = []

    def write_with_competing_reservation(machine_id, image_id, tag, version, fingerprint=None, *, session):
        if not claimed:
            claimed.append(tag)
            original(machine_id, image_id, tag, version, "competing-recipe", session=session)
        return original(machine_id, image_id, tag, version, fingerprint, session=session)

    monkeypatch.setattr(machine_image_repo, "record_dispatch", write_with_competing_reservation)
    try:
        build = image_tasks.resolve_image_build(1, machine.id)
    except RuntimeError:
        return  # 无法安全预留时拒绝请求也是安全结果。
    assert claimed and build.payload["image_tag"] != claimed[0]
