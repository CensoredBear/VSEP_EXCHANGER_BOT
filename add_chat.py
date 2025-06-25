import asyncio
from aiogram import Bot
from aiogram.types import Message
from aiogram.filters import Command
from aiogram import Router
from config import config
from db import db
from datetime import datetime

router = Router()

@router.message(Command("add_chat"))
async def add_chat_to_db(message: Message):
    """Команда для добавления чата в базу данных"""
    chat_id = message.chat.id
    chat_title = message.chat.title or "Личный чат"
    
    # Проверяем, является ли пользователь суперадмином
    user_rank = await db.get_user_rank(message.from_user.id)
    if user_rank != 'superadmin':
        await message.reply("❌ <b>Доступ запрещен!</b> Только суперадмины могут добавлять чаты.", parse_mode="HTML")
        return
    
    # Подключаемся к базе данных
    await db.connect()
    
    try:
        # Проверяем, есть ли уже чат в базе данных
        if db.pool is None:
            await message.reply("❌ <b>Ошибка:</b> Нет подключения к базе данных.", parse_mode="HTML")
            return
        pool = db.pool
        existing_chat = await pool.fetchrow(
            'SELECT * FROM "VSEPExchanger"."user" WHERE id = $1',
            chat_id
        )
        
        if existing_chat:
            response = f"⚠️ <b>Чат уже существует в базе данных!</b>\n\n"
            response += f"🆔 <b>ID чата:</b> <code>{chat_id}</code>\n"
            response += f"📝 <b>Название:</b> {chat_title}\n"
            response += f"👤 <b>Текущий nickneim:</b> {existing_chat.get('nickneim', 'Не установлен')}\n"
            response += f"🔧 <b>Ранг:</b> {existing_chat.get('rang', 'Не установлен')}\n"
            response += f"💡 <b>Используйте команду /update_chat для изменения</b>\n"
        else:
            response = f"📋 <b>Добавление нового чата:</b>\n\n"
            response += f"🆔 <b>ID чата:</b> <code>{chat_id}</code>\n"
            response += f"📝 <b>Название:</b> {chat_title}\n\n"
            response += f"💡 <b>Для добавления чата используйте:</b>\n"
            response += f"<code>/add_chat_mbt ИМЯ</code> - для MBT\n"
            response += f"<code>/add_chat_lgi ИМЯ</code> - для LGI\n"
            response += f"<code>/add_chat_tct ИМЯ</code> - для TCT\n\n"
            response += f"<b>Пример:</b> <code>/add_chat_mbt VSEP_Admin</code>"
        
        await message.reply(response, parse_mode="HTML")
        
    except Exception as e:
        error_msg = f"❌ <b>Ошибка при проверке:</b> {str(e)}"
        await message.reply(error_msg, parse_mode="HTML")
    finally:
        await db.close()

@router.message(Command("add_chat_mbt"))
async def add_chat_mbt(message: Message):
    """Добавление чата типа MBT"""
    await add_chat_with_type(message, "MBT")

@router.message(Command("add_chat_lgi"))
async def add_chat_lgi(message: Message):
    """Добавление чата типа LGI"""
    await add_chat_with_type(message, "LGI")

@router.message(Command("add_chat_tct"))
async def add_chat_tct(message: Message):
    """Добавление чата типа TCT"""
    await add_chat_with_type(message, "TCT")

