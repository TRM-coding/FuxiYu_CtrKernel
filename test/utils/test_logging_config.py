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


def test_uvicorn_stderr_lines_keep_textual_level(caplog):
    stream = logging_config._UvicornStreamToLogger(logging.getLogger("stderr-test"), logging.ERROR)

    with caplog.at_level(logging.INFO, logger="stderr-test"):
        stream.write("INFO:     Started server process [1]\n")
        stream.write("ERROR:    bind failed\n")

    records = [(record.levelno, record.message) for record in caplog.records]
    assert (logging.INFO, "Started server process [1]") in records
    assert (logging.ERROR, "bind failed") in records
