"""Создаёт папку secrets/ с файлами для Docker secrets.

    python scripts/init_secrets.py

Случайные значения генерируются для secret_key и postgres_password.
ad_password и saby_password остаются пустыми — впишите туда пароли руками (одна строка, без кавычек).
Существующие файлы не перезаписываются (флаг --force перезапишет сгенерированные).
Пустой файл безопасен: приложение тогда возьмёт значение из .env или значение по умолчанию.
"""
import argparse
import os
import secrets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS_DIR = os.path.join(ROOT, "secrets")

GENERATED = {
    "secret_key": lambda: secrets.token_hex(32),
    "postgres_password": lambda: secrets.token_urlsafe(24),
}
MANUAL = ["ad_password", "saby_password"]


def write(name: str, value: str, force: bool) -> str:
    path = os.path.join(SECRETS_DIR, f"{name}.txt")
    if os.path.exists(path) and not force:
        return "уже есть, пропущен"
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(value)
    try:
        os.chmod(path, 0o600)  # на Windows игнорируется
    except OSError:
        pass
    return "создан"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="перезаписать сгенерированные секреты")
    args = parser.parse_args()

    os.makedirs(SECRETS_DIR, exist_ok=True)
    for name, make in GENERATED.items():
        print(f"secrets/{name}.txt: {write(name, make(), args.force)}")
    for name in MANUAL:
        # пустые файлы не перезаписываем даже с --force: там могут лежать ваши пароли
        print(f"secrets/{name}.txt: {write(name, '', force=False)}")

    print("\nГотово. Впишите пароли в secrets/ad_password.txt и secrets/saby_password.txt (если нужны),")
    print("затем: docker compose up --build -d")
    print("Внимание: смена postgres_password после первого запуска не меняет пароль уже созданной БД.")


if __name__ == "__main__":
    main()
