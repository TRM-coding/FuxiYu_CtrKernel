"""Q33：entrypoint 的四处说明必须与构建实现一致。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_entrypoint_docs_describe_build_stage_at_all_four_locations():
    image = _read("models/image.py")
    containers = _read("models/containers.py")
    schema = _read("schemas/image.py")
    creation = _read("services/container_module/creation.py")
    docs = (image, containers, schema, creation)

    for text in docs:
        for legacy in ("不参与构建", "不进 Dockerfile", "默认值只写在 Node", "utils/Container.py"):
            assert legacy not in text

    assert "参与构建" in image
    assert "DockerfileParts" in image
    assert "PLATFORM_DEFAULT_ENTRYPOINT" in image

    assert "参与构建" in containers
    assert "ENTRYPOINT" in containers

    assert "render_final_dockerfile" in schema
    assert "ENTRYPOINT" in schema

    assert "ENTRYPOINT" in creation
    assert "模板侧的三项" in creation
