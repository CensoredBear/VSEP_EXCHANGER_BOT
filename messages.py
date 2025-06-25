# messages.py
# TODO: Вынести сюда генерацию всех сообщений (пользователь, админ) из handlers.py 

import asyncio
from aiogram import Bot
from aiogram.types import Message as TgMessage, ReplyKeyboardMarkup, InlineKeyboardMarkup
from aiogram.enums import ParseMode
from datetime import datetime, timezone
import pytz
from config import system_settings
from db import db
from logger import logger, log_system, log_user, log_func, log_db, log_warning, log_error

def get_bali_and_msk_time_list():
    """Вернуть список из 8 вариантов времени: 
    UTC (дата+время), UTC (только время), Бали (дата+время), Бали (только время), МСК (дата+время), МСК (только время), Бали (дата+время), МСК (дата+время)
    """
    now_utc = datetime.now(timezone.utc)
    bali_tz = pytz.timezone("Asia/Makassar")
    msk_tz = pytz.timezone("Europe/Moscow")
    now_utc_long = now_utc.strftime("%d.%m.%Y %H:%M:%S")
    now_utc_short = now_utc.strftime("%H:%M")
    now_bali = now_utc.astimezone(bali_tz).strftime("%d.%m.%Y %H:%M:%S")
    now_bali_long = now_utc.astimezone(bali_tz).strftime("%d.%m.%Y %H:%M")
    now_bali_short = now_utc.astimezone(bali_tz).strftime("%H:%M")
    now_msk = now_utc.astimezone(msk_tz).strftime("%d.%m.%Y %H:%M:%S")
    now_msk_short = now_utc.astimezone(msk_tz).strftime("%H:%M")
    now_msk_long = now_utc.astimezone(msk_tz).strftime("%d.%m.%Y %H:%M")
    return [
        now_utc_long,      # 0: UTC дата+время
        now_utc_short,     # 1: UTC только время
        now_bali,          # 2: Бали дата+время часы:минуты:секунды
        now_bali_short,    # 3: Бали только время часы:минуты
        now_msk,           # 4: МСК дата+времячасы:минуты:секунды
        now_msk_short,     # 5: МСК только время часы:минуты
        now_bali_long,     # 6: Бали дата+время часы:минуты
        now_msk_long,      # 7: МСК дата+время часы:минуты
    ]

async def send_message(
    bot: Bot,
    chat_id: int | None = None,
    text: str | None = None,
    *,
    reply_to_message_id: int | None = None,
    message_thread_id: int | None = None,
    parse_mode: ParseMode = ParseMode.HTML,
    reply_markup: ReplyKeyboardMarkup | InlineKeyboardMarkup = None,
    delete_after: int | None = None,
    delay: int | None = None,
    forward_from_chat_id: int | None = None,
    forward_message_id: int | None = None,
    **kwargs
) -> TgMessage | None:
    """
    Универсальная отправка сообщения:
      - обычное сообщение
      - автоудаление через delete_after секунд
      - ответ на сообщение
      - отправка в тред
      - с клавиатурой
      - с задержкой отправки (delay)
      - пересылка сообщения (forward_from_chat_id, forward_message_id)
      - любые параметры aiogram
    """
    if delay:
        await asyncio.sleep(delay)
    if forward_from_chat_id and forward_message_id:
        msg = await bot.forward_message(
            chat_id if chat_id is not None else 0,
            forward_from_chat_id if forward_from_chat_id is not None else 0,
            forward_message_id if forward_message_id is not None else 0,
            message_thread_id=message_thread_id if message_thread_id is not None else 0,
            **kwargs
        )
    else:
        msg = await bot.send_message(
            chat_id if chat_id is not None else 0,
            text or '',
            reply_to_message_id=reply_to_message_id if reply_to_message_id is not None else 0,
            message_thread_id=message_thread_id if message_thread_id is not None else 0,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs
        )
    if delete_after:
        asyncio.create_task(_auto_delete(bot, chat_id, msg.message_id, delete_after))
    return msg

async def _auto_delete(bot: Bot, chat_id: int | None, message_id: int | None, delay: int | None):
    await asyncio.sleep(delay or 0)
    try:
        await bot.delete_message(chat_id if chat_id is not None else 0, message_id if message_id is not None else 0)
        # Логируем удаление
        print(f"[автоудалено] id={message_id}")
    except Exception:
        pass  # если уже удалено или нет прав

