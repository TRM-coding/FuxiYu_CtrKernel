import importlib


def test_config_reads_deployment_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CTRL_PORT", raising=False)
    monkeypatch.delenv("WEB_PORT", raising=False)
    monkeypatch.delenv("NODE_PORT", raising=False)
    monkeypatch.delenv("ENABLE_SSL", raising=False)
    monkeypatch.delenv("SSL_CERT_PATH", raising=False)
    monkeypatch.delenv("SSL_KEY_PATH", raising=False)
    from ... import config

    importlib.reload(config)

    assert config.NetConfig.CTRL_PORT == 5000
    assert config.NetConfig.WEB_PORT == 5173
    assert config.CommsConfig.NODE_PORT == 5789
    assert config.AppConfig.SSL_ENABLED is True
    assert config.AppConfig.SSL_CERT_PATH == "certs/ctrl.pem"
    assert config.AppConfig.SSL_KEY_PATH == "certs/ctrl-key.pem"


def test_config_reads_deployment_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("CTRL_PORT", "5100")
    monkeypatch.setenv("WEB_PORT", "5273")
    monkeypatch.setenv("NODE_PORT", "6789")
    monkeypatch.setenv("ENABLE_SSL", "false")
    monkeypatch.setenv("SSL_CERT_PATH", "certs/custom-ctrl.pem")
    monkeypatch.setenv("SSL_KEY_PATH", "certs/custom-ctrl-key.pem")
    from ... import config

    importlib.reload(config)

    assert config.AppConfig.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"
    assert config.NetConfig.CTRL_PORT == 5100
    assert config.NetConfig.WEB_PORT == 5273
    assert config.CommsConfig.NODE_PORT == 6789
    assert config.CommsConfig.NODE_URL_MIDDLE == ":6789/api"
    assert config.AppConfig.SSL_ENABLED is False
    assert config.AppConfig.SSL_CERT_PATH == "certs/custom-ctrl.pem"
    assert config.AppConfig.SSL_KEY_PATH == "certs/custom-ctrl-key.pem"
