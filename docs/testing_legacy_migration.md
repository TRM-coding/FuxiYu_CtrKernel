# Deleted Legacy Test Migration

Default safe pytest command:

```bash
pytest -m "not integration and not legacy"
```

Integration tests are deliberately excluded from the safe suite. Pre-migration
legacy tests have been deleted instead of retained as a second contract.

| Old Test File | Current Status | Replacement Coverage |
| --- | --- | --- |
| `test/test_api_web.py` | deleted | `test/user/test_user_api_auth.py`, `test/user/test_user_api_profile.py` |
| `test/test_user_sql.py` | deleted | `test/user/test_user_tasks_*.py`, `test/user/test_user_repository_integration.py` |
| `test/test_api_web_machine.py` | deleted | `test/machine/test_machine_api_*.py` |
| `test/test_machine_sql.py` | deleted | `test/machine/test_machine_tasks_*.py`, `test/machine/test_machine_repository_integration.py` |
| `test/test_api_web_containers.py` | deleted | `test/container/test_container_api_*.py` |
| `test/test_container_sql.py` | deleted | `test/container/test_container_tasks_*.py`, `test/container/test_container_cleanup_*.py` |
| `test/test_mail.py` | `integration` | `test/utils/test_mail.py` |

Rules:

- Old tests that can touch real Node, real SMTP, or a non-SQLite database must stay out of the safe suite.
- Pre-migration tests are not retained. Tests must follow the FastAPI and explicit
  SQLAlchemy session contract.
- New coverage should live in the categorized directories under `test/`.
