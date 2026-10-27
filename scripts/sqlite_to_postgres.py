"""Переносит данные из старой SQLite-базы в БД, на которую настроено приложение (PostgreSQL).

Порядок:
  1. Поднять стек (`docker compose up -d`): миграции создадут таблицы в PostgreSQL.
  2. Положить старую базу в ./instance/hr.db (она монтируется в контейнер).
  3. Выполнить:
       docker compose exec hr-ad-panel python scripts/sqlite_to_postgres.py instance/hr.db

Скрипт отказывается работать, если в целевой БД уже есть пользователи (чтобы не задвоить данные).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app import app  # noqa: E402
from models import ActionLog, Employee, LoginHistory, User, db  # noqa: E402

# Порядок важен только для читаемости (внешних ключей между таблицами нет)
MODELS = [User, Employee, ActionLog, LoginHistory]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sqlite_path", help="путь к старому файлу hr.db")
    parser.add_argument("--force", action="store_true", help="копировать, даже если в целевой БД уже есть данные")
    args = parser.parse_args()

    if not os.path.isfile(args.sqlite_path):
        sys.exit(f"Файл не найден: {args.sqlite_path}")

    source = create_engine(f"sqlite:///{os.path.abspath(args.sqlite_path)}")
    source_tables = set(inspect(source).get_table_names())

    with app.app_context():
        if not args.force and db.session.query(User).count() > 0:
            sys.exit("В целевой БД уже есть пользователи. Остановка (используйте --force, если это осознанно).")

        for model in MODELS:
            table = model.__table__
            if table.name not in source_tables:
                print(f"{table.name}: в источнике нет таблицы, пропуск")
                continue
            with source.connect() as conn:
                source_columns = {c["name"] for c in inspect(source).get_columns(table.name)}
                columns = [c.name for c in table.columns if c.name in source_columns]
                rows = [dict(r._mapping) for r in conn.execute(text(
                    f'SELECT {", ".join(chr(34) + c + chr(34) for c in columns)} FROM "{table.name}"'))]
            if rows:
                db.session.execute(table.insert(), rows)
            print(f"{table.name}: перенесено {len(rows)}")

        db.session.commit()

        if db.engine.dialect.name == "postgresql":
            # После вставки с явными id счётчики автоинкремента нужно подвинуть
            for model in MODELS:
                name = model.__table__.name
                db.session.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('\"{name}\"', 'id'), COALESCE((SELECT MAX(id) FROM \"{name}\"), 1))"))
            db.session.commit()
            print("Счётчики id обновлены")


if __name__ == "__main__":
    main()
