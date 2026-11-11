import contextlib
import importlib
import importlib.util
import io
import os
import shutil
import smtplib
import subprocess
import sys
from pathlib import Path

import pytest

from .. import create_app
from ..utils import mail
from .conftest import TEST_CONFIG_OVERRIDES, _assert_sqlite_database_uri


ROOT = Path(__file__).resolve().parents[1]
GITHOOKS = ROOT / "githooks"


def _git_bash():
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
            if candidate.exists():
                return str(candidate)
    bash = shutil.which("bash")
    assert bash, "bash is required to exercise the repository hooks"
    return bash


def _git(repo, *args, input_text=None):
    git = shutil.which("git")
    assert git, "git is required to exercise the repository hooks"
    return subprocess.run(
        [git, *args],
        cwd=str(repo),
        input=input_text,
        text=True,
        capture_output=True,
        encoding="utf-8",
    )


def _init_repo(path):
    path.mkdir(parents=True)
    completed = _git(path, "init", "-q")
    assert completed.returncode == 0, completed.stderr
    return path


def _run_hook(repo, hook, *args):
    return subprocess.run(
        [_git_bash(), str(GITHOOKS / hook), *args],
        cwd=str(repo),
        text=True,
        capture_output=True,
        encoding="utf-8",
    )


def _write_message(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _stage_added(repo, relpath, content):
    blob = _git(repo, "hash-object", "-w", "--stdin", input_text=content)
    assert blob.returncode == 0, blob.stderr
    sha = blob.stdout.strip()
    completed = _git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"100644,{sha},{relpath}",
    )
    assert completed.returncode == 0, completed.stderr