async def edit_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    parse_mode: ParseMode = ParseMode.HTML,
    reply_markup: ReplyKeyboardMarkup | InlineKeyboardMarkup = None,
    **kwargs
):
    return await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        **kwargs
    )

def get_control_usage_message() -> str:
    """Сообщение о правильном использовании команды /control"""
    return (
        "❌ <b>Неправильное использование команды</b>\n\n"
        "Используйте команду в формате:\n"
        "<code>/control CRM-номер номер-заявки</code>\n\n"
        "Например:\n"
        "<code>/control CRM-12345 67890</code>"
    )

def get_control_confirm_message(crm_number: str) -> str:
    """Сообщение с подтверждением использования команды control без CRM"""
    text = "⏳ Отправлено на проверку, ожидаем результата...\n\n"# return (
    if crm_number == "-":
        text += "<i>обращаю внимание, что команда /conrol принята без комментариев (CRM)</i>"
    return (text)


def get_control_notify_message(chat_title: str, user_nick: str, link: str, operators: list, control_count: int) -> str:
    """Сообщение уведомления о запросе контроля"""
    operator_nicks = []
    for op in operators:
        nick = op.get('nickneim', '')
        if nick.startswith('@'):
            operator_nicks.append(nick)
        else:
            operator_nicks.append(f"@{nick}")
    operators_text = ", ".join(operator_nicks) if operator_nicks else "нет активных операторов"
    return (
        f"⚠️⚠️⚠️ ВНИМАНИЮ ОПЕРАТОРОВ:\n"
        f"{operators_text}\n\n"
        f"<b>📢 📢 📢Запрос контроля</b>\n\n"
        f"из чата: {chat_title}\n"
        f"Пользователь: {user_nick}\n"
        f"Время: {get_bali_and_msk_time_list()[2]}\n\n"
        f"Пожалуйста, проверьте заявку и подтвердите оплату.\n"
        f"Ссылка на сообщение: {link}\n\n"
        f"<b>СЕЙЧАС ЗАЯВОК НА КОНТРОЛЕ: {control_count}</b>"
    )


def get_control_error_message(error_type: str) -> str:
    """Сообщения об ошибках при запросе контроля"""
    messages = {
        "not_found": "❌ Заявка не найдена. Проверьте номер и попробуйте снова.",
        "update_error": "❌ Ошибка при обновлении статуса заявки. Попробуйте позже.",
        "notify_error": "❌ Ошибка при отправке уведомлений операторам. Попробуйте позже."
    }
    return messages.get(error_type, "❌ Произошла неизвестная ошибка. Попробуйте позже.")

def get_control_no_attachment_message() -> str:
    """Сообщение об ошибке использования команды без вложения"""
    return (f'''
    🚫 НЕ ВЫПОЛНЕНО!

    ⚠️ПРИЧИНА: <b>Некорректное использование команды</b>

Команда /control должна быть отправлена:
• Либо вместе с вложением
• Либо в ответ на сообщение с вложением
- опционально: вместе с текстом или подписью (например номер CRM)

<blockquote>примеры:
/control 1234567890
/control часть заказа</blockquote>
            
Пожалуйста, прикрепите вложение или ответьте на сообщение с вложением.'''
)

def get_shift_time_message():
    """Получение сообщения о времени смены"""
    return f"Время работы: {system_settings.shift_start_time or ''} - {system_settings.shift_end_time or ''}"

def get_shift_start_message():
    """Получение сообщения о начале смены"""
    return f"Смена начинается в {system_settings.shift_start_time or ''}"

def get_shift_end_message():
    """Получение сообщения о конце смены"""
    return f"Смена заканчивается в {system_settings.shift_end_time or ''}"

def get_night_shift_message():
    """Получение сообщения о ночной смене"""
    return (
        f"⚠️ <b>НОЧНАЯ СМЕНА</b> 🌙\n\n"
        f"В период с {system_settings.shift_end_time or ''} до {system_settings.shift_start_time or ''} "
        f"ответы на заявки — информационные: бот не выдаёт реквизиты, заявки не попадают в базу "
        f"и не могут быть оплачены."
    ) 