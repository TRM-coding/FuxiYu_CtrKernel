# Ctrl Testing Guide

## Safety Boundary

The default Ctrl test suite is designed to run while the production service is still running.

Default tests must not touch:

- production or development databases
- real Node services
- real Docker
- real SMTP services
- background schedulers
- private intranet resources

The pytest fixtures inject a SQLite-only app configuration through `create_app(overrides=...)`.
Do not use `FLASK_CONFIG=testing` or any runtime testing mode to start the application.

## Default Command

Run the safe suite:

```bash
pytest -m "not integration and not legacy"
```

This is also the default configured in `pytest.ini`.

With coverage:

```bash
pytest -m "not integration and not legacy" \
  --cov --cov-report=term-missing --cov-report=xml --cov-report=html \
  --junitxml=reports/pytest.xml
```

## Focused Runs

```bash
pytest test/user
pytest test/machine
pytest test/container
pytest test/repository test/utils test/config
```

Marker-focused runs:

```bash
pytest -m unit
pytest -m api
pytest -m db
pytest -m e2e
```

## Integration Tests

Integration tests are excluded from the default suite. They may require real external services.

Run them only when the required environment is intentionally prepared:

```bash
pytest -m integration
```

Legacy tests are also excluded from default runs:

```bash
pytest -m legacy
```

## Factory And Mock Rules

- Create database data through `test/factories.py`.
- Mock external services at the module import location actually used by the code under test.
- Task tests assert return values, exception reasons, and local database state.
- API tests assert HTTP status, payload, and service-layer calls.
- Repository tests assert final SQLite database state.
- New safe tests should not import or call real `requests.post`, `smtplib.SMTP`, or scheduler startup paths.
