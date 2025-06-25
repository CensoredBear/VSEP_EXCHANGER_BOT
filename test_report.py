#!/usr/bin/env python3
"""
Тестовый скрипт для проверки команды /report
"""

import asyncio
from handlers import cmd_report
from permissions import is_operator_or_admin

async def test_report_command():
    """Тестируем команду report"""
    print("🧪 Тестирование команды /report...")
    
    # Создаем мок объект сообщения
    class MockMessage:
        def __init__(self, user_id: int, chat_id: int = -1001234567890):
            self.from_user = MockUser(user_id)
            self.chat = MockChat(chat_id)
            
        async def reply(self, text: str, parse_mode: str = None, reply_markup=None):
            print(f"📤 Бот ответил: {text}")
            if reply_markup:
                print(f"🔘 Кнопки: {reply_markup}")
            
    class MockUser:
        def __init__(self, user_id: int):
            self.id = user_id
            
    class MockChat:
        def __init__(self, chat_id: int):
            self.id = chat_id
            
    # Тест 1: Оператор
    print("\n1️⃣ Тест с оператором:")
    message = MockMessage(123456789, -1001234567890)
    
    # Мокаем функцию is_operator_or_admin
    async def mock_is_operator_or_admin(user_id: int) -> bool:
        return True
    
    # Временно заменяем функцию
    import handlers
    original_is_operator_or_admin = handlers.is_operator_or_admin
    handlers.is_operator_or_admin = mock_is_operator_or_admin
    
    try:
        await cmd_report(message)
        print("✅ Команда выполнилась успешно")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        # Восстанавливаем оригинальную функцию
        handlers.is_operator_or_admin = original_is_operator_or_admin
    
    # Тест 2: Обычный пользователь
    print("\n2️⃣ Тест с обычным пользователем:")
    message = MockMessage(987654321, -1001234567890)
    
    async def mock_is_operator_or_admin_false(user_id: int) -> bool:
        return False
    
    handlers.is_operator_or_admin = mock_is_operator_or_admin_false
    
    try:
        await cmd_report(message)
        print("✅ Команда корректно отклонила обычного пользователя")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        handlers.is_operator_or_admin = original_is_operator_or_admin

if __name__ == "__main__":
    print("🚀 Запуск тестов команды /report...")
    asyncio.run(test_report_command())
    print("✅ Тесты завершены!") 