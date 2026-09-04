import ast
from pathlib import Path

import pytest

from .conftest import TEST_CONFIG_OVERRIDES


ROOT = Path(__file__).resolve().parents[1]
OLD_TEST_FILES = [
    "test/test_api_web.py",
    "test/test_api_web_machine.py",
    "test/test_api_web_containers.py",
    "test/test_user_sql.py",
    "test/test_machine_sql.py",
    "test/test_container_sql.py",
]
INTEGRATION_TEST_FILES = [
    "test/test_mail.py",
]


def _module_has_pytestmark(path: Path, marker_name: str) -> bool:
    def _is_marker(node) -> bool:
        func = node.func if isinstance(node, ast.Call) else node
        return (
            isinstance(func, ast.Attribute)
            and func.attr == marker_name
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "mark"
        )

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
                value = node.value
                if _is_marker(value):
                    return True
                if isinstance(value, ast.List):
                    for item in value.elts:
                        if _is_marker(item):
                            return True
    return False


def test_pytest_markers_are_registered():
    text = (ROOT / "pytest.ini").read_text(encoding="utf-8")

    for marker in ("unit", "api", "db", "e2e", "integration", "legacy"):
        assert f"{marker}:" in text


def test_safe_test_config_disables_background_tasks():
    assert TEST_CONFIG_OVERRIDES["TESTING"] is True
    assert TEST_CONFIG_OVERRIDES["DISABLE_BACKGROUND_TASKS"] is True


def test_safe_test_config_uses_isolated_database():
    assert TEST_CONFIG_OVERRIDES["SQLALCHEMY_DATABASE_URI"].startswith("sqlite://")


def test_real_network_is_blocked_by_default():
    import requests

    with pytest.raises(AssertionError, match="Real HTTP requests are blocked"):
        requests.post("http://127.0.0.1")


def test_real_smtp_is_blocked_by_default():
    import smtplib

    with pytest.raises(AssertionError, match="Real SMTP"):
        smtplib.SMTP("localhost")


def test_docs_testing_mentions_safe_default_command():
    text = (ROOT / "docs/testing.md").read_text(encoding="utf-8")

    assert 'pytest -m "not integration and not legacy"' in text
    assert "SQLite" in text


def test_legacy_tests_are_removed():
    for relpath in OLD_TEST_FILES:
        path = ROOT / relpath
        assert not path.exists(), relpath


def test_default_safe_collection_excludes_legacy_tests():
    assert 'addopts = -m "not integration and not legacy"' in (ROOT / "pytest.ini").read_text(encoding="utf-8")


def test_integration_tests_are_not_selected_by_safe_command():
    for relpath in INTEGRATION_TEST_FILES:
        assert _module_has_pytestmark(ROOT / relpath, "integration")


def test_integration_tests_are_not_forced_through_safe_external_mocks():
    text = (ROOT / "test/conftest.py").read_text(encoding="utf-8")

    assert 'request.node.get_closest_marker("integration")' in text
    assert "Real SMTP_SSL is blocked in the safe pytest suite" in text


def test_legacy_migration_doc_lists_all_old_test_files():
    text = (ROOT / "docs/testing_legacy_migration.md").read_text(encoding="utf-8")

    for relpath in OLD_TEST_FILES:
        assert f"`{relpath}`" in text
        assert "deleted" in text
    for relpath in INTEGRATION_TEST_FILES:
        assert f"`{relpath}`" in text


def test_no_new_unmarked_legacy_style_tests():
    old_names = {Path(path).name for path in OLD_TEST_FILES}
    for path in (ROOT / "test").glob("test_*.py"):
        if path.name in old_names:
            continue
        assert not path.name.endswith("_sql.py")


def test_no_tests_import_requests_without_integration_marker():
    for path in (ROOT / "test").rglob("test_*.py"):
        if path.name == "test_testing_safety_contract.py":
            continue
        if _module_has_pytestmark(path, "integration"):
            continue
        text = path.read_text(encoding="utf-8")
        assert "import requests" not in text
        assert "from requests" not in text


def test_no_tests_call_create_app_without_testing_config():
    for path in (ROOT / "test").rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        if "create_app(" not in text:
            continue
        assert "overrides=" in text or path.name == "conftest.py"


def test_test_readme_documents_factory_and_mock_rules():
    text = (ROOT / "test/README.md").read_text(encoding="utf-8")

    assert "test/factories.py" in text
    assert "test/mocks.py" in text


def test_github_actions_uses_only_safe_services():
    text = (ROOT / ".github/workflows/ctrl-tests.yml").read_text(encoding="utf-8")

    assert 'DATABASE_URL: "sqlite:///:memory:"' in text
    assert 'python -m pytest -m "not integration and not legacy"' in text
    assert "mysql" not in text.lower()
    assert "docker" not in text.lower()
    assert "FLASK_CONFIG" not in text


def test_coverage_config_excludes_tests_and_sets_initial_threshold():
    text = (ROOT / ".coveragerc").read_text(encoding="utf-8")

    assert "test/*" in text
    assert "fail_under = 60" in text
