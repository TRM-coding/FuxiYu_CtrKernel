import logging

from ...utils import logging_config


def test_logging_config_does_not_duplicate_handlers(monkeypatch, tmp_path, app):
    monkeypatch.setenv("CTRL_LOG_DIR", str(tmp_path))
    logging_config._CONFIGURED = False
    before = len(logging.getLogger().handlers)

    logging_config.configure_daily_logging(app)
    first = len(logging.getLogger().handlers)
    logging_config.configure_daily_logging(app)
    second = len(logging.getLogger().handlers)

    assert first == before + 1
    assert second == first
    assert app._daily_logging_configured is True
