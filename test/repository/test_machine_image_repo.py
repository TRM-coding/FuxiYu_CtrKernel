"""machine_image 仓储写入口的行为锁：就地更换、身份不变、版本不回退。

缓存行代表"这台机器上这份模板当前的制品版本"。配方变了就换值，但行 id 与
`(machine_id, image_id)` 复合键永不变——容器归属、授权关系与观测线索都不随换代改动。
"""

from datetime import datetime, timedelta

from ...repositories import machine_image_repo
from ..factories import create_machine


def test_record_dispatch_keeps_identity_and_row_count(db_session):
    """同一 (机器, 模板) 只有一行；重复写相同值不新增行、不改值。"""
    machine = create_machine()
    stamp = datetime(2026, 1, 1)
    first = machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000000Z", stamp, "fp1", session=db_session
    )
    db_session.commit()
    assert first.id is not None

    again = machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000000Z", stamp, "fp1", session=db_session
    )
    db_session.commit()

    assert again.id == first.id
    rows = machine_image_repo.list_by_machine(machine.id, session=db_session)
    assert len(rows) == 1
    assert rows[0].image_tag == "fuxi/image-1:20260101T000000Z"


def test_record_dispatch_replaces_values_in_place_for_newer_version(db_session):
    """更新的版本戳 → 就地更换同一行的标签/版本戳/指纹。"""
    machine = create_machine()
    first = machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000000Z", datetime(2026, 1, 1), "fp1",
        session=db_session,
    )
    db_session.commit()
    row_id = first.id

    newer = datetime(2026, 1, 1) + timedelta(seconds=1)
    replaced = machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000001Z", newer, "fp2", session=db_session
    )
    db_session.commit()

    assert replaced.id == row_id, "换代不换身份"
    assert replaced.image_tag == "fuxi/image-1:20260101T000001Z"
    assert replaced.created_at == newer
    assert replaced.recipe_fingerprint == "fp2"
    assert len(machine_image_repo.list_by_machine(machine.id, session=db_session)) == 1


def test_record_dispatch_never_moves_the_version_backwards(db_session):
    """并发交错：更旧的派发不该覆盖已更新的行——返回既有行即可。

    行只需代表"这台机器上最新的那一版"；回退会让下一次判旧的基准也跟着退，且会被
    误当成"当前那一版"而复用一个已被新版本取代的标签。
    """
    machine = create_machine()
    newer = datetime(2026, 1, 1, 0, 0, 5)
    machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000005Z", newer, "fp_new", session=db_session
    )
    db_session.commit()

    stale = machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000000Z", datetime(2026, 1, 1), "fp_old",
        session=db_session,
    )
    db_session.commit()

    assert stale.created_at == newer
    assert stale.image_tag == "fuxi/image-1:20260101T000005Z"
    assert stale.recipe_fingerprint == "fp_new"


def test_record_dispatch_refuses_to_relabel_the_same_tag(db_session):
    """同一个标签 MUST NOT 对应两个配方：同 tag 不同指纹的写入被拒绝，指纹保持原值。"""
    machine = create_machine()
    stamp = datetime(2026, 1, 1)
    machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000000Z", stamp, "fp1", session=db_session
    )
    db_session.commit()

    same = machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000000Z", stamp, "fp2", session=db_session
    )
    db_session.commit()

    assert same.recipe_fingerprint == "fp1", "同标签不得改配方"
    assert same.image_tag == "fuxi/image-1:20260101T000000Z"


def test_schema_upgrade_adds_recipe_fingerprint_column(db_session):
    """旧库的 machine_image 没有指纹列 → 启动自愈补列；存量行留 NULL，读侧判旧一次。"""
    from sqlalchemy import inspect, text

    from ... import _ensure_machine_image_schema
    from ...extensions import engine

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS machine_image"))
        conn.execute(text(
            "CREATE TABLE machine_image ("
            " id INTEGER PRIMARY KEY,"
            " machine_id INTEGER NOT NULL,"
            " image_id INTEGER NOT NULL,"
            " image_tag VARCHAR(200) NOT NULL,"
            " created_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO machine_image (machine_id, image_id, image_tag, created_at)"
            " VALUES (1, 1, 'fuxi/image-1:20260101T000000Z', '2026-01-01 00:00:00')"
        ))

    _ensure_machine_image_schema()

    assert "recipe_fingerprint" in {
        column["name"] for column in inspect(engine).get_columns("machine_image")
    }
    with engine.begin() as conn:
        stored = conn.execute(text("SELECT recipe_fingerprint FROM machine_image")).scalar()
    assert stored is None, "存量行不回填猜测指纹：读侧判旧一次即可安全收敛"


def test_composite_key_scopes_rows_per_machine_and_template(db_session):
    """检索按 `(machine_id, image_id)`：同机器不同模板、不同机器同模板互不串行。"""
    from ...services import image_tasks

    machine_a = create_machine()
    machine_b = create_machine()
    second_image_id = image_tasks.Create_image(name="tpl-two", base_image="ubuntu:22.04")

    machine_image_repo.record_dispatch(
        machine_a.id, 1, "fuxi/image-1:20260101T000000Z", datetime(2026, 1, 1), "fp1",
        session=db_session,
    )
    machine_image_repo.record_dispatch(
        machine_a.id, second_image_id, f"fuxi/image-{second_image_id}:20260101T000000Z",
        datetime(2026, 1, 1), "fp2", session=db_session,
    )
    machine_image_repo.record_dispatch(
        machine_b.id, 1, "fuxi/image-1:20260101T000000Z", datetime(2026, 1, 1), "fp1",
        session=db_session,
    )
    db_session.commit()

    assert len(machine_image_repo.list_by_machine(machine_a.id, session=db_session)) == 2
    assert len(machine_image_repo.list_by_machine(machine_b.id, session=db_session)) == 1
    assert machine_image_repo.get_by_machine_image(
        machine_a.id, second_image_id, session=db_session
    ).image_tag.startswith(f"fuxi/image-{second_image_id}:")