def _write_probe(path, marker=None):
    lines = ["import pytest", ""]
    if marker:
        lines.append(f"pytestmark = pytest.mark.{marker}")
    lines.extend(["", "def test_probe():", "    assert True", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _minimal_probe_env(tmp_path):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONPATH": str(tmp_path),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.name == "nt" and os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def _write_socket_guard(tmp_path):
    (tmp_path / "sitecustomize.py").write_text(
        "\n".join(
            [
                "import socket",
                "",
                "class _BlockedSocket(socket.socket):",
                "    def connect(self, *args, **kwargs):",
                "        raise AssertionError('socket outbound blocked by anvil safety probe')",
                "",
                "    def connect_ex(self, *args, **kwargs):",
                "        raise AssertionError('socket outbound blocked by anvil safety probe')",
                "",
                "socket.socket = _BlockedSocket",
                "",
                "def _blocked(*args, **kwargs):",
                "    raise AssertionError('socket outbound blocked by anvil safety probe')",
                "",
                "socket.create_connection = _blocked",
                "socket.getaddrinfo = _blocked",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_collect(tmp_path, probe):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-c",
            str(ROOT / "pytest.ini"),
            str(probe),
        ],
        cwd=str(tmp_path),
        env=_minimal_probe_env(tmp_path),
        text=True,
        capture_output=True,
        encoding="utf-8",
    )


@pytest.mark.parametrize("keyword", ["NEW", "AMEND", "FIX", "SPEC", "TEST"])
def test_commit_msg_accepts_only_well_formed_item_lines(tmp_path, keyword):
    repo = _init_repo(tmp_path / "repo")
    single = _write_message(tmp_path, "single.txt", f"- {keyword} 提交分类说明\n")
    completed = _run_hook(repo, "commit-msg", str(single))
    assert completed.returncode == 0, completed.stderr
    valid = _write_message(
        tmp_path,
        "valid.txt",
        "- NEW 新增测试映射\n\n# 注释行应被跳过\n- FIX 修复测试映射\n",
    )

    completed = _run_hook(repo, "commit-msg", str(valid))
    assert completed.returncode == 0, completed.stderr

    cases = [
        ("-NEW 连字符后缺空格\n", "第 1 行不符合条目格式"),
        ("- ADD 自造关键字\n", "第 1 行不符合条目格式"),
        ("- spec 关键字必须大写\n", "第 1 行不符合条目格式"),
        ("- TEST\n", "第 1 行不符合条目格式"),
        ("\n# 只有注释\n", "至少需要一条实际变更"),
    ]
    for index, (message, expected) in enumerate(cases):
        path = _write_message(tmp_path, f"invalid_{index}.txt", message)
        completed = _run_hook(repo, "commit-msg", str(path))
        assert completed.returncode != 0, message
        assert expected in completed.stderr


def test_commit_msg_merge_head_bypasses_item_format(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    message = _write_message(tmp_path, "merge.txt", "Merge branch 'feature'\n")
    merge_head = repo / ".git" / "MERGE_HEAD"
    merge_head.write_text("0" * 40 + "\n", encoding="utf-8")

    completed = _run_hook(repo, "commit-msg", str(message))
    assert completed.returncode == 0, completed.stderr

    merge_head.unlink()
    completed = _run_hook(repo, "commit-msg", str(message))
    assert completed.returncode != 0
    assert completed.stderr


def _write_self_signed_pin(path):
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "10.0.0.7")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def test_commit_msg_rejects_attribution_trailers_and_lists_hits(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    cases = [
        ("coauthored.txt", "Co-authored-by: Bot <bot@example.com>", "Co-authored-by:"),
        ("generated.txt", "Generated with an assistant", "Generated with"),
        ("bot.txt", "🤖 generated", "🤖"),
    ]
    for index, (name, trailer, expected) in enumerate(cases):
        message = _write_message(
            tmp_path,
            name,
            f"- FIX 修复映射\n{trailer}\n",
        )
        completed = _run_hook(repo, "commit-msg", str(message))
        assert completed.returncode != 0, trailer
        assert "提交信息不得包含署名尾注或生成标记" in completed.stderr
        assert expected in completed.stderr


def test_pre_commit_rejects_double_prefix_capability(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    relpath = "openspec/specs/backend--standard--xxx/spec.md"
    _stage_added(repo, relpath, "# Spec\n")

    completed = _run_hook(repo, "pre-commit")
    assert completed.returncode != 0
    assert "capability 不得叠加门类前缀" in completed.stderr
    assert relpath in completed.stderr


def test_pre_commit_rejects_capability_without_prefix(tmp_path):
    rejected = _init_repo(tmp_path / "rejected")
    _stage_added(rejected, "openspec/specs/calendar/spec.md", "# Spec\n")
    completed = _run_hook(rejected, "pre-commit")
    assert completed.returncode != 0
    assert "capability 名缺少门类前缀" in completed.stderr
    assert "standard--" in completed.stderr

    accepted = _init_repo(tmp_path / "accepted")
    _stage_added(accepted, "openspec/specs/backend--calendar/spec.md", "# Spec\n")
    completed = _run_hook(accepted, "pre-commit")
    assert completed.returncode == 0, completed.stderr


def test_default_suite_deselects_integration_and_legacy_probes(tmp_path):
    _write_socket_guard(tmp_path)
    integration_probe = tmp_path / "test_integration_probe.py"
    legacy_probe = tmp_path / "test_legacy_probe.py"
    plain_probe = tmp_path / "test_plain_probe.py"
    _write_probe(integration_probe, "integration")
    _write_probe(legacy_probe, "legacy")
    _write_probe(plain_probe)

    for probe in (integration_probe, legacy_probe):
        completed = _run_collect(tmp_path, probe)
        assert completed.returncode == 5, (completed.stdout, completed.stderr)
        assert "test_probe" not in completed.stdout

    completed = _run_collect(tmp_path, plain_probe)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "test_probe" in completed.stdout


def test_safe_config_uses_exact_in_memory_sqlite(app):
    assert TEST_CONFIG_OVERRIDES["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"
    assert app.state.config.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"


def test_create_app_overrides_clear_mysql_engine_options_and_ignore_flask_config(monkeypatch):
    monkeypatch.setenv("FLASK_CONFIG", "tests.does.not.exist")
    created = create_app(overrides=TEST_CONFIG_OVERRIDES)

    assert created.state.config.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"
    assert created.state.config.SQLALCHEMY_ENGINE_OPTIONS == {}
    assert created.state.config.TESTING is True
    assert created.state.config.DISABLE_BACKGROUND_TASKS is True


def test_assert_sqlite_database_uri_rejects_non_sqlite():
    class _FakeApp:
        config = {
            "SQLALCHEMY_DATABASE_URI": "mysql+pymysql://user:secret@localhost/db",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
        }

    with pytest.raises(RuntimeError) as raised:
        _assert_sqlite_database_uri(_FakeApp())
    assert "Refusing to run tests against non-SQLite database URI" in str(raised.value)
    assert "mysql+pymysql://user:secret@localhost/db" in str(raised.value)

    class _SQLiteApp:
        config = {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
        }

    _assert_sqlite_database_uri(_SQLiteApp())


def test_pinned_adapter_http_path_is_blocked_before_network(tmp_path):
    from ..services.container_module.node_comms_modules import transport

    pin = tmp_path / "10.0.0.7.pem"
    _write_self_signed_pin(pin)

    with pytest.raises(AssertionError, match="Real HTTP requests are blocked"):
        transport._post_node_json(
            "https://10.0.0.7:5789/api/x",
            {},
            1.0,
            None,
            str(pin),
        )


def test_real_smtp_ssl_is_blocked_by_default():
    with pytest.raises(AssertionError, match="Real SMTP_SSL"):
        smtplib.SMTP_SSL("localhost")


def test_mail_send_uses_local_success_stub_without_smtp(db_session):
    result = mail.send("to@example.test", "subject", "body")

    assert result["ok"] is True
    assert result["mode"] == "pytest-mock"
    assert result["to"] == ["to@example.test"]


def test_mail_send_batch_uses_local_success_stub_without_smtp(db_session):
    messages = [
        {"to": "first@example.test", "subject": "subject", "content": "body"},
        {"to": "second@example.test", "subject": "subject", "content": "body"},
    ]

    results = mail.send_batch(messages)

    assert len(results) == 2
    assert [result["ok"] for result in results] == [True, True]
    assert [result["mode"] for result in results] == ["pytest-mock", "pytest-mock"]
    assert results[0]["to"] == ["first@example.test"]
    assert results[1]["to"] == ["second@example.test"]


@pytest.mark.integration
def test_integration_marker_bypasses_external_stubs():
    requests = importlib.import_module("requests")

    assert requests.Session.request is requests.sessions.Session.request
    assert isinstance(smtplib.SMTP, type)
    assert smtplib.SMTP.__module__ == "smtplib"


def test_ensure_auth_users_builds_rows_on_test_sqlite(ensure_auth_users, db_session):
    from ..models.user import User

    assert db_session.get(User, 1).username == "auth_user_1"
    assert db_session.get(User, 7).username == "auth_user_7"
    assert str(db_session.get_bind().url).startswith("sqlite://")


def test_legacy_replacement_paths_exist():
    patterns = [
        "test/user/test_user_api_auth.py",
        "test/user/test_user_api_profile.py",
        "test/user/test_user_tasks_*.py",
        "test/user/test_user_repository_integration.py",
        "test/machine/test_machine_api_*.py",
        "test/machine/test_machine_tasks_*.py",
        "test/machine/test_machine_repository_integration.py",
        "test/container/test_container_api_*.py",
        "test/container/test_container_tasks_*.py",
        "test/container/test_container_cleanup_*.py",
        "test/utils/test_mail.py",
    ]

    for pattern in patterns:
        matches = sorted(ROOT.glob(pattern))
        assert matches, pattern
        assert any("def test_" in path.read_text(encoding="utf-8") for path in matches), pattern


def test_retired_testing_docs_are_not_restored():
    for relpath in (
        "docs/testing.md",
        "docs/testing_legacy_migration.md",
        "test/README.md",
    ):
        assert not (ROOT / relpath).exists(), relpath
    assert (ROOT / "openspec/specs/procedure--testing-safety/spec.md").exists()


def test_check_pr_does_not_execute_body_sentinel(tmp_path):
    from importlib.util import module_from_spec, spec_from_file_location

    sentinel = tmp_path / "check_pr_sentinel.txt"
    payload = f'__import__("pathlib").Path({str(sentinel)!r}).write_text("pwned")'
    body = (
        "### 新增内容 | WHAT'S NEW\n"
        f"- 新增内容，payload: `{payload}`\n"
    )
    body_path = tmp_path / "body.md"
    body_path.write_text(body, encoding="utf-8")

    spec = spec_from_file_location("check_pr_anvil_probe", ROOT / "scripts/ci/check_pr.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = module.main(["--body-file", str(body_path)])

    assert code == 0
    assert "通过" in output.getvalue()
    assert not sentinel.exists()
