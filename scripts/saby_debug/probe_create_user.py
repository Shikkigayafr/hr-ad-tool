import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # корень проекта

import logging
import sys
from saby_utils import create_saby_user

# ВКЛЮЧАЕМ ЛОГИРОВАНИЕ (покажет запросы и ответы pysaby)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# Твой тестовый логин (обязательно новый!)
TEST_FULLNAME = "Тестов Тест Тестович"
TEST_LOGIN = "test.saby.debug.123413211312231421421466666666645"  # <--- МЕНЯЙ КАЖДЫЙ РАЗ
TEST_PASSWORD = "Test12345!"
TEST_DEPARTMENT = "Отдел исходящих звонков"

print("Попытка создать сотрудника в Saby...")
ok, message = create_saby_user(TEST_FULLNAME, TEST_LOGIN, TEST_PASSWORD, TEST_DEPARTMENT)

print(f"\n{'='*50}")
if ok:
    print(f"✅ УСПЕХ: {message}")
else:
    print(f"❌ ОШИБКА: {message}")
print(f"{'='*50}")