"""旧缓存表升级不推测历史配方，不改写关联身份和已有版本。"""

from sqlalchemy import create_engine, inspect, text

from ... import _ensure_machine_image_schema, extensions


def test_old_cache_schema_adds_nullable_fingerprint_idempotently(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old-cache.db').as_posix()}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE images (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO images VALUES (3)"))
            conn.execute(text("""
                CREATE TABLE machine_image (
                    id INTEGER PRIMARY KEY, machine_id INTEGER NOT NULL,
                    image_id INTEGER NOT NULL, image_tag VARCHAR(200) NOT NULL,
                    created_at DATETIME NOT NULL
                )
            """))
            conn.execute(text("""
                INSERT INTO machine_image VALUES
                (17, 5, 3, 'fuxi/image-3:20261010T000000Z', '2026-10-10 00:00:00')
            """))
        monkeypatch.setattr(extensions, "engine", engine)
        _ensure_machine_image_schema()
        _ensure_machine_image_schema()
        columns = {column["name"]: column for column in inspect(engine).get_columns("machine_image")}
        assert columns["recipe_fingerprint"]["nullable"] is True
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM machine_image")).mappings().one()
            assert (row["id"], row["machine_id"], row["image_id"]) == (17, 5, 3)
            assert row["image_tag"] == "fuxi/image-3:20261010T000000Z"
            assert row["created_at"] == "2026-10-10 00:00:00"
            assert row["recipe_fingerprint"] is None
    finally:
        engine.dispose()
