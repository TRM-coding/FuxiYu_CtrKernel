# Ctrl Test Layout

Tests are grouped by behavioral surface:

- `user/`
- `machine/`
- `container/`
- `repository/`
- `utils/`
- `config/`
- `e2e/`

Default tests use SQLite and mocked external services. They are safe to run next to a live production process.

Use `test/factories.py` for ORM data and `test/mocks.py` for shared mock helpers. Avoid adding new tests directly to old root-level legacy files.
