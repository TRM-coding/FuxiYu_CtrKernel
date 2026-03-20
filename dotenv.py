from __future__ import annotations

from pathlib import Path
import os


def _parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_dotenv(dotenv_path: str | None = None, *args, **kwargs) -> bool:
    path = Path(dotenv_path or ".env")
    loaded = False
    for key, value in _parse(path).items():
        os.environ.setdefault(key, value)
        loaded = True
    return loaded


def find_dotenv(*args, **kwargs) -> str:
    filename = kwargs.get("filename", ".env")
    path = Path(filename)
    return str(path if path.exists() else filename)


def dotenv_values(dotenv_path=None, *args, **kwargs):
    path = Path(dotenv_path or ".env")
    return _parse(path)
