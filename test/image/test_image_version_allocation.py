"""创建请求尚未完成派发时，后续请求的配方和标签仍必须一一对应。"""

from datetime import datetime, timedelta

from ...repositories import machine_image_repo
from ...services import image_tasks
from ..factories import create_machine


def test_different_recipes_resolved_before_dispatch_have_distinct_tags(db_session):
    machine = create_machine()
    future = datetime.utcnow().replace(microsecond=0) + timedelta(seconds=30)
    machine_image_repo.record_dispatch(
        machine.id, 1, image_tasks.format_image_build_tag(1, future), future,
        recipe_fingerprint="unknown-previous-recipe", session=db_session,
    )
    db_session.commit()

    first = image_tasks.resolve_image_build(1, machine.id)
    image_tasks.Update_image(image_id=1, dockerfile_body="RUN echo second-pending-request")
    second = image_tasks.resolve_image_build(1, machine.id)
    repeated = image_tasks.resolve_image_build(1, machine.id)

    assert first.payload["dockerfile_text"] != second.payload["dockerfile_text"]
    assert first.payload["image_tag"] != second.payload["image_tag"]
    assert repeated.payload["image_tag"] == second.payload["image_tag"]
