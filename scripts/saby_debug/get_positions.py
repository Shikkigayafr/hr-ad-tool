import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = os.getenv("SABY_PASSWORD")

def main():
    manager = SABYManager(login=LOGIN, password=PASSWORD)
    
    print("--- Получаем список должностей из Saby ---")
    
    # Метод sabyPosition.List возвращает должности по фильтру [citation:1]
    # Передаем пустой фильтр, чтобы получить все должности
    query = {
        "Filter": {} 
    }
    
    try:
        result = manager.send_query("sabyPosition.List", query)
        
        # Печатаем весь ответ, чтобы найти ID и названия
        print(json.dumps(result, indent=4, ensure_ascii=False))
        
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    main()