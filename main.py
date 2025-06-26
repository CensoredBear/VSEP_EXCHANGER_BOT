print('=== BOT MAIN.PY STARTED ===')
import asyncio
import sys
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import Message
import logging
from aiogram.fsm.storage.memory import MemoryStorage
import traceback

from config import config, system_settings
from logger import logger, log_system, log_info, setup_logger
from scheduler import Scheduler, init_scheduler
from handlers import register_handlers, set_commands, cmd_help, cmd_start, cmd_check
from messages import send_startup_message
from db import db
from middlewares import UserSaveMiddleware, ChatLoggerMiddleware
from callback_guard import CallbackInitiatorGuard

async def main():
    setup_logger()
    logger.info("Бот запускается...")

    # Явным образом загружаем переменные окружения
    if not config.BOT_TOKEN:
        raise ValueError("Необходимо установить BOT_TOKEN в .env файле")

    await db.connect()
    logger.info("База данных подключена")

    # Загружаем системные настройки из БД
    logger.info("Попытка загрузки системных настроек из БД...")
    if await system_settings.load():
        logger.info("Системные настройки успешно загружены.")
    else:
        logger.warning("Не удалось загрузить системные настройки. Попытка создать настройки по умолчанию...")
        await db.ensure_system_settings()
        logger.info("Созданы системные настройки по умолчанию. Повторная попытка загрузки...")
        if not await system_settings.load():
            logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить системные настройки даже после их создания. Остановка бота.")
            raise RuntimeError("Не удалось загрузить системные настройки.")

    bot = Bot(token=str(config.BOT_TOKEN), default=DefaultBotProperties(parse_mode="HTML"))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Проверяем существование таблицы system_settings
    if not await db.check_system_settings_table():
        logger.critical("Таблица system_settings не существует в схеме VSEPExchanger")
        return

    # Проверяем и устанавливаем значения по умолчанию для системных настроек
    await db.ensure_system_settings()
    log_system("Проверка системных настроек завершена")

    # Загружаем системные настройки
    await system_settings.load()

    # Подключаем middleware
    dp.message.middleware(ChatLoggerMiddleware())  # Сначала логирование
    dp.message.middleware(UserSaveMiddleware())   # Потом сохранение пользователя
    dp.callback_query.middleware(ChatLoggerMiddleware())
    dp.callback_query.middleware(CallbackInitiatorGuard())
    dp.chat_member.middleware(ChatLoggerMiddleware())
    
    scheduler = init_scheduler(bot)

    # Регистрация обработчиков
    register_handlers(dp)
    log_system("Обработчики команд зарегистрированы")

    # Установка команд бота
    await set_commands(bot)
    log_system("Команды бота установлены")

    # Отправка сообщения о запуске
    await send_startup_message(bot)
    log_system("Бот готов к работе")

    # Загрузка системных настроек
    await on_startup()

    # Запуск планировщика
    scheduler_task = asyncio.create_task(scheduler.start())
    log_system("VSEP EXCHANGER BOT: Планировщик запущен")

    # Запуск бота
    log_system("Бот запускается...")
    log_system("Запуск polling...")
    try:
        await asyncio.gather(dp.start_polling(bot, scheduler=scheduler), scheduler_task)
    except Exception as e:
        log_system(f"Ошибка при запуске polling: {e}", level=logging.CRITICAL)
        print(traceback.format_exc())
        raise
    finally:
        await db.close()
        logger.info("База данных отключена")
        logger.info("Бот остановлен")

async def on_startup():
    """Действия при запуске бота"""
    # Загружаем системные настройки
    await system_settings.load()
    
    # Остальные действия при запуске
    # ... existing code ...

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
    except Exception as e:
        logger.critical(f"Необработанная ошибка: {e}")
        sys.exit(1) 