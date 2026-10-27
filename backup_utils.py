import os
import shutil
import datetime
import glob
import logging

# Настройка логирования (чтобы видеть в контейнере, что бэкап сработал)
logger = logging.getLogger('apscheduler')
logger.setLevel(logging.INFO)

def backup_database(app):
    # Копирование файла работает только для SQLite; PostgreSQL бэкапится сервисом db-backup (pg_dump)
    if not str(app.config.get('SQLALCHEMY_DATABASE_URI', '')).startswith('sqlite'):
        logger.info("БД не SQLite — файловый бэкап пропущен (используйте pg_dump)")
        return

    # Папка, где лежит база (instance) и куда будем класть бэкапы
    instance_dir = os.path.join(app.root_path, 'instance')
    backup_dir = os.path.join(app.root_path, 'backups')
    
    # Создаем папку для бэкапов, если её нет
    os.makedirs(backup_dir, exist_ok=True)
    
    db_path = os.path.join(instance_dir, 'hr.db')
    
    if not os.path.exists(db_path):
        logger.warning("База данных не найдена, бэкап не сделан.")
        return

    # Формируем имя файла: hr_backup_2026-10-26_18-30.db
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    backup_filename = f"hr_backup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)

    try:
        # Копируем файл
        shutil.copy2(db_path, backup_path)
        logger.info(f"Бэкап успешно создан: {backup_filename}")
        
        # Очистка старых бэкапов (оставляем только 7 последних)
        cleanup_old_backups(backup_dir)
        
    except Exception as e:
        logger.error(f"Ошибка при создании бэкапа: {e}")

def cleanup_old_backups(backup_dir, max_backups=7):
    # Ищем все файлы .db в папке бэкапов
    files = glob.glob(os.path.join(backup_dir, '*.db'))
    # Сортируем по времени изменения (старые сверху)
    files.sort(key=os.path.getmtime)
    
    # Если файлов больше, чем max_backups, удаляем самые старые
    if len(files) > max_backups:
        for file in files[:-max_backups]:
            try:
                os.remove(file)
                logger.info(f"Удален старый бэкап: {os.path.basename(file)}")
            except Exception as e:
                logger.error(f"Ошибка при удалении старого бэкапа: {e}")