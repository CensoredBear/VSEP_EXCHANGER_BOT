#!/usr/bin/env python3
"""
Тестовый скрипт для проверки функции получения анекдотов
"""
import asyncio
from joke_parser import get_joke, get_joke_with_source


async def test_joke():
    """Тестируем получение анекдота"""
    print("🎭 Тестируем получение анекдота...")
    
    try:
        # Тест простого получения анекдота
        joke = await get_joke()
        print(f"✅ Простой анекдот получен: {joke[:100]}...")
        
        # Тест получения анекдота с источником
        joke_data = await get_joke_with_source()
        print(f"✅ Анекдот с источником:")
        print(f"   Анекдот: {joke_data['joke'][:100]}...")
        print(f"   Источник: {joke_data['source']}")
        print(f"   Время: {joke_data['timestamp']}")
        
        print("\n🎉 Все тесты прошли успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_joke()) 