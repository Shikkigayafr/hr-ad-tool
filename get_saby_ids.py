import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

# Загружаем переменные окружения
load_dotenv()

# Данные для входа
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = os.getenv("SABY_PASSWORD")
TARGET_INN = os.getenv("SABY_ORG_INN", "").strip()  # ИНН ищем из .env, если он там есть

def print_header(text):
    print(f"\n{'=' * 50}")
    print(f" {text}")
    print(f"{'=' * 50}")

def main():
    if not LOGIN or not PASSWORD:
        print("❌ ОШИБКА: Не заданы SABY_LOGIN или SABY_PASSWORD в файле .env")
        return

    print_header("АВТОРИЗАЦИЯ В SABY")
    try:
        manager = SABYManager(login=LOGIN, password=PASSWORD)
        print("✅ Успешная авторизация.")
    except Exception as e:
        print(f"❌ Ошибка авторизации: {e}")
        return

    # --- ПОИСК ОРГАНИЗАЦИИ ---
    print_header("ПОИСК ОРГАНИЗАЦИИ")
    try:
        orgs = manager.send_query("СБИС.СписокНашихОрганизаций", {"Фильтр": {}})
    except Exception as e:
        print(f"❌ Ошибка при получении организаций: {e}")
        return

    target_org = None
    if orgs and 'НашаОрганизация' in orgs:
        org_list = orgs['НашаОрганизация']
        if isinstance(org_list, dict):
            org_list = [org_list]

        print(f"Доступно организаций: {len(org_list)}")
        
        for org in org_list:
            inn = ""
            name = ""
            
            # Вытаскиваем данные в зависимости от типа (ИП или ЮЛ)
            if 'СвФЛ' in org:
                inn = org['СвФЛ'].get('ИНН', '')
                name = org['СвФЛ'].get('НазваниеПолное', '')
            elif 'СвЮЛ' in org:
                inn = org['СвЮЛ'].get('ИНН', '')
                name = org['СвЮЛ'].get('Название', '')

            print(f" - {name} (ИНН: {inn})")

            # Если в .env задан ИНН, ищем именно его
            if TARGET_INN and inn == TARGET_INN:
                target_org = org
                print(f"👉 ВЫБРАНА ОРГАНИЗАЦИЯ ПО ИНН: {name}")

    if not target_org:
        # Если ИНН не задан в .env или не найден, берем первую попавшуюся
        if not TARGET_INN and org_list:
            target_org = org_list[0]
            print("⚠️ SABY_ORG_INN не задан в .env. Взята первая организация из списка.")
        else:
            print(f"❌ Организация с ИНН '{TARGET_INN}' не найдена. Проверь доступы.")
            return

    # --- ПОЛУЧЕНИЕ ПОДРАЗДЕЛЕНИЙ ---
    print_header("ПОЛУЧЕНИЕ ПОДРАЗДЕЛЕНИЙ")
    
    # Формируем фильтр
    filter_params = {}
    if 'СвФЛ' in target_org:
        filter_params = {"НашаОрганизация": {"СвФЛ": {"ИНН": target_org['СвФЛ']['ИНН']}}}
    elif 'СвЮЛ' in target_org:
        filter_params = {"НашаОрганизация": {"СвЮЛ": {"ИНН": target_org['СвЮЛ']['ИНН'], "КПП": target_org['СвЮЛ']['КПП']}}}

    try:
        query = {"Параметр": {"Фильтр": filter_params}}
        departments = manager.send_query("СБИС.СписокПодразделений", query)
        
        if not departments or 'Подразделение' not in departments:
            print("❌ Подразделения не найдены. Ответ Saby:", departments)
            return

        dept_list = departments['Подразделение']
        if isinstance(dept_list, dict):
            dept_list = [dept_list]

        print(f"Найдено отделов: {len(dept_list)}\n")
        
        print("--- ГОТОВЫЙ КОД ДЛЯ ВСТАВКИ В .env ---")
        for dept in dept_list:
            dept_name = dept.get('Название', 'Без названия')
            dept_id = dept.get('Идентификатор', '')
            
            # Выводим красиво в консоль
            print(f"📁 {dept_name}: {dept_id}")
            
            # Генерируем строку для .env (транслит для удобства)
            # Например: Отдел исходящих звонков -> SABY_DEPT_OUTGOING
            print(f"   SABY_DEPT_{dept_name.upper().replace(' ', '_')}={dept_id}")
        print("--------------------------------------")

    except Exception as e:
        print(f"❌ Ошибка при получении подразделений: {e}")

if __name__ == "__main__":
    main()