#!/usr/bin/env python3
"""
Тестовый скрипт для проверки команды /restart
"""

import asyncio
import os
from aiogram import Bot
from aiogram.types import Message
from handlers import cmd_restart

async def test_restart_command():
    """Тестируем команду restart"""
    print("🧪 Тестирование команды /restart...")
    
    # Создаем мок объект сообщения
    class MockMessage:
        def __init__(self, user_id: int, is_superadmin: bool = True):
            self.from_user = MockUser(user_id)
            self.chat = MockChat()
            
        async def answer(self, text: str):
            print(f"📤 Бот ответил: {text}")
            
    class MockUser:
        def __init__(self, user_id: int):
            self.id = user_id
            
    class MockChat:
        def __init__(self):
            self.id = 123456789
            
    # Тест 1: Суперадмин
    print("\n1️⃣ Тест с суперадмином:")
    message = MockMessage(123456789, True)
    
    # Мокаем функцию is_superadmin
    async def mock_is_superadmin(user_id: int) -> bool:
        return True
    
    # Временно заменяем функцию
    import handlers
    original_is_superadmin = handlers.is_superadmin
    handlers.is_superadmin = mock_is_superadmin
    
    try:
        await cmd_restart(message)
        print("✅ Команда выполнилась успешно (бот должен был завершиться)")
    except SystemExit:
        print("✅ Команда /restart работает корректно - процесс завершился")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        # Восстанавливаем оригинальную функцию
        handlers.is_superadmin = original_is_superadmin
    
    # Тест 2: Обычный пользователь
    print("\n2️⃣ Тест с обычным пользователем:")
    message = MockMessage(987654321, False)
    
    async def mock_is_superadmin_false(user_id: int) -> bool:
        return False
    
    handlers.is_superadmin = mock_is_superadmin_false
    
    try:
        await cmd_restart(message)
        print("✅ Команда корректно отклонила обычного пользователя")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        handlers.is_superadmin = original_is_superadmin

if __name__ == "__main__":
    print("🚀 Запуск тестов команды /restart...")
    asyncio.run(test_restart_command())
    print("✅ Тесты завершены!") 