import asyncio
from aiogram import Bot
from aiogram.types import Message
from aiogram.filters import Command
from aiogram import Router
from config import config

router = Router()

@router.message(Command("chatid"))
async def get_chat_id(message: Message):
    """Команда для получения ID чата"""
    chat_id = message.chat.id
    chat_type = message.chat.type
    chat_title = message.chat.title or "Личный чат"
    
    response = f"📋 <b>Информация о чате:</b>\n\n"
    response += f"🆔 <b>ID чата:</b> <code>{chat_id}</code>\n"
    response += f"📝 <b>Название:</b> {chat_title}\n"
    response += f"🔧 <b>Тип:</b> {chat_type}\n"
    
    if message.chat.username:
        response += f"🔗 <b>Username:</b> @{message.chat.username}\n"
    
    await message.reply(response, parse_mode="HTML")

async def main():
    bot = Bot(token=config.BOT_TOKEN)
    dp = Router()
    dp.include_router(router)
    
    print("Бот запущен для получения ID чата...")
    print("Отправьте команду /chatid в любой чат, где есть бот")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main()) 