async def add_chat_with_type(message: Message, chat_type: str):
    """Общая функция для добавления чата с указанным типом"""
    # Проверяем, является ли пользователь суперадмином
    user_rank = await db.get_user_rank(message.from_user.id)
    if user_rank != 'superadmin':
        await message.reply("❌ <b>Доступ запрещен!</b> Только суперадмины могут добавлять чаты.", parse_mode="HTML")
        return
    
    # Получаем имя чата из команды
    command_parts = message.text.split()
    if len(command_parts) < 2:
        await message.reply(f"❌ <b>Ошибка!</b> Укажите имя чата.\n\n<b>Пример:</b> <code>/add_chat_{chat_type.lower()} VSEP_Admin</code>", parse_mode="HTML")
        return
    
    chat_name = " ".join(command_parts[1:])
    chat_id = message.chat.id
    chat_title = message.chat.title or "Личный чат"
    nickneim = f"{chat_type}_{chat_name}"
    
    # Подключаемся к базе данных
    await db.connect()
    
    try:
        # Проверяем, есть ли уже чат в базе данных
        if db.pool is None:
            await message.reply("❌ <b>Ошибка:</b> Нет подключения к базе данных.", parse_mode="HTML")
            return
        pool = db.pool
        existing_chat = await pool.fetchrow(
            'SELECT * FROM "VSEPExchanger"."user" WHERE id = $1',
            chat_id
        )
        
        if existing_chat:
            # Обновляем существующий чат
            await pool.execute(
                'UPDATE "VSEPExchanger"."user" SET nickneim = $1, rang = $2, updated_at = $3 WHERE id = $4',
                nickneim, 'group', datetime.now(), chat_id
            )
            action = "обновлен"
        else:
            # Добавляем новый чат
            await pool.execute(
                'INSERT INTO "VSEPExchanger"."user" (id, nickneim, rang, created_at, updated_at) VALUES ($1, $2, $3, $4, $5)',
                chat_id, nickneim, 'group', datetime.now(), datetime.now()
            )
            action = "добавлен"
        
        response = f"✅ <b>Чат успешно {action}!</b>\n\n"
        response += f"🆔 <b>ID чата:</b> <code>{chat_id}</code>\n"
        response += f"📝 <b>Название:</b> {chat_title}\n"
        response += f"👤 <b>Nickneim:</b> <code>{nickneim}</code>\n"
        response += f"🎯 <b>Тип:</b> {chat_type}\n"
        response += f"🔧 <b>Ранг:</b> group\n"
        response += f"📅 <b>Действие:</b> {action}\n\n"
        response += f"💡 <b>Теперь чат будет использовать медиа для {chat_type}</b>"
        
        await message.reply(response, parse_mode="HTML")
        
    except Exception as e:
        error_msg = f"❌ <b>Ошибка при добавлении чата:</b> {str(e)}"
        await message.reply(error_msg, parse_mode="HTML")
    finally:
        await db.close()

@router.message(Command("update_chat"))
async def update_chat(message: Message):
    """Обновление существующего чата"""
    # Проверяем, является ли пользователь суперадмином
    user_rank = await db.get_user_rank(message.from_user.id)
    if user_rank != 'superadmin':
        await message.reply("❌ <b>Доступ запрещен!</b> Только суперадмины могут обновлять чаты.", parse_mode="HTML")
        return
    
    # Получаем новые параметры из команды
    command_parts = message.text.split()
    if len(command_parts) < 3:
        await message.reply("❌ <b>Ошибка!</b> Укажите тип и имя чата.\n\n<b>Пример:</b> <code>/update_chat TCT VSEP_Admin</code>", parse_mode="HTML")
        return
    
    chat_type = command_parts[1].upper()
    if chat_type not in ["MBT", "LGI", "TCT"]:
        await message.reply("❌ <b>Ошибка!</b> Тип чата должен быть MBT, LGI или TCT.", parse_mode="HTML")
        return
    
    chat_name = " ".join(command_parts[2:])
    chat_id = message.chat.id
    nickneim = f"{chat_type}_{chat_name}"
    
    # Подключаемся к базе данных
    await db.connect()
    
    try:
        # Обновляем чат
        if db.pool is None:
            await message.reply("❌ <b>Ошибка:</b> Нет подключения к базе данных.", parse_mode="HTML")
            return
        pool = db.pool
        result = await pool.execute(
            'UPDATE "VSEPExchanger"."user" SET nickneim = $1, updated_at = $2 WHERE id = $3',
            nickneim, datetime.now(), chat_id
        )
        
        if result == "UPDATE 1":
            response = f"✅ <b>Чат успешно обновлен!</b>\n\n"
            response += f"🆔 <b>ID чата:</b> <code>{chat_id}</code>\n"
            response += f"👤 <b>Новый nickneim:</b> <code>{nickneim}</code>\n"
            response += f"🎯 <b>Тип:</b> {chat_type}\n\n"
            response += f"💡 <b>Теперь чат будет использовать медиа для {chat_type}</b>"
        else:
            response = f"❌ <b>Чат не найден в базе данных!</b>\n\nИспользуйте команду <code>/add_chat_{chat_type.lower()} ИМЯ</code> для добавления."
        
        await message.reply(response, parse_mode="HTML")
        
    except Exception as e:
        error_msg = f"❌ <b>Ошибка при обновлении чата:</b> {str(e)}"
        await message.reply(error_msg, parse_mode="HTML")
    finally:
        await db.close()

async def main():
    bot = Bot(token=config.BOT_TOKEN)
    dp = Router()
    dp.include_router(router)
    
    print("Бот запущен для управления чатами...")
    print("Доступные команды:")
    print("/add_chat - проверить чат")
    print("/add_chat_mbt ИМЯ - добавить чат типа MBT")
    print("/add_chat_lgi ИМЯ - добавить чат типа LGI") 
    print("/add_chat_tct ИМЯ - добавить чат типа TCT")
    print("/update_chat ТИП ИМЯ - обновить существующий чат")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main()) 