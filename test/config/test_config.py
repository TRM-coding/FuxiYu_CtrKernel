import importlib


def test_config_reads_cleanup_and_long_term_defaults(monkeypatch):
    monkeypatch.delenv("CONTAINER_CLEANUP_AFTER_DAYS", raising=False)
    monkeypatch.delenv("CONTAINER_CLEANUP_REMINDER_HOURS", raising=False)
    monkeypatch.delenv("LONG_TERM_CONTAINER_LIMIT", raising=False)
    from ... import config

    importlib.reload(config)

    assert config.AppConfig.CONTAINER_CLEANUP_AFTER_DAYS == 7
    assert config.AppConfig.CONTAINER_CLEANUP_REMINDER_HOURS == "72,24,12"
    assert config.AppConfig.LONG_TERM_CONTAINER_LIMIT == 1


def test_config_reads_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("CONTAINER_CLEANUP_AFTER_DAYS", "9")
    monkeypatch.setenv("CONTAINER_CLEANUP_REMINDER_HOURS", "48,6")
    monkeypatch.setenv("LONG_TERM_CONTAINER_LIMIT", "3")
    from ... import config

    importlib.reload(config)

    assert config.AppConfig.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"
    assert config.AppConfig.CONTAINER_CLEANUP_AFTER_DAYS == 9
    assert config.AppConfig.CONTAINER_CLEANUP_REMINDER_HOURS == "48,6"
    assert config.AppConfig.LONG_TERM_CONTAINER_LIMIT == 3
