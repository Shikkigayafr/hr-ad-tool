"""Чтение секретов: сначала файл (Docker secrets), потом обычная переменная окружения."""
import os

SECRETS_DIR = os.getenv("SECRETS_DIR", "/run/secrets")


def read_secret(name: str, default: str | None = None) -> str | None:
    """Порядок поиска для секрета NAME:
    1. переменная NAME_FILE — путь к файлу с секретом;
    2. файл /run/secrets/name (в нижнем регистре) — так Docker монтирует secrets;
    3. переменная окружения NAME (обычный .env);
    4. значение по умолчанию.
    """
    path = os.getenv(f"{name}_FILE") or os.path.join(SECRETS_DIR, name.lower())
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
        if value:
            return value
    return os.getenv(name) or default
