import asyncio
from aiogram import Bot
from aiogram.types import Message
from aiogram.filters import Command
from aiogram import Router
from config import config
from db import db

router = Router()

@router.message(Command("checkchat"))
async def check_chat_info(message: Message):
    """Команда для проверки информации о чате в базе данных"""
    chat_id = message.chat.id
    chat_title = message.chat.title or "Личный чат"
    
    # Подключаемся к базе данных
    await db.connect()
    
    try:
        # Проверяем, есть ли чат в базе данных
        chat_info = await db.pool.fetchrow(
            'SELECT * FROM "VSEPExchanger"."user" WHERE id = $1',
            chat_id
        )
        
        response = f"📋 <b>Информация о чате:</b>\n\n"
        response += f"🆔 <b>ID чата:</b> <code>{chat_id}</code>\n"
        response += f"📝 <b>Название:</b> {chat_title}\n"
        
        if chat_info:
            response += f"✅ <b>Найден в базе данных</b>\n"
            response += f"👤 <b>Nickneim:</b> {chat_info.get('nickneim', 'Не установлен')}\n"
            response += f"🔧 <b>Ранг:</b> {chat_info.get('rang', 'Не установлен')}\n"
            response += f"📅 <b>Дата создания:</b> {chat_info.get('created_at', 'Не установлена')}\n"
            
            # Определяем тип медиа
            nickneim = chat_info.get('nickneim', '')
            if nickneim:
                nickneim_upper = nickneim.upper()
                if nickneim_upper.startswith("MBT"):
                    chat_type = "MBT"
                elif nickneim_upper.startswith("LGI"):
                    chat_type = "LGI"
                elif nickneim_upper.startswith("TCT"):
                    chat_type = "TCT"
                else:
                    chat_type = "Неизвестный тип"
            else:
                chat_type = "Nickneim не установлен"
                
            response += f"🎯 <b>Тип для медиа:</b> {chat_type}\n"
        else:
            response += f"❌ <b>НЕ найден в базе данных</b>\n"
            response += f"💡 <b>Нужно добавить запись с nickneim</b>\n"
        
        await message.reply(response, parse_mode="HTML")
        
    except Exception as e:
        error_msg = f"❌ <b>Ошибка при проверке:</b> {str(e)}"
        await message.reply(error_msg, parse_mode="HTML")
    finally:
        await db.close()

async def main():
    bot = Bot(token=config.BOT_TOKEN)
    dp = Router()
    dp.include_router(router)
    
    print("Бот запущен для проверки чата...")
    print("Отправьте команду /checkchat в любой чат, где есть бот")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main()) 