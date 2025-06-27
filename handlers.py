"""
VSEPExchangerBot Handlers
=========================
Этот модуль содержит обработчики команд Telegram-бота для сервиса обмена.
"""
from aiogram import Dispatcher, Router
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, BotCommand, BotCommandScopeDefault, BotCommandScopeAllGroupChats, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, User
from aiogram import Bot
from aiogram import F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from datetime import datetime, timezone, time, timedelta
import pytz
import traceback
from aiogram.utils.markdown import code
import sys
import logging
import re
from db import db
from logger import logger, log_system, log_user, log_func, log_db, log_warning, log_error
from db import db
from procedures.bank_handlers import bank_router
from procedures.shift_handlers import force_open_callback, force_close_callback
from procedures.rate_handlers import rate_change_confirm, rate_change_cancel
from permissions import is_admin_or_superadmin, is_operator_or_admin
from help_menu import build_pretty_help_text, get_bot_commands_for_status
from messages import (
    get_bali_and_msk_time_list,
    get_control_usage_message,
    get_control_notify_message,
    # get_control_success_message,
    get_control_error_message,
    send_message,
    get_control_confirm_message,
    get_control_no_attachment_message,
    send_to_admin_group_safe
)
from chat_logger import log_message
from procedures.input_sum import handle_input_sum
from scheduler import init_scheduler, scheduler, night_shift
from config import config, system_settings
from google_sync import write_to_google_sheet_async, write_multiple_to_google_sheet, read_sum_all_report
from utils import fmt_0, fmt_2, fmt_delta
from commands.accept import router as accept_router
from commands.joke import router as joke_router
from commands.dice import router as dice_router
from commands.coin import router as coin_router
from commands.meme import router as meme_router
from commands.order_change import router as order_change_router
import time
import asyncio
from aiogram.exceptions import TelegramBadRequest, TelegramMigrateToChat
import json
from collections import defaultdict
from joke_parser import get_joke, get_joke_with_source
from commands.joke import router as joke_router
from bybit_api import get_idr_usdt_rate
from bybit_p2p import get_p2p_idr_usdt_avg_rate

# Создаем роутер для всех обработчиков
router = Router()

# Определяем классы состояний FSM в начале файла
class RateChangeStates(StatesGroup):
    waiting_for_new_rate = State()

class ShiftTimeStates(StatesGroup):
    waiting_for_time = State()

class ControlStates(StatesGroup):
    waiting_for_order_selection = State()

class VsepReportStates(StatesGroup):
    waiting_for_month = State()
    waiting_for_rate = State()

BALI_TZ = timezone(timedelta(hours=8))

# Глобальный dict: для каждого чата только один актуальный control message_id
active_control_message = defaultdict(lambda: None)

# Кастомный календарь для выбора месяца/года
class MonthYearCalendar:
    """Календарь для выбора только месяца и года"""
    
    def __init__(self, locale='ru_RU'):
        self.locale = locale
        self.months = {
            'ru_RU': [
                'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
            ],
            'en_US': [
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ]
        }
        self.months_short = {
            'ru_RU': [
                'янв.', 'фев.', 'мар.', 'апр.', 'май', 'июн.',
                'июл.', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.'
            ],
            'en_US': [
                'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
            ]
        }
    
    def create_month_year_keyboard(self, year: int, month: int = None) -> InlineKeyboardMarkup:
        """Создает клавиатуру для выбора месяца/года"""
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        builder = InlineKeyboardBuilder()
        
        # Если месяц не выбран, показываем месяцы
        if month is None:
            # Заголовок с годом
            builder.row(InlineKeyboardButton(
                text=f"📅 {year}",
                callback_data=f"my_year_{year}"
            ))
            
            # Кнопки навигации по годам
            nav_row = []
            nav_row.append(InlineKeyboardButton(
                text="◀️",
                callback_data=f"my_year_{year-1}"
            ))
            nav_row.append(InlineKeyboardButton(
                text="▶️",
                callback_data=f"my_year_{year+1}"
            ))
            builder.row(*nav_row)
            
            # Месяцы (3 в ряд)
            months = self.months.get(self.locale, self.months['en_US'])
            for i in range(0, 12, 3):
                row = []
                for j in range(3):
                    if i + j < 12:
                        month_num = i + j + 1
                        row.append(InlineKeyboardButton(
                            text=months[i + j],
                            callback_data=f"my_month_{year}_{month_num}"
                        ))
                builder.row(*row)
            
            # Кнопка отмены
            builder.row(InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="my_cancel"
            ))
        
        return builder.as_markup()
    
    def process_selection(self, callback_data: str) -> tuple[bool, dict]:
        """Обрабатывает выбор в календаре"""
        if callback_data == "my_cancel":
            return True, {"action": "cancel"}
        
        if callback_data.startswith("my_year_"):
            year = int(callback_data.split("_")[2])
            return False, {"year": year, "month": None}
        
        if callback_data.startswith("my_month_"):
            parts = callback_data.split("_")
            year = int(parts[2])
            month = int(parts[3])
            return True, {"year": year, "month": month}
        
        return False, {}

"""🟡 Установка команд бота в меню"""
async def set_commands(bot: Bot):
    # Получаем список всех пользователей-админов, операторов и супер-админов
    # Для простоты: для личных чатов — ставим команды по статусу пользователя
    # Для групп — только help и accept
    from aiogram.types import BotCommandScopeDefault, BotCommandScopeAllGroupChats
    from db import db
    # Получаем всех пользователей с рангами
    # (В реальном боте можно кэшировать или оптимизировать)
    # Для личных чатов — индивидуально по пользователю
    # Для групп — только help и accept
    # Здесь пример для всех пользователей, но Telegram API не позволяет массово назначать индивидуальные меню — только через BotCommandScopeChat
    # Поэтому для всех по умолчанию — admin-меню, для групп — help и accept
    admin_commands = get_bot_commands_for_status("admin")
    group_commands = [
        BotCommand(command="help", description="Показать справку по командам"),
        BotCommand(command="report", description="Показать отчет по заявкам")
        # BotCommand(command="accept", description="Отметка о принятии платежа")
    ]
    await bot.set_my_commands(admin_commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())

"""🟡 Отбивка для команд в разработке"""
async def cmd_in_development(message: Message, command_name: str, description: str):
    response = f"<b>{command_name}</b>\n{description}\n\n⚠️ Команда в разработке"
    await message.reply(response)
    logger.info(f"Вызвана команда {command_name} (в разработке)")

# === CALLBACK HANDLERS ДЛЯ СМЕН ===
async def force_open_callback(call: CallbackQuery, data: dict):
    print("DATA IN force_open_callback:", data)
    if call.data == "force_open_yes":
        await scheduler.send_shift_start()
        scheduler.sent_start_today = True
        scheduler.sent_end_today = False
        await call.message.edit_text("Смена принудительно открыта.")
    else:
        await call.message.edit_text("Операция отменена.")

async def force_close_callback(call: CallbackQuery, data: dict):
    print("DATA IN force_close_callback:", data)
    if call.data == "force_close_yes":
        await scheduler.send_shift_end()
        scheduler.sent_end_today = True
        await call.message.edit_text("Смена принудительно закрыта.")
    else:
        await call.message.edit_text("Операция отменена.")

# === CALLBACK HANDLERS ДЛЯ ИЗМЕНЕНИЯ КУРСОВ ===
async def rate_change_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # Защита: только инициатор может подтверждать
    if call.from_user.id != call.message.reply_to_message.from_user.id if call.message.reply_to_message else call.from_user.id:
        try:
            await call.answer("Только инициатор может подтверждать изменение курса!", show_alert=True)
        except Exception:
            pass
        return
    if 'new_rate' not in data:
        try:
            await call.answer("Данные устарели, начните заново.", show_alert=True)
        except Exception:
            pass
        await call.message.edit_text("Данные устарели, начните заново.")
        await state.clear()
        return
    new_rate = float(data['new_rate'])
    coefs = await db.get_rate_coefficients()
    
    # Проверяем, что коэффициенты получены
    if not coefs:
        await call.message.edit_text("❌ Ошибка: не удалось получить коэффициенты курсов. Попробуйте позже.")
        await state.clear()
        return
    
    main_coef = float(coefs['main_rate'])
    rate1 = new_rate * float(coefs['rate1']) / main_coef
    rate2 = new_rate * float(coefs['rate2']) / main_coef
    rate3 = new_rate * float(coefs['rate3']) / main_coef
    rate4 = new_rate * float(coefs['rate4']) / main_coef
    rate_back = new_rate * float(coefs['rate_back']) / main_coef
    old_rate_row = await db.get_actual_rate()
    old_rate_special = old_rate_row['rate_special'] if old_rate_row else None
    rate_special = old_rate_special
    
    # Проверяем, что пул базы данных доступен
    if not db.pool:
        await call.message.edit_text("❌ Ошибка: база данных недоступна. Попробуйте позже.")
        await state.clear()
        return
    
    await db.pool.execute('UPDATE "VSEPExchanger"."rate" SET is_actual=FALSE WHERE is_actual=TRUE')
    await db.pool.execute('''
        INSERT INTO "VSEPExchanger"."rate" (main_rate, rate1, rate2, rate3, rate4, rate_back, rate_special, created_by, created_at, is_actual)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), TRUE)
    ''', new_rate, rate1, rate2, rate3, rate4, rate_back, rate_special, call.from_user.id)
    await call.message.edit_text("Курсы изменены!")
    await cmd_rate_show(call.message)
    await state.clear()

async def rate_change_cancel(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # Защита: только инициатор может отменять
    if call.from_user.id != call.message.reply_to_message.from_user.id if call.message.reply_to_message else call.from_user.id:
        try:
            await call.answer("Только инициатор может отменять изменение курса!", show_alert=True)
        except Exception:
            pass
        return
    await call.message.edit_text("Изменение курса отменено.")
    await state.clear()

# === CALLBACK HANDLERS ДЛЯ CONTROL ===
async def process_control_request(message: Message, crm_number: str):
    """Обработка запроса контроля"""
    log_func(f"Начало обработки запроса контроля с {crm_number}")
    user = message.from_user
    user_nick = f"@{user.username}" if user.username else user.full_name
    chat_id = message.chat.id
    msg_id = message.message_id
    chat_title = message.chat.title or message.chat.full_name or str(chat_id)
    
    # Формируем ссылку на сообщение
    if message.chat.username:
        link = f"https://t.me/{message.chat.username}/{msg_id}"
    else:
        chat_id_num = str(chat_id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link = f"https://t.me/c/{chat_id_num}/{msg_id}"
    
    log_func(f"Сформирована ссылка на сообщение: {link}")
    
    try:
        # Получаем список операторов
        operators = await db.get_operators()
        if not operators:
            await message.reply("❌ Нет активных операторов для контроля.")
            return
        log_func(f"Получен список операторов: {len(operators)}")
        
        # Счетчик контроля для текущего чата
        counter = await db.get_control_counter(chat_id)
        if counter is None:
            counter = 0
        new_counter = counter + 1
        await db.set_control_counter(chat_id, new_counter)
        log_func(f"Счетчик контроля для чата {chat_id} увеличен: {counter} -> {new_counter}")
        
        # Получаем все счетчики контроля по всем чатам
        all_counters = await db.get_all_control_counters()
        if not all_counters:
            all_counters = []
        log_func(f"Получены счетчики контроля: {len(all_counters)} чатов")
        
        # Формируем текст уведомления
        operator_nicks = []
        for op in operators:
            nick = op.get('nickneim', str(op['id']))
            if nick.startswith('@'):
                operator_nicks.append(nick)
            else:
                operator_nicks.append(f"@{nick}")
        operators_text = ", ".join(operator_nicks) if operator_nicks else "нет активных операторов"
        
        # Формируем строки со счетчиками контроля
        counter_lines = []
        for chat_counter in all_counters:
            if chat_counter['counter'] > 0:  # Показываем только чаты с счетчиком > 0
                counter_emoji = "🟨" if chat_counter['counter'] == 1 else "🟥" * chat_counter['counter']
                counter_lines.append(f"{counter_emoji} Счетчик контроля <code>{chat_counter['chat_title']}</code>: {chat_counter['counter']}")
        
        counters_text = "\n".join(counter_lines) if counter_lines else "Нет активных счетчиков контроля"
        
        notify_text = f"""<b>⚠️⚠️⚠️ ВНИМАНИЮ ОПЕРАТОРОВ:</b> 
👨‍💻 {operators_text}

⚜️ <b>ЗАПРОС КОНТРОЛЯ ОПЛАТЫ</b>
    из чата: <code>{chat_title}</code>
👤 <b>Автор:</b> <code>{user_nick}</code>
🔗 <b>Ссылка:</b> <b><a href='{link}'>ПЕРЕЙТИ К ЗАПРОСУ</a></b>

📝 <b>Примечание:</b> <code>{crm_number}</code>

{counters_text}
"""
        
        # Отправляем уведомление в админский чат
        await send_to_admin_group_safe(message.bot, notify_text)
        log_system(f"Отправлено уведомление в админский чат {config.ADMIN_GROUP}")
        
        # Отправляем личные сообщения каждому оператору
        for operator in operators:
            try:
                operator_id = operator['id']
                operator_nick = operator.get('nickneim', '')
                log_func(f"Отправка сообщения оператору {operator_id} ({operator_nick})")
                await message.bot.send_message(
                    operator_id,
                    notify_text,
                    parse_mode="HTML"
                )
                log_system(f"Отправлено уведомление оператору {operator_id} ({operator_nick})")
            except Exception as e:
                log_error(f"Ошибка при отправке уведомления оператору {operator_id}: {e}")
        
        log_func("Запрос контроля успешно обработан")
    except Exception as e:
        log_error(f"Ошибка при отправке уведомления: {e}")
        await message.reply("❌ Произошла ошибка при отправке уведомления операторам.")

async def process_control_request_with_order(message: Message, crm_number: str, transaction_number: str, order: dict, user: User = None):
    """Обработка запроса контроля с конкретной заявкой"""
    log_func(f"Начало обработки запроса контроля заявки {transaction_number} с {crm_number}")
    
    # Используем переданного пользователя или извлекаем из сообщения
    if user is None:
        user = message.from_user
    
    user_nick = f"@{user.username}" if user.username else user.full_name
    chat_id = message.chat.id
    msg_id = message.message_id + 1
    chat_title = message.chat.title or message.chat.full_name or str(chat_id)
    
    # Формируем ссылку на сообщение
    if message.chat.username:
        link = f"https://t.me/{message.chat.username}/{msg_id}"
    else:
        chat_id_num = str(chat_id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link = f"https://t.me/c/{chat_id_num}/{msg_id}"
    
    log_func(f"Сформирована ссылка на сообщение: {link}")
    
    try:
        # Получаем список операторов
        operators = await db.get_operators()
        if not operators:
            await message.reply("❌ Нет активных операторов для контроля.")
            return
        log_func(f"Получен список операторов: {len(operators)}")
        
        # Счетчик контроля для текущего чата
        counter = await db.get_control_counter(chat_id)
        if counter is None:
            counter = 0
        new_counter = counter + 1
        await db.set_control_counter(chat_id, new_counter)
        log_func(f"Счетчик контроля для чата {chat_id} увеличен: {counter} -> {new_counter}")
        
        # Получаем все счетчики контроля по всем чатам
        all_counters = await db.get_all_control_counters()
        if not all_counters:
            all_counters = []
        log_func(f"Получены счетчики контроля: {len(all_counters)} чатов")
        
        # Формируем текст уведомления
        operator_nicks = []
        for op in operators:
            nick = op.get('nickneim', str(op['id']))
            if nick.startswith('@'):
                operator_nicks.append(nick)
            else:
                operator_nicks.append(f"@{nick}")
        operators_text = ", ".join(operator_nicks) if operator_nicks else "нет активных операторов"
        
        # Формируем строки со счетчиками контроля
        counter_lines = []
        for chat_counter in all_counters:
            if chat_counter['counter'] > 0:  # Показываем только чаты с счетчиком > 0
                counter_emoji = "🟨" if chat_counter['counter'] == 1 else "🟥" * chat_counter['counter']
                counter_lines.append(f"{counter_emoji} Счетчик контроля <code>{chat_counter['chat_title']}</code>: {chat_counter['counter']}")
        
        counters_text = "\n".join(counter_lines) if counter_lines else "Нет активных счетчиков контроля"
        
        # Форматируем суммы для отображения
        rub_amount = int(order['rub_amount']) if order['rub_amount'] else 0
        idr_amount = int(order['idr_amount']) if order['idr_amount'] else 0
        rub_formatted = f"{rub_amount:,}".replace(",", " ")
        idr_formatted = f"{idr_amount:,}".replace(",", " ")
        
        notify_text = f"""<b>⚠️ ВНИМАНИЮ ОПЕРАТОРОВ ⚠️:</b> {operators_text}

▒░ <b>ЗАПРОС КОНТРОЛЯ ОПЛАТЫ</b> ░▒
• из чата: <code>{chat_title}</code>
• <b>Автор:</b> <code>{user_nick}</code>

• <b>Номер заявки:</b> <code>#{transaction_number}</code>
• <b>Сумма:</b> <code>{rub_formatted} RUB | {idr_formatted} IDR</code>
• <b>Примечание:</b> <code>{crm_number}</code>
• <b>Статус заявки:</b> НА КОНТРОЛЕ

{counters_text}

• <b>Ссылка на запрос:</b>
➖➖➖➖➖➖➖➖➖➖➖➖➖
☑ <b><a href='{link}'>ПЕРЕЙТИ К ЗАПРОСУ</a></b> ☑
➖➖➖➖➖➖➖➖➖➖➖➖➖
(перейдите по ссылке, чтобы акцептовать заявку)
"""
        
        # Отправляем уведомление в админский чат
        await send_to_admin_group_safe(message.bot, notify_text)
        log_system(f"Отправлено уведомление в админский чат {config.ADMIN_GROUP}")
        
        # Отправляем личные сообщения каждому оператору
        for operator in operators:
            try:
                operator_id = operator['id']
                operator_nick = operator.get('nickneim', '')
                log_func(f"Отправка сообщения оператору {operator_id} ({operator_nick})")
                await message.bot.send_message(
                    operator_id,
                    notify_text,
                    parse_mode="HTML"
                )
                log_system(f"Отправлено уведомление оператору {operator_id} ({operator_nick})")
            except Exception as e:
                log_error(f"Ошибка при отправке уведомления оператору {operator_id}: {e}")
        
        log_func("Запрос контроля успешно обработан")
    except Exception as e:
        log_error(f"Ошибка при отправке уведомления: {e}")
        await message.reply("❌ Произошла ошибка при отправке уведомления операторам.")

async def control_callback_handler(call: CallbackQuery, state: FSMContext):
    """Обработчик callback-кнопок команды control"""
    log_user(f"Получен callback {call.data} от пользователя {call.from_user.id}")
    
    # Проверяем права доступа (владелец или суперадмин)
    state_data = await state.get_data()
    owner_id = state_data.get('owner_id')
    
    if not owner_id:
        await call.answer("❌ Ошибка: данные сессии устарели.", show_alert=True)
        return
    
    # Проверяем, является ли пользователь владельцем или суперадмином
    is_owner = call.from_user.id == owner_id
    is_superadmin_user = await is_superadmin(call.from_user.id)
    
    if not (is_owner or is_superadmin_user):
        await call.answer("❌ Извините, это не ваша кнопка. Действие невозможно.", show_alert=True)
        return
    
    if call.data == "control_cancel":
        log_func("Обработка нажатия кнопки 'Отмена'")
        
        # Отменяем задачу истечения кнопок
        state_data = await state.get_data()
        expire_task = state_data.get('expire_task')
        base_text = state_data.get('base_text', '')
        if expire_task and not expire_task.done():
            expire_task.cancel()
            log_func("Задача истечения кнопок отменена")
        
        # Убираем кнопки и добавляем текст о незавершенной команде
        new_text = base_text + "\n\n** ℹ️ КОМАНДА КОНТРОЛЬ НЕ ЗАВЕРШЕНА МЕНЕДЖЕРОМ ℹ️. НАЖАТА КНОПКА ОТМЕНА**"
        
        await call.message.edit_text(
            text=new_text,
            reply_markup=None  # Убираем все кнопки
        )
        # Очищаем message_id
        active_control_message[call.message.chat.id] = None
        # Сбрасываем состояние
        await state.clear()
        log_func("Кнопки убраны, добавлен текст об отмене")
        return
    
    if call.data.startswith("control_order_"):
        # Обработка выбора конкретной заявки
        parts = call.data.split("_")
        if len(parts) >= 3:
            transaction_number = parts[2]
            
            # Получаем примечание из состояния
            crm_number = state_data.get('crm_number', '-')
            
            log_func(f"Обработка выбора заявки {transaction_number} с примечанием: {crm_number}")
            
            # Обновляем статус заявки на "на контроле"
            if not db.pool:
                await call.answer("❌ Ошибка: база данных недоступна.", show_alert=True)
                return
            
            try:
                async with db.pool.acquire() as conn:
                    # Проверяем, что заявка существует и имеет статус "создана"
                    order = await conn.fetchrow('''
                        SELECT transaction_number, rub_amount, idr_amount, status
                        FROM "VSEPExchanger"."transactions"
                        WHERE transaction_number = $1 AND source_chat = $2
                    ''', transaction_number, str(call.message.chat.id))
                    
                    if not order:
                        await call.answer("❌ Заявка не найдена.", show_alert=True)
                        return
                    
                    if order['status'] != 'created':
                        await call.answer(f"❌ Заявка уже имеет статус: {order['status']}", show_alert=True)
                        return
                    
                    # Обновляем статус на "на контроле"
                    await conn.execute('''
                        UPDATE "VSEPExchanger"."transactions"
                        SET status = 'control', status_changed_at = NOW()
                        WHERE transaction_number = $1
                    ''', transaction_number)
                    
                    # Записываем в историю
                    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    user_nick = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
                    
                    # Формируем ссылку на сообщение
                    if call.message.chat.username:
                        link = f"https://t.me/{call.message.chat.username}/{call.message.message_id}"
                    else:
                        chat_id_num = str(call.message.chat.id)
                        if chat_id_num.startswith('-100'):
                            chat_id_num = chat_id_num[4:]
                        elif chat_id_num.startswith('-'):
                            chat_id_num = chat_id_num[1:]
                        link = f"https://t.me/c/{chat_id_num}/{call.message.message_id}"
                    
                    control_entry = f"{now_str}${user_nick}$контроль${link}"
                    
                    # Получаем старую историю и добавляем новую запись
                    old_history = await conn.fetchval('''
                        SELECT history FROM "VSEPExchanger"."transactions"
                        WHERE transaction_number = $1
                    ''', transaction_number)
                    
                    if old_history:
                        history = old_history + "%%%" + control_entry
                    else:
                        history = control_entry
                    
                    # Обновляем историю
                    await conn.execute('''
                        UPDATE "VSEPExchanger"."transactions"
                        SET history = $2
                        WHERE transaction_number = $1
                    ''', transaction_number, history)
                    
                    log_func(f"Статус заявки {transaction_number} изменен: created -> control")
                
                # Удаляем сообщение с кнопками
                await call.message.delete()
                
                # Отменяем задачу истечения кнопок
                state_data = await state.get_data()
                expire_task = state_data.get('expire_task')
                if expire_task and not expire_task.done():
                    expire_task.cancel()
                    log_func("Задача истечения кнопок отменена при выборе заявки")
                # Очищаем message_id
                active_control_message[call.message.chat.id] = None
                
                # Отправляем сообщение о том, что заявка отправлена на контроль
                rub_amount = int(order['rub_amount']) if order['rub_amount'] else 0
                idr_amount = int(order['idr_amount']) if order['idr_amount'] else 0
                rub_formatted = f"{rub_amount:,}".replace(",", " ")
                idr_formatted = f"{idr_amount:,}".replace(",", " ")
                
                control_message = (
                    f"🟡 Заявка отправлена на контроль!\n\n"
                    f"• Номер заявки: <code>{transaction_number}</code>\n"
                    f"• Сумма: {rub_formatted} RUB | {idr_formatted} IDR\n"
                    f"• Примечание: {crm_number}\n"
                    f"🟡 Статус заявки: <b>НА КОНТРОЛЕ</b>\n\n"
                    f"Операторы уведомлены.\nОжидайте подтверждения получения транзакции."
                )
                # Добавляем кнопку "Принять" для операторов/админов/суперадминов
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                accept_keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Подтвердить транзакцию (accept)", callback_data=f"accept_order_{transaction_number}")]
                    ]
                )
                control_msg = await call.message.answer(control_message, reply_markup=accept_keyboard)
                log_func("Отправлено сообщение о заявке на контроле с кнопкой Принять")
                
                # Сохраняем ID сообщения с кнопкой в состоянии для использования в accept callback
                await state.update_data(control_message_id=control_msg.message_id)
                
                # Отправляем уведомление операторам
                await process_control_request_with_order(call.message, crm_number, transaction_number, order, call.from_user)
                
                # Сбрасываем состояние
                await state.clear()
                
            except Exception as e:
                log_error(f"Ошибка при обновлении статуса заявки {transaction_number}: {e}")
                await call.answer("❌ Произошла ошибка при обработке заявки.", show_alert=True)
                return
    
    # Сбрасываем состояние
    await state.clear()
    log_func("Состояние сброшено")

# === CALLBACK HANDLERS ДЛЯ REPORT ===
async def report_callback_handler(call: CallbackQuery):
    """Обработчик кнопок в отчете"""
    # Получаем user_id из callback_data
    parts = call.data.split('_')
    action = parts[1]  # 'bill' или 'cancel'
    creator_id = int(parts[2])  # user_id
    
    # Проверяем, что кнопку нажимает тот, кто её создал
    if call.from_user.id != creator_id:
        await call.answer("Это не ваша кнопка!", show_alert=True)
        return
        
    if action == "cancel":
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as e:
            if "query is too old" in e.message:
                await call.message.edit_text("Археологическая кнопка устарела. Попробуйте вызвать новую", reply_markup=None)
            else:
                raise
        return

    if action == "bill":
         # Проверяем права
         if not await is_admin_or_superadmin(call.from_user.id):
            try:
                 await call.answer("Команда доступна только администраторам и супер-админам.", show_alert=True)
            except TelegramBadRequest as e:
                 if "query is too old" in e.message:
                     await call.message.edit_text("Археологическая кнопка устарела. Попробуйте вызвать новую", reply_markup=None)
                 else:
                     raise
            return

         chat_id = call.message.chat.id
         now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
         user = call.from_user
         user_nick = f"@{user.username}" if user.username else user.full_name
         now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
         
         # Формируем ссылку на сообщение
         msg_id = call.message.message_id
         if call.message.chat.username:
             link = f"https://t.me/{call.message.chat.username}/{msg_id}"
         else:
             chat_id_num = str(chat_id)
             if chat_id_num.startswith('-100'):
                 chat_id_num = chat_id_num[4:]
             elif chat_id_num.startswith('-'):
                 chat_id_num = chat_id_num[1:]
             link = f"https://t.me/c/{chat_id_num}/{msg_id}"
         
         # Получаем все ордера со статусом accept для этого чата
         if not db.pool:
             await call.answer("Ошибка: база данных недоступна.", show_alert=True)
             return
         async with db.pool.acquire() as conn:
             rows = await conn.fetch('''
                 SELECT transaction_number, rub_amount, idr_amount
                 FROM "VSEPExchanger"."transactions"
                 WHERE source_chat = $1 AND status = 'accept'
                 ORDER BY status_changed_at
             ''', str(chat_id))
         
         if not rows:
            try:
                 await call.answer("Нет заявок для формирования нового счета.", show_alert=True)
            except TelegramBadRequest as e:
                 if "query is too old" in e.message:
                     await call.message.edit_text("Археологическая кнопка устарела. Попробуйте вызвать новую", reply_markup=None)
                 else:
                     raise
            return

         # Обновляем статус и историю для каждого ордера
         total_idr = 0
         for row in rows:
             transaction_number = row['transaction_number']
             idr = int(row['idr_amount']) if row['idr_amount'] else 0
             total_idr += idr
             
             # Получаем текущую историю
             transaction = await db.get_transaction_by_number(transaction_number)
             old_history = transaction.get('history', '') if transaction else ''
             new_entry = f"{now_str}&{user_nick}&bill&{link}"
             history = old_history + "%%%" + new_entry if old_history else new_entry
             
             # Обновляем статус и историю
             await db.update_transaction_status(transaction_number, "bill", now_utc)
             await db.update_transaction_history(transaction_number, history)
         
         # Формируем новое сообщение
         col1 = 15
         col2 = 12
         col3 = 12
         header = '<b>🟣 СФОРМИРОВАН СЧЕТ НА ВЫПЛАТУ:</b>\n'
         header += f"<code>Количество заказов: {len(rows)}</code>\n"
         header += f"<code>Сумма: {fmt_0(total_idr)} IDR</code>\n\n"
         header += '<b>Список заказов:</b>\n'
         header += f"<code>{'Номер ордера'.ljust(col1)}{'RUB'.rjust(col2)}{'IDR'.rjust(col3)}</code>\n"
         header += f"<code>{'-' * (col1 + col2 + col3)}</code>\n"
         
         lines = []
         total_rub = 0
         for row in rows:
             num = str(row['transaction_number'])
             rub = int(row['rub_amount']) if row['rub_amount'] else 0
             idr = int(row['idr_amount']) if row['idr_amount'] else 0
             lines.append(f"<code>{num.ljust(col1)}</code><code>{fmt_0(rub).rjust(col2)}{fmt_0(idr).rjust(col3)}</code>")
             total_rub += rub
         
         table = header + '\n'.join(lines)
         table += f"\n<code>{'-'*(col1+col2+col3)}</code>"
         table += f"\n<code>ордеров: {len(rows):<5}{fmt_0(total_rub).rjust(col2)}{fmt_0(total_idr).rjust(col3)}</code>"
         
         try:
              await call.message.edit_text(table, parse_mode="HTML", reply_markup=None)
              await call.answer("Счет сформирован", show_alert=True)
         except TelegramBadRequest as e:
              if "query is too old" in e.message:
                  await call.message.edit_text("Археологическая кнопка устарела. Попробуйте вызвать новую", reply_markup=None)
              else:
                  raise

# Обработчики команд для операторов партнеров
"""🟡 Команда sos"""
@router.message(Command("sos"))
async def cmd_sos(message: Message):
    chat = message.chat
    chat_title = chat.title or chat.full_name or str(chat.id)
    msg_id = message.message_id
    # Формируем ссылку на сообщение
    if chat.username:
        link = f"https://t.me/{chat.username}/{msg_id}"
    else:
        chat_id_num = str(chat.id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link = f"https://t.me/c/{chat_id_num}/{msg_id}"
    user = message.from_user
    user_name = user.full_name
    times = get_bali_and_msk_time_list()
    user_username = f"@{user.username}" if user.username else ""
    alert_text = (
        f"🚨 <b>ВНИМАНИЕ!</b>\n\n"
        f"<b>НАЖАТА КНОПКА 🆘!</b>\n\n"
        f"от {user_username} в чате <b>{chat_title}</b>\n"
        f"🕒: {times[6]} (Bali) / {times[5]} (MSK)\n\n"
        f"<b>S⭕️S - СРОЧНО ОТКРОЙТЕ СООБЩЕНИЕ!</b>\n\n"

        f"Ссылка на сообщение:\n{link}"
    )
    
    # Отправляем в админскую группу с обработкой ошибки миграции
    await send_to_admin_group_safe(message.bot, alert_text)
    
    operators = await db.get_operators()
    if not operators:
        operators = []
    admins = await db.get_admins()
    if not admins:
        admins = []
    superadmins = [u for u in admins if u.get('rang') == 'superadmin']
    user_ids = set()
    for u in operators + admins:
        user_ids.add(u['id'])
    for u in superadmins:
        user_ids.add(u['id'])
    for uid in user_ids:
        try:
            await message.bot.send_message(uid, alert_text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не удалось отправить SOS пользователю {uid}: {e}")
    await message.reply("SOS отправлен!")

# Обработчики команд для оператора сервиса

# Обработчики команд для админа сервиса
"""🟡 Команда bank_show"""
@router.message(Command("bank_show"))
async def cmd_bank_show(message: Message):
    if str(message.chat.id) != config.ADMIN_GROUP:
        await message.reply("Извините, команда невозможна в данном чате.")
        return
    if not await is_operator_or_admin(message.from_user.id):
        await message.reply("Команда доступна только операторам и выше.")
        return
    accounts = await db.get_active_bank_accounts()
    if not accounts:
        await message.reply("Нет активных реквизитов.")
        return
    text = "<b>Активные реквизиты:</b>\n"
    for acc in accounts:
        status = []
        if acc.get("is_actual"):
            status.append("🟢 АКТУАЛЬНЫЕ")
        if acc.get("is_special"):
            status.append("🔴 СПЕЦ")
        status_str = ", ".join(status) if status else "резерв"
        text += f"<b>{acc['account_number']}</b>: {acc['bank']}, {acc['card_number']}, {acc['recipient_name']}, {acc['sbp_phone']} — {status_str}\n"
    await message.reply(text)

"""🟡 Команда rate_show"""
@router.message(Command("rate_show"))
async def cmd_rate_show(message: Message):
    if str(message.chat.id) != config.ADMIN_GROUP:
        await message.reply("Извините, команда невозможна в данном чате.")
        return
    """Показать текущие курсы обмена"""
    try:
        # Получаем данные о курсах
        rate = await db.get_actual_rate()
        logger.info(f"Запрос курсов обмена от пользователя {message.from_user.id}. Получены данные: {rate}")
        if not rate:
            logger.warning(f"Курсы обмена не установлены. Запрос от пользователя {message.from_user.id}")
            await message.reply("❌ Курсы обмена не установлены")
            return

        # Получаем лимиты и коэффициенты
        limits = await db.get_rate_limits()
        coefs = await db.get_rate_coefficients()
        logger.info(f"Получены лимиты: {limits} и коэффициенты: {coefs} для пользователя {message.from_user.id}")

        # Формируем таблицу
        header = '*♻️ Текущие параметры обмена:*'
        lines = []
        coln1 = 15  # от
        coln2 = 12  # до
        coln4 = 9  # курс
        coln5 = 9   # надбавка

        lines.append(code('Актуальные'))
        # Заголовок таблицы
        lines.append(
            code('от').ljust(coln1) +
            code('до').ljust(coln2) +
            code('Курс').ljust(coln4) +
            code('Надбавка').ljust(coln5)
        )
        lines.append(code('-' * (coln1 + coln2 + coln4 + coln5)))

        # Строки с курсами
        if not limits or not rate or not coefs:
            await message.reply("❌ Ошибка: не удалось получить курсы или лимиты. Попробуйте позже.")
            return
        def safe_get(d, key, default="—"):
            return d[key] if d and key in d and d[key] is not None else default
        lines.append(
            '0'.ljust(coln1) +
            fmt_0(safe_get(limits, 'main_rate')).ljust(coln2) +
            fmt_2(safe_get(rate, 'main_rate')).ljust(coln4) +
            fmt_delta(safe_get(coefs, 'main_rate')).ljust(coln5)
        )
        lines.append(
            fmt_0(safe_get(limits, 'main_rate')).ljust(coln1) +
            fmt_0(safe_get(limits, 'rate1')).ljust(coln2) +
            fmt_2(safe_get(rate, 'rate1')).ljust(coln4) +
            fmt_delta(safe_get(coefs, 'rate1')).ljust(coln5)
        )
        lines.append(
            fmt_0(safe_get(limits, 'rate1')).ljust(coln1) +
            fmt_0(safe_get(limits, 'rate2')).ljust(coln2) +
            fmt_2(safe_get(rate, 'rate2')).ljust(coln4) +
            fmt_delta(safe_get(coefs, 'rate2')).ljust(coln5)
        )
        lines.append(
            fmt_0(safe_get(limits, 'rate2')).ljust(coln1) +
            fmt_0(safe_get(limits, 'rate3')).ljust(coln2) +
            fmt_2(safe_get(rate, 'rate3')).ljust(coln4) +
            fmt_delta(safe_get(coefs, 'rate3')).ljust(coln5)
        )
        lines.append(
            fmt_0(safe_get(limits, 'rate3')).ljust(coln1) +
            '∞'.ljust(coln2) +
            fmt_2(safe_get(rate, 'rate4')).ljust(coln4) +
            fmt_delta(safe_get(coefs, 'rate4')).ljust(coln5)
        )
        # Обратный курс и спец. лимит
        lines.append('')
        lines.append(
            code('Обратный курс (возврат)....').ljust(coln1 + coln2) +
            fmt_2(safe_get(rate, 'rate_back')).ljust(coln4) +
            fmt_delta(safe_get(coefs, 'rate_back')).ljust(coln5)
        )
        lines.append(
            code('Специальные реквизиты от...').ljust(coln1 + coln2) +
            code(fmt_0(safe_get(rate, 'rate_special')) + ' руб').ljust(coln4) +
            ' '.ljust(coln5)
        )

        # Информация о последнем изменении
        user_id = rate.get("created_by")
        from_user = "—"
        if user_id:
            admins = await db.get_admins() or []
            if not admins:
                admins = []
            operators = await db.get_operators() or []
            if not operators:
                operators = []
            users = {str(u['id']): u['nickneim'] for u in list(admins) + list(operators)}
            from_user = users.get(str(user_id), f"id{user_id}")

        created_at = rate.get("created_at")
        lines.append('')
        lines.append(code(f"Внесено: {from_user}"))
        if created_at:
            lines.append(code(f"Дата: {created_at:%d.%m.%Y %H:%M}"))

        # Формируем итоговый текст
        text = header + '\n```' + '\n'.join(lines) + '\n```'
        
        await message.answer(text, parse_mode="MarkdownV2")
        logger.info(f"Пользователь {message.from_user.id} запросил текущие курсы обмена")
        
    except Exception as e:
        error_msg = f"Ошибка при отображении курсов: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
        await message.reply("❌ Произошла ошибка при отображении курсов")

# Обработчики команд для супер админа
async def is_superadmin(user_id: int) -> bool:
    rank = await db.get_user_rank(user_id)
    return rank in ("superadmin", "суперадмин")

"""🟡 Команда admin_show"""
@router.message(Command("admin_show"))
async def cmd_admin_show(message: Message):
    if not await is_superadmin(message.from_user.id):
        await message.reply("Команда доступна только супер-админу.")
        logger.warning(f"{message.from_user.id} попытался вызвать /admin_show без прав superadmin")
        return
    admins = await db.get_admins() or []
    if not admins:
        await message.reply("В базе нет админов.")
        return
    text = "<b>Админы сервиса:</b>\n"
    for row in admins:
        text += f"✧{row['nickneim']} | {row['id']} | {row['rang']}\n"
    await message.reply(text)
    logger.info(f"{message.from_user.id} запросил список админов")

"""🟡 Команда admin_add"""
@router.message(Command("admin_add"))
async def cmd_admin_add(message: Message):
    if not await is_superadmin(message.from_user.id):
        await message.reply("Команда доступна только супер-админу.")
        logger.warning(f"{message.from_user.id} попытался вызвать /admin_add без прав superadmin")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        logger.info(f"{message.from_user.id} ({message.from_user.username}) попытался вызвать /admin_add без ответа на сообщение в чате {message.chat.id}")
        text = (
            "Отправьте команду в ответ на сообщение участника, которого вы хотите назначить админом.\n\n"
            "Внимание — у админа будут права на изменение ключевых значений в работе сервиса."
        )
        await message.reply(text)
        return
    user = message.reply_to_message.from_user
    username = user.username or user.full_name or f"id{user.id}"
    initiator_id = message.from_user.id
    # --- Добавить в базу, если нет ---
    user_rank = await db.get_user_rank(user.id)
    if not user_rank:
        await db.add_user_if_not_exists(user.id, username)
        await db.set_user_rank(user.id, "admin")
    text = (
        f"Юзеру <b>{username}</b> будут назначены права администратора.\n"
        "У админа будут права на изменение ключевых значений в работе сервиса.\n"
        "Подтвердите действие."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data=f"admin_add_confirm:{user.id}:{initiator_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"admin_add_cancel:{initiator_id}")
            ]
        ]
    )
    await message.reply(text, reply_markup=keyboard)
"""✅ реализация кнопки подтвердить и НАЗНАЧЕНИЯ В БАЗУ"""
async def admin_add_confirm_callback(call: CallbackQuery):
    data = call.data
    if data.startswith("admin_add_confirm:"):
        parts = data.split(":")
        user_id = int(parts[1])
        admin_id = call.from_user.id
        admin_username = call.from_user.username or call.from_user.full_name or f"id{admin_id}"
        logger.info(f"{admin_id} ({admin_username}) подтвердил назначение {user_id} админом в чате {call.message.chat.id}")
        await db.set_user_rank(user_id, "admin")
        username = None
        if call.message.reply_to_message and call.message.reply_to_message.from_user.id == user_id:
            username = call.message.reply_to_message.from_user.username or call.message.reply_to_message.from_user.full_name or f"id{user_id}"
        else:
            admins = await db.get_admins() or []
            for row in admins:
                if row['id'] == user_id:
                    username = row['nickneim']
                    break
            if not username:
                username = f"id{user_id}"
        await call.message.edit_text(f"<b>{username}</b> получил права админа.")
        await call.answer()
"""❌ реализация кнопки отмена"""
async def admin_add_cancel_callback(call: CallbackQuery):
    data = call.data
    if data.startswith("admin_add_cancel:"):
        admin_id = call.from_user.id
        admin_username = call.from_user.username or call.from_user.full_name or f"id{admin_id}"
        logger.info(f"{admin_id} ({admin_username}) отменил назначение админа в чате {call.message.chat.id}")
        await call.message.delete()
        log_message("delete", call.message.chat, call.from_user, text="[удалено ботом]")
        await call.answer()

"""🟡 Команда admin_remove"""
@router.message(Command("admin_remove"))
async def cmd_admin_remove(message: Message):
    if not await is_superadmin(message.from_user.id):
        await message.reply("Команда доступна только супер-админу.")
        logger.warning(f"{message.from_user.id} попытался вызвать /admin_remove без прав superadmin")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        logger.info(f"{message.from_user.id} ({message.from_user.username}) попытался вызвать /admin_remove без ответа на сообщение в чате {message.chat.id}")
        text = (
            "Отправьте команду в ответ на сообщение админа, которого вы хотите удалить.\n\n"
            "Внимание — у пользователя будут сняты права администратора."
        )
        await message.reply(text)
        return
    user = message.reply_to_message.from_user
    username = user.username or user.full_name or f"id{user.id}"
    initiator_id = message.from_user.id
    text = (
        f"У пользователя <b>{username}</b> будут сняты права администратора.\n"
        "Подтвердите действие."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data=f"admin_remove_confirm:{user.id}:{initiator_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"admin_remove_cancel:{initiator_id}")
            ]
        ]
    )
    await message.reply(text, reply_markup=keyboard)
    logger.info(f"{message.from_user.id} инициировал снятие прав админа у {user.id} ({username}) в чате {message.chat.id}")
"""✅ реализация кнопки подтвердить и СНЯТИЯ ПРАВ В БАЗУ"""
async def admin_remove_confirm_callback(call: CallbackQuery):
    data = call.data
    if data.startswith("admin_remove_confirm:"):
        parts = data.split(":")
        user_id = int(parts[1])
        admin_id = call.from_user.id
        admin_username = call.from_user.username or call.from_user.full_name or f"id{admin_id}"
        await db.set_user_rank(user_id, "user")
        username = None
        if call.message.reply_to_message and call.message.reply_to_message.from_user.id == user_id:
            username = call.message.reply_to_message.from_user.username or call.message.reply_to_message.from_user.full_name or f"id{user_id}"
        else:
            admins = await db.get_admins() or []
            for row in admins:
                if row['id'] == user_id:
                    username = row['nickneim']
                    break
            if not username:
                username = f"id{user_id}"
        await call.message.edit_text(f"<b>{username}</b> больше не админ.")
        logger.info(f"{admin_id} ({admin_username}) снял права админа у {user_id} ({username}) в чате {call.message.chat.id}")
        await call.answer()
"""❌ реализация кнопки отмена"""
async def admin_remove_cancel_callback(call: CallbackQuery):
    data = call.data
    if data.startswith("admin_remove_cancel:"):
        admin_id = call.from_user.id
        admin_username = call.from_user.username or call.from_user.full_name or f"id{admin_id}"
        logger.info(f"{admin_id} ({admin_username}) отменил снятие прав админа в чате {call.message.chat.id}")
        await call.message.delete()
        log_message("delete", call.message.chat, call.from_user, text="[удалено ботом]")
        await call.answer()

# Обработчики команд для оператора сервиса
"""🟡 Команда operator_add"""
@router.message(Command("operator_add"))
async def cmd_operator_add(message: Message):
    if not await is_admin_or_superadmin(message.from_user.id):
        await message.reply("Команда доступна только админам и супер-админам.")
        logger.warning(f"{message.from_user.id} попытался вызвать /operator_add без прав admin/superadmin")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        logger.info(f"{message.from_user.id} ({message.from_user.username}) попытался вызвать /operator_add без ответа на сообщение в чате {message.chat.id}")
        text = (
            "Отправьте команду в ответ на сообщение участника, которого вы хотите назначить оператором сервиса.\n\n"
            "Внимание — у оператора будут права на выполнение сервисных операций."
        )
        await message.reply(text)
        return
    user = message.reply_to_message.from_user
    username = user.username or user.full_name or f"id{user.id}"
    initiator_id = message.from_user.id
    # --- Добавить в базу, если нет ---
    user_rank = await db.get_user_rank(user.id)
    if not user_rank:
        await db.add_user_if_not_exists(user.id, username)
        await db.set_user_rank(user.id, "operator")
    text = (
        f"Юзеру <b>{username}</b> будут назначены права оператора сервиса.\n"
        "Подтвердите действие."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data=f"operator_add_confirm:{user.id}:{initiator_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"operator_add_cancel:{initiator_id}")
            ]
        ]
    )
    await message.reply(text, reply_markup=keyboard)
    logger.info(f"{message.from_user.id} инициировал назначение {user.id} ({username}) оператором в чате {message.chat.id}")
"""✅ реализация кнопки подтвердить и НАЗНАЧЕНИЯ В БАЗУ"""
async def operator_add_confirm_callback(call: CallbackQuery):
    data = call.data
    if data.startswith("operator_add_confirm:"):
        parts = data.split(":")
        user_id = int(parts[1])
        admin_id = call.from_user.id
        admin_username = call.from_user.username or call.from_user.full_name or f"id{admin_id}"
        await db.set_user_rank(user_id, "operator")
        username = None
        if call.message.reply_to_message and call.message.reply_to_message.from_user.id == user_id:
            username = call.message.reply_to_message.from_user.username or call.message.reply_to_message.from_user.full_name or f"id{user_id}"
        else:
            ops = await db.get_operators() or []
            for row in ops:
                if row['id'] == user_id:
                    username = row['nickneim']
                    break
            if not username:
                username = f"id{user_id}"
        await call.message.edit_text(f"<b>{username}</b> получил права оператора сервиса.")
        logger.info(f"{admin_id} ({admin_username}) назначил {user_id} ({username}) оператором в чате {call.message.chat.id}")
        await call.answer()
"""❌ реализация кнопки отмена"""
async def operator_add_cancel_callback(call: CallbackQuery):
    data = call.data
    if data.startswith("operator_add_cancel:"):
        admin_id = call.from_user.id
        admin_username = call.from_user.username or call.from_user.full_name or f"id{admin_id}"
        logger.info(f"{admin_id} ({admin_username}) отменил назначение оператора в чате {call.message.chat.id}")
        await call.message.delete()
        log_message("delete", call.message.chat, call.from_user, text="[удалено ботом]")
        await call.answer()

"""🟡 Команда operator_remove"""
@router.message(Command("operator_remove"))
async def cmd_operator_remove(message: Message):
    if not await is_admin_or_superadmin(message.from_user.id):
        await message.reply("Команда доступна только админам и супер-админам.")
        logger.warning(f"{message.from_user.id} попытался вызвать /operator_remove без прав admin/superadmin")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        logger.info(f"{message.from_user.id} ({message.from_user.username}) попытался вызвать /operator_remove без ответа на сообщение в чате {message.chat.id}")
        text = (
            "Отправьте команду в ответ на сообщение оператора, которого вы хотите удалить.\n\n"
            "Внимание — у пользователя будут сняты права оператора."
        )
        await message.reply(text)
        return
    user = message.reply_to_message.from_user
    username = user.username or user.full_name or f"id{user.id}"
    initiator_id = message.from_user.id
    text = (
        f"У пользователя <b>{username}</b> будут сняты права оператора сервиса.\n"
        "Подтвердите действие."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data=f"operator_remove_confirm:{user.id}:{initiator_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"operator_remove_cancel:{initiator_id}")
            ]
        ]
    )
    await message.reply(text, reply_markup=keyboard)
    logger.info(f"{message.from_user.id} инициировал снятие прав оператора у {user.id} ({username}) в чате {message.chat.id}")
"""✅ реализация кнопки подтвердить и СНЯТИЯ ПРАВ В БАЗУ"""
async def operator_remove_confirm_callback(call: CallbackQuery):
    data = call.data
    if data.startswith("operator_remove_confirm:"):
        parts = data.split(":")
        user_id = int(parts[1])
        admin_id = call.from_user.id
        admin_username = call.from_user.username or call.from_user.full_name or f"id{admin_id}"
        await db.set_user_rank(user_id, "user")
        username = None
        if call.message.reply_to_message and call.message.reply_to_message.from_user.id == user_id:
            username = call.message.reply_to_message.from_user.username or call.message.reply_to_message.from_user.full_name or f"id{user_id}"
        else:
            ops = await db.get_operators() or []
            for row in ops:
                if row['id'] == user_id:
                    username = row['nickneim']
                    break
            if not username:
                username = f"id{user_id}"
        await call.message.edit_text(f"<b>{username}</b> больше не оператор сервиса.")
        logger.info(f"{admin_id} ({admin_username}) снял права оператора у {user_id} ({username}) в чате {call.message.chat.id}")
        await call.answer()
"""❌ реализация кнопки отмена"""
async def operator_remove_cancel_callback(call: CallbackQuery):
    data = call.data
    if data.startswith("operator_remove_cancel:"):
        admin_id = call.from_user.id
        admin_username = call.from_user.username or call.from_user.full_name or f"id{admin_id}"
        logger.info(f"{admin_id} ({admin_username}) отменил снятие прав оператора в чате {call.message.chat.id}")
        await call.message.delete()
        log_message("delete", call.message.chat, call.from_user, text="[удалено ботом]")
        await call.answer()

"""🟡 Команда operator_show"""
@router.message(Command("operator_show"))
async def cmd_operator_show(message: Message):
    if not await is_admin_or_superadmin(message.from_user.id):
        await message.reply("Команда доступна только админам и супер-админам.")
        logger.warning(f"{message.from_user.id} попытался вызвать /operator_show без прав admin/superadmin")
        return
    ops = await db.get_operators() or []
    if not ops:
        await message.reply("В базе нет операторов.")
        return
    text = "<b>Операторы сервиса:</b>\n"
    for row in ops:
        text += f"✧ {row['nickneim']} | {row['id']} | {row['rang']}\n"
    await message.reply(text)
    logger.info(f"{message.from_user.id} запросил список операторов")

"""🟡 Команда help"""
@router.message(Command("help"))
async def cmd_help(message: Message):
    print(f"=== CMD_HELP CALLED by {message.from_user.id} ===")
    log_system(f"CMD_HELP CALLED by {message.from_user.id}")
    user_rank = await db.get_user_rank(message.from_user.id)
    logger.info(f"[MSG] chat_id={message.chat.id}; user_id={message.from_user.id}; username={message.from_user.username}; rank={user_rank}; action=received; text={message.text}")
    help_text = build_pretty_help_text(user_rank)
    await message.reply(help_text)
    logger.info(f"[BOT_MSG] chat_id={message.chat.id}; to_user={message.from_user.id}; action=bot_send; text={help_text[:200]}")

"""🟡 Команда start"""
@router.message(CommandStart())
async def cmd_start(message: Message):
    user_rank = await db.get_user_rank(message.from_user.id)
    logger.info(f"[MSG] chat_id={message.chat.id}; user_id={message.from_user.id}; username={message.from_user.username}; rank={user_rank}; action=received; text={message.text}")
    await message.answer("Привет! Я VSEP бот. Используйте /help для просмотра доступных команд.")
    logger.info(f"[BOT_MSG] chat_id={message.chat.id}; to_user={message.from_user.id}; action=bot_send; text=Привет! Я VSEP бот. Используйте /help для просмотра доступных команд.")

"""🟡 Команда check"""
@router.message(Command("check"))
async def cmd_check(message: Message):
    user_rank = await db.get_user_rank(message.from_user.id)
    logger.info(f"[MSG] chat_id={message.chat.id}; user_id={message.from_user.id}; username={message.from_user.username}; rank={user_rank}; action=received; text={message.text}")
    try:
        chat = message.chat
        log_message = f"""
КОМАНДА /CHECK ВЫПОЛНЕНА
"""
        logger.info(log_message.upper())
        response = f"""
КОМАНДА /CHECK ВЫПОЛНЕНА
ЧАТ ID: {chat.id}
ТИП ЧАТА: {chat.type}
НАЗВАНИЕ ЧАТА: {chat.title if chat.title else 'нет названия'}
ИМЯ ПОЛЬЗОВАТЕЛЯ: {message.from_user.full_name if message.from_user else 'неизвестно'}
USERNAME: @{message.from_user.username if message.from_user and message.from_user.username else 'нет username'}
user id: {message.from_user.id if message.from_user else 'неизвестно'}
"""
        # Проверяем наличие вложения в ответном сообщении
        if message.reply_to_message:
            reply = message.reply_to_message
            # Фото
            if reply.photo:
                photo_id = reply.photo[-1].file_id
                response += f"\nID фото: <code>{photo_id}</code>"
            # Видео
            elif reply.video:
                video_id = reply.video.file_id
                response += f"\nID видео: <code>{video_id}</code>"
            # Документ
            elif reply.document:
                doc_id = reply.document.file_id
                response += f"\nID документа: <code>{doc_id}</code>"
            # Анимация (GIF)
            elif reply.animation:
                anim_id = reply.animation.file_id
                response += f"\nID анимации: <code>{anim_id}</code>"
            # Стикер
            elif reply.sticker:
                sticker_id = reply.sticker.file_id
                response += f"\nID стикера: <code>{sticker_id}</code>"
            # Аудио
            elif reply.audio:
                audio_id = reply.audio.file_id
                response += f"\nID аудио: <code>{audio_id}</code>"
            # Голосовое сообщение
            elif reply.voice:
                voice_id = reply.voice.file_id
                response += f"\nID голосового сообщения: <code>{voice_id}</code>"
            # Видео сообщение
            elif reply.video_note:
                video_note_id = reply.video_note.file_id
                response += f"\nID видео сообщения: <code>{video_note_id}</code>"
        
        await message.reply(response, parse_mode="HTML")
        logger.info(f"[BOT_MSG] chat_id={message.chat.id}; to_user={message.from_user.id}; action=bot_send; text={response[:200]}")
    except Exception as e:
        error_msg = f"Ошибка при выполнении команды /check: {e}"
        logger.error(error_msg)
        await message.reply("произошла ошибка при выполнении команды")

@router.message(Command("order_show"))
async def cmd_order_show(message: Message):
    """🟡 Команда order_show"""
    args = message.text.strip().split()
    if len(args) < 2:
        await message.reply("Использование: /order_show <номер_ордера>")
        return
    order_number = args[1]
    transaction = await db.get_transaction_by_number(order_number)
    if not transaction:
        await message.reply("Заявка с таким номером не найдена.")
        return
    # Определяем возврат или обычная заявка
    is_refund = int(transaction.get('idr_amount', 0)) < 0 or int(transaction.get('rub_amount', 0)) < 0
    idr = abs(int(transaction.get('idr_amount', 0)))
    rub = abs(int(transaction.get('rub_amount', 0)))
    # Формируем заголовок
    lines = []
    lines.append(f"<b>Карточка заявки № <code>{order_number}</code></b>")
    if is_refund:
        lines.append(f"\n<b>Сумма возврата:</b> {fmt_0(rub)} RUB ⏮ {fmt_0(idr)} IDR")
    else:
        lines.append(f"\n<b>Сумма:</b> {fmt_0(idr)} IDR ⏮ {fmt_0(rub)} RUB")
    lines.append(f"\n<b>Текущий статус:</b> {transaction.get('status','-')}")
    # Добавляю Note
    note = transaction.get('note')
    if not note:
        note = '-'
    lines.append(f"<b>Note:</b> {note}")
    # История статусов
    history = transaction.get('history', '')
    hist_lines = []
    if history:
        events = history.split('%%%')
        prev_time = None
        for idx, ev in enumerate(events):
            # Поддержка $ и & как разделителей
            if '$' in ev:
                parts = ev.split('$', 3)
            else:
                parts = ev.split('&', 3)
            if len(parts) < 4:
                if idx == 0 and ev.strip():
                    hist_lines.append(f"{ev.strip()} (создано)")
                continue
            dt_str, user, status, link = [p.strip() for p in parts]
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                dt_bali = dt.replace(tzinfo=timezone.utc).astimezone(BALI_TZ)
            except Exception:
                dt = None
                dt_bali = None
            status_map = {
                'night': 'night',
                'control': 'control',
                'accept': 'accept',
                'accounted': 'accounted',
                'created': 'created',
                'создан': 'создан',
                'cancel': 'cancel',
            }
            status_disp = status_map.get(status, status)
            time_str = dt_bali.strftime("%H:%M") if dt_bali else "--:--"
            if idx == 0:
                # Первая строка — дата дд.мм.гг
                date_str = dt_bali.strftime("%d.%m.%y") if dt_bali else "--.--.--"
                hist_lines.append(f"{date_str} {status_disp}: {time_str} {user} (<a href='{link}'>link</a>)")
            else:
                # Разница во времени с предыдущим статусом
                if prev_time and dt:
                    delta = dt - prev_time
                    total_seconds = int(delta.total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    seconds = total_seconds % 60
                    delta_str = f"+{hours:02}:{minutes:02}:{seconds:02}"
                else:
                    delta_str = "+--:--:--"
                hist_lines.append(f"{delta_str} {status_disp}: {time_str} {user} (<a href='{link}'>link</a>)")
            prev_time = dt
    if hist_lines:
        lines.append("\n<b>Хронология:</b>")
        lines.extend(hist_lines)
    # Реквизиты
    acc_info = transaction.get('account_info', '-')
    lines.append(f"\n<b>Реквизиты:</b> {acc_info}")
    await message.reply('\n'.join(lines), parse_mode="HTML")

@router.message(Command("transfer"))
async def cmd_transfer(message: Message):
    """🟡 Команда transfer"""
    # Проверка: команда должна быть с фото или документом, либо в ответ на сообщение с фото или документом
    has_attachment = bool(message.photo or message.document or message.video or message.animation)
    is_reply = bool(message.reply_to_message)
    reply_has_attachment = is_reply and bool(
        message.reply_to_message.photo or 
        message.reply_to_message.document or 
        message.reply_to_message.video or 
        message.reply_to_message.animation
    )
    if not (has_attachment or reply_has_attachment):
        await message.reply("\n🚫 НЕ ВЫПОЛНЕНО!\n\nПРИЧИНА: команда /transfer [сумма_в_IDR] должна быть с фото или документом или отправлена в ответ на сообщение с фото или документом.")
        return

    # Проверяем наличие текста в сообщении или подписи к фото/документу
    command_text = message.text or message.caption
    if not command_text:
        await message.reply("\n🚫 НЕ ВЫПОЛНЕНО!\n\nПРИЧИНА: команда должна содержать сумму: /transfer [сумма_в_IDR]")
        return

    progress_msg = await message.reply("⏳ Команда принята, выполняю проверку, ожидайте...")

    # Проверка прав доступа
    user_id = message.from_user.id
    if not await is_admin_or_superadmin(user_id):
        await progress_msg.edit_text("Команда доступна только администраторам и супер-админам.")
        return

    # Получаем сумму из команды
    try:
        args = command_text.split()
        if len(args) != 2:
            await progress_msg.edit_text("\n🚫 НЕ ВЫПОЛНЕНО!\n\nПРИЧИНА: формат команды: /transfer [сумма_в_IDR] (только число, без пробелов)", parse_mode="HTML")
            return
        transfer_amount = float(args[1])
    except ValueError:
        await progress_msg.edit_text("Неверный формат суммы. Используйте число.")
        return

    chat_id = message.chat.id
    # Получаем все ордера со статусом bill для этого чата
    if not db.pool:
        await progress_msg.edit_text("Ошибка: база данных недоступна.")
        return
    async with db.pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT transaction_number, rub_amount, idr_amount, status
            FROM "VSEPExchanger"."transactions"
            WHERE source_chat = $1 
            AND status = 'bill'
            ORDER BY status_changed_at
        ''', str(chat_id))

    if not rows:
        await progress_msg.edit_text("Не найдено ордеров со статусом 'bill'.")
        return

    # Проверяем сумму
    total_idr = sum(row['idr_amount'] for row in rows)
    order_count = len(rows)
    tolerance = 1000
    if abs(total_idr - transfer_amount) > tolerance:  # Допускаем погрешность в 1000 IDR
        msg = (
            f"🚫 НЕ ВЫПОЛНЕНО!\n\n"
            f"ПРИЧИНА: сумма не совпадает со счетом.\n\n"
            f"🔹 В ИМЕЮЩЕМСЯ СЧЕТЕ НА ВЫПЛАТУ: Количество ордеров со статусом 'bill', подлежащих оплате: <b>{order_count}</b> на сумму: <b>{fmt_0(total_idr)} IDR</b>\n"
            f"🔸 В КОМАНДЕ УКАЗАНО: <b>{fmt_0(transfer_amount)} IDR</b>\n"
            f"\nРазница: <b>{fmt_0(abs(total_idr - transfer_amount))} IDR</b>\n"
            f"💭 Проверьте сумму и повторите подтверждение трансфера."
        )
        await progress_msg.edit_text(msg, parse_mode="HTML")
        return

    # Подтверждаем оплату для всех ордеров
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    user = message.from_user
    user_nick = f"@{user.username}" if user.username else user.full_name
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    chat_id = message.chat.id
    msg_id = message.message_id
    if message.chat.username:
        link = f"https://t.me/{message.chat.username}/{msg_id}"
    else:
        chat_id_num = str(chat_id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link = f"https://t.me/c/{chat_id_num}/{msg_id}"

    # Список данных для записи в Google Sheets
    gsheet_rows = []

    for row in rows:
        transaction_number = row['transaction_number']
        transaction = await db.get_transaction_by_number(transaction_number)
        if not transaction:
            continue  # если транзакция не найдена, пропускаем
        old_history = transaction.get('history', '') if transaction else ''
        new_entry = f"{now_str}&{user_nick}&accounted&{link}"
        history = old_history + "%%%" + new_entry if old_history else new_entry
        
        # Обновляем статус и историю в базе данных
        await db.update_transaction_status(transaction_number, "accounted", now_utc)
        await db.update_transaction_history(transaction_number, history)
        
        # Подготавливаем данные для Google Sheets
        # Формат: [transaction_number, user_nick, idr_amount, rub_amount, used_rate, status, note, acc_info, history, source_chat, now_str, transfer_dt]
        gsheet_row = [
            transaction_number,
            user_nick,
            row['idr_amount'],
            row['rub_amount'],
            transaction.get('used_rate', 0) if transaction else 0,
            'accounted',
            transaction.get('note', '') if transaction else '',
            transaction.get('acc_info', '') if transaction else '',
            history,
            str(chat_id),
            transaction.get('created_at', now_utc) if transaction else now_utc,
            now_utc  # дата выполнения /transfer
        ]
        gsheet_rows.append(gsheet_row)

    # Записываем все ордера в Google Sheets
    try:
        await write_multiple_to_google_sheet(str(chat_id), gsheet_rows)
        log_func(f"Успешно записано {len(gsheet_rows)} ордеров в Google Sheets")
    except Exception as e:
        log_error(f"Ошибка при записи в Google Sheets: {e}")
        # Продолжаем выполнение, даже если Google Sheets недоступен

    await progress_msg.edit_text(f"🟢 ТРАНСФЕР ВЫПОЛНЕН!\n\nПодтверждена выплата {order_count} ордеров на сумму {fmt_0(total_idr)} IDR", parse_mode="HTML")

@router.message(Command("rate_change"))
async def cmd_rate_change(message: Message, state: FSMContext):
    """🟡 Команда rate_change"""
    user_id = message.from_user.id
    if not await is_admin_or_superadmin(user_id):
        await message.reply("🚫 Команда доступна только администраторам и супер-админам.")
        return
    
    await state.set_state(RateChangeStates.waiting_for_new_rate)
    await message.reply(
        "💱 <b>Изменение курса обмена</b>\n\n"
        "Введите новый основной курс (RUB/IDR):\n"
        "Например: <code>0.0045</code>\n\n"
        "Или отправьте <code>/cancel</code> для отмены.",
        parse_mode="HTML"
    )

@router.message(RateChangeStates.waiting_for_new_rate)
async def rate_change_input(message: Message, state: FSMContext):
    """🟩 ввод нового курса /rate_change/"""
    if message.text.lower() == '/cancel':
        await state.clear()
        await message.reply("❌ Изменение курса отменено.")
        return
    
    try:
        new_rate = float(message.text.replace(',', '.'))
        if new_rate <= 0:
            raise ValueError("Курс должен быть положительным")
    except ValueError:
        await message.reply(
            "❌ <b>Некорректный формат курса!</b>\n\n"
            "Используйте число с точкой или запятой.\n"
            "Например: <code>0.0045</code>\n\n"
            "Или отправьте <code>/cancel</code> для отмены.",
            parse_mode="HTML"
        )
        return
    
    # Получаем текущие коэффициенты
    coefs = await db.get_rate_coefficients()
    if not coefs:
        await message.reply("❌ Ошибка: не удалось получить коэффициенты курса.")
        return
    main_coef = float(coefs['main_rate']) if 'main_rate' in coefs and coefs['main_rate'] is not None else 1
    rate1 = new_rate * float(coefs['rate1']) / main_coef if 'rate1' in coefs and coefs['rate1'] is not None else 0
    rate2 = new_rate * float(coefs['rate2']) / main_coef if 'rate2' in coefs and coefs['rate2'] is not None else 0
    rate3 = new_rate * float(coefs['rate3']) / main_coef if 'rate3' in coefs and coefs['rate3'] is not None else 0
    rate4 = new_rate * float(coefs['rate4']) / main_coef if 'rate4' in coefs and coefs['rate4'] is not None else 0
    rate_back = new_rate * float(coefs['rate_back']) / main_coef if 'rate_back' in coefs and coefs['rate_back'] is not None else 0
    
    # Получаем текущий курс
    old_rate_row = await db.get_actual_rate()
    old_rate = old_rate_row['main_rate'] if old_rate_row and 'main_rate' in old_rate_row and old_rate_row['main_rate'] is not None else 0
    
    # Сохраняем в состояние
    await state.update_data(new_rate=new_rate)
    
    # Формируем сообщение подтверждения
    response = (
        f"💱 <b>Подтверждение изменения курса</b>\n\n"
        f"<b>Текущий курс:</b> {fmt_2(old_rate)} RUB/IDR\n"
        f"<b>Новый курс:</b> {fmt_2(new_rate)} RUB/IDR\n\n"
        f"<b>Новые курсы по зонам:</b>\n"
        f"• Зона 1: {fmt_2(rate1)} RUB/IDR {fmt_delta(float(coefs['rate1']))}\n"
        f"• Зона 2: {fmt_2(rate2)} RUB/IDR {fmt_delta(float(coefs['rate2']))}\n"
        f"• Зона 3: {fmt_2(rate3)} RUB/IDR {fmt_delta(float(coefs['rate3']))}\n"
        f"• Зона 4: {fmt_2(rate4)} RUB/IDR {fmt_delta(float(coefs['rate4']))}\n"
        f"• Возврат: {fmt_2(rate_back)} RUB/IDR {fmt_delta(float(coefs['rate_back']))}\n\n"
        f"Подтвердите изменение курса:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить", callback_data="rate_change_confirm")],
        [InlineKeyboardButton(text="Отмена", callback_data="rate_change_cancel")]
    ])
    
    await message.reply(response, reply_markup=keyboard, parse_mode="HTML")

@router.message(Command("rate_zone_change"))
async def cmd_rate_zone_change(message: Message):
    """🟡 Команда rate_zone_change (в разработке)"""
    await cmd_in_development(message, "/rate_zone_change", "Изменение зон (интервалов) обмена")

@router.message(Command("rate_coef_change"))
async def cmd_rate_coef_change(message: Message):
    """🟡 Команда rate_coef_change (в разработке)"""
    await cmd_in_development(message, "/rate_coef_change", "Изменение коэффициентов курсов")

@router.message(Command("worktime"))
async def cmd_worktime(message: Message, state: FSMContext):
    """Обработчик команды /worktime для изменения рабочего времени"""
    user = message.from_user
    chat_id = message.chat.id
    
    logger.info(f"[WORKTIME] Команда /worktime вызвана пользователем {user.id} (@{user.username}) в чате {chat_id}")
    
    # Проверяем права (только суперадмин)
    if not await is_superadmin(user.id):
        logger.warning(f"[WORKTIME] Отказ в доступе для пользователя {user.id} - недостаточно прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только суперадмину.")
        return
    
    logger.info(f"[WORKTIME] Права доступа подтверждены для пользователя {user.id}")
    
    # Устанавливаем состояние ожидания времени
    await state.set_state(ShiftTimeStates.waiting_for_time)
    
    response = (
        "⏰ <b>Изменение рабочего времени смены</b>\n\n"
        "Отправьте новое время в формате:\n"
        "<code>HH:MM-HH:MM</code>\n\n"
        "Например:\n"
        "<code>09:00-22:30</code>\n\n"
        "Или отправьте <code>/cancel</code> для отмены."
    )
    
    await message.reply(response, parse_mode="HTML")
    logger.info(f"[WORKTIME] Запрошено ввод нового времени от пользователя {user.id}")

@router.message(ShiftTimeStates.waiting_for_time)
async def process_shift_time(message: Message, state: FSMContext):
    """Обработка введенного времени смены"""
    user = message.from_user
    chat_id = message.chat.id
    time_text = message.text.strip()
    
    logger.info(f"[WORKTIME] Получено время от пользователя {user.id}: {time_text}")
    
    if time_text.lower() == '/cancel':
        await state.clear()
        await message.reply("❌ Изменение времени отменено.")
        logger.info(f"[WORKTIME] Изменение времени отменено пользователем {user.id}")
        return
    
    # Проверяем формат времени
    try:
        if '-' not in time_text:
            raise ValueError("Отсутствует разделитель '-'")
        
        start_time, end_time = time_text.split('-')
        start_hour, start_minute = map(int, start_time.split(':'))
        end_hour, end_minute = map(int, end_time.split(':'))
        
        if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59 and 
                0 <= end_hour <= 23 and 0 <= end_minute <= 59):
            raise ValueError("Некорректные значения времени")
        
        # Сохраняем в базу данных
        await db.set_system_setting("shift_start_time", start_time)
        await db.set_system_setting("shift_end_time", end_time)
        
        # Обновляем в памяти
        from config import system_settings
        system_settings.shift_start_time = start_time
        system_settings.shift_end_time = end_time
        
        response = (
            f"✅ <b>Время смены успешно изменено!</b>\n\n"
            f"🕐 Новое время: <code>{start_time} - {end_time}</code>\n\n"
            f"Изменения применены и сохранены в базе данных."
        )
        
        await message.reply(response, parse_mode="HTML")
        logger.info(f"[WORKTIME] Время смены изменено на {start_time}-{end_time} пользователем {user.id}")
        
    except (ValueError, IndexError) as e:
        logger.warning(f"[WORKTIME] Некорректный формат времени от пользователя {user.id}: {time_text}")
        await message.reply(
            "❌ <b>Некорректный формат времени!</b>\n\n"
            "Используйте формат: <code>HH:MM-HH:MM</code>\n"
            "Например: <code>09:00-22:30</code>\n\n"
            "Или отправьте <code>/cancel</code> для отмены.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[WORKTIME] Ошибка при сохранении времени: {e}")
        await message.reply("❌ Произошла ошибка при сохранении времени. Попробуйте позже.")
    
    # Сбрасываем состояние
    await state.clear()

@router.message(Command("work_open"))
async def cmd_work_open(message: Message):
    """Принудительно открыть смену"""
    user = message.from_user
    chat_id = message.chat.id
    
    logger.info(f"[WORK_OPEN] Команда /work_open вызвана пользователем {user.id} (@{user.username}) в чате {chat_id}")
    
    # Проверяем права (только суперадмин)
    if not await is_superadmin(user.id):
        logger.warning(f"[WORK_OPEN] Отказ в доступе для пользователя {user.id} - недостаточно прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только суперадмину.")
        return
    
    logger.info(f"[WORK_OPEN] Права доступа подтверждены для пользователя {user.id}")
    
    # Создаем кнопки подтверждения
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, открыть смену", callback_data="force_open_yes"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="force_open_no")
        ]
    ])
    
    response = (
        "⚠️ <b>Принудительное открытие смены</b>\n\n"
        "Вы уверены, что хотите принудительно открыть смену?\n"
        "Это действие нельзя отменить."
    )
    
    await message.reply(response, parse_mode="HTML", reply_markup=keyboard)
    logger.info(f"[WORK_OPEN] Запрошено подтверждение открытия смены от пользователя {user.id}")

@router.message(Command("work_close"))
async def cmd_work_close(message: Message):
    """Принудительно закрыть смену"""
    user = message.from_user
    chat_id = message.chat.id
    
    logger.info(f"[WORK_CLOSE] Команда /work_close вызвана пользователем {user.id} (@{user.username}) в чате {chat_id}")
    
    # Проверяем права (только суперадмин)
    if not await is_superadmin(user.id):
        logger.warning(f"[WORK_CLOSE] Отказ в доступе для пользователя {user.id} - недостаточно прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только суперадмину.")
        return
    
    logger.info(f"[WORK_CLOSE] Права доступа подтверждены для пользователя {user.id}")
    
    # Создаем кнопки подтверждения
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, закрыть смену", callback_data="force_close_yes"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="force_close_no")
        ]
    ])
    
    response = (
        "⚠️ <b>Принудительное закрытие смены</b>\n\n"
        "Вы уверены, что хотите принудительно закрыть смену?\n"
        "Это действие нельзя отменить."
    )
    
    await message.reply(response, parse_mode="HTML", reply_markup=keyboard)
    logger.info(f"[WORK_CLOSE] Запрошено подтверждение закрытия смены от пользователя {user.id}")

@router.message(Command("reset_control"))
async def cmd_reset_control(message: Message):
    """Сбросить счетчик контроля для текущего чата"""
    user = message.from_user
    chat_id = message.chat.id
    
    logger.info(f"[RESET_CONTROL] Команда /reset_control вызвана пользователем {user.id} (@{user.username}) в чате {chat_id}")
    
    # Проверяем права (только суперадмин)
    if not await is_superadmin(user.id):
        logger.warning(f"[RESET_CONTROL] Отказ в доступе для пользователя {user.id} - недостаточно прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только суперадмину.")
        return
    
    logger.info(f"[RESET_CONTROL] Права доступа подтверждены для пользователя {user.id}")
    
    try:
        # Сбрасываем счетчик контроля
        await db.set_control_counter(chat_id, 0)
        
        response = f"✅ <b>Счетчик контроля сброшен!</b>\n\nСчетчик контроля для чата {chat_id} установлен в 0."
        await message.reply(response, parse_mode="HTML")
        logger.info(f"[RESET_CONTROL] Счетчик контроля сброшен для чата {chat_id} пользователем {user.id}")
        
    except Exception as e:
        logger.error(f"[RESET_CONTROL] Ошибка при сбросе счетчика: {e}")
        await message.reply("❌ Произошла ошибка при сбросе счетчика контроля.")

@router.message(Command("check_control"))
async def cmd_check_control(message: Message):
    """Показать количество запросов на контроле"""
    user = message.from_user
    chat_id = message.chat.id
    
    logger.info(f"[CHECK_CONTROL] Команда /check_control вызвана пользователем {user.id} (@{user.username}) в чате {chat_id}")
    
    # Проверяем права (операторы и выше)
    if not await is_operator_or_admin(user.id):
        logger.warning(f"[CHECK_CONTROL] Отказ в доступе для пользователя {user.id} - недостаточно прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только операторам, администраторам и суперадминам.")
        return
    
    logger.info(f"[CHECK_CONTROL] Права доступа подтверждены для пользователя {user.id}")
    
    try:
        # Получаем счетчик контроля
        counter = await db.get_control_counter(chat_id)
        
        response = (
            f"📊 <b>Отчет по контролю</b>\n\n"
            f"🔄 <b>Заявок на контроле в этом чате:</b> {counter}\n\n"
            f"Используйте <code>/reset_control</code> для сброса счетчика (только суперадмин)."
        )
        
        await message.reply(response, parse_mode="HTML")
        logger.info(f"[CHECK_CONTROL] Показан счетчик контроля {counter} для чата {chat_id} пользователю {user.id}")
        
    except Exception as e:
        logger.error(f"[CHECK_CONTROL] Ошибка при получении счетчика: {e}")
        await message.reply("❌ Произошла ошибка при получении данных о контроле.")

@router.message(Command("status"))
async def cmd_status(message: Message):
    """Показать открытые заявки в текущем чате"""
    user = message.from_user
    chat_id = message.chat.id
    
    logger.info(f"[STATUS] Команда /status вызвана пользователем {user.id} (@{user.username}) в чате {chat_id}")
    
    # Проверяем права (операторы и выше)
    if not await is_operator_or_admin(user.id):
        logger.warning(f"[STATUS] Отказ в доступе для пользователя {user.id} - недостаточно прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только операторам, администраторам и суперадминам.")
        return
    
    logger.info(f"[STATUS] Права доступа подтверждены для пользователя {user.id}")
    
    try:
        logger.info(f"[STATUS] Начинаем получение данных из БД для чата {chat_id}")
        
        # Проверяем подключение к БД
        if not db.pool:
            logger.error("[STATUS] ОШИБКА: db.pool равен None - база данных не подключена!")
            await message.reply("❌ Ошибка подключения к базе данных. Обратитесь к администратору.")
            return
        
        logger.info(f"[STATUS] Подключение к БД подтверждено, выполняем запрос...")
        
        # Получаем открытые заявки
        if not db.pool:
            await message.reply("Ошибка: база данных недоступна.")
            return
        async with db.pool.acquire() as conn:
            created_rows = await conn.fetch('''
                SELECT transaction_number, rub_amount, idr_amount
                FROM "VSEPExchanger"."transactions"
                WHERE source_chat = $1 AND status = 'created'
                ORDER BY status_changed_at
            ''', str(chat_id))
            
            accept_rows = await conn.fetch('''
                SELECT transaction_number, rub_amount, idr_amount
                FROM "VSEPExchanger"."transactions"
                WHERE source_chat = $1 AND status = 'accept'
                ORDER BY status_changed_at
            ''', str(chat_id))
            
            bill_rows = await conn.fetch('''
                SELECT transaction_number, rub_amount, idr_amount
                FROM "VSEPExchanger"."transactions"
                WHERE source_chat = $1 AND status = 'bill'
                ORDER BY status_changed_at
            ''', str(chat_id))

        if not created_rows and not accept_rows and not bill_rows:
            logger.info(f"[STATUS] В чате {chat_id} нет открытых заявок")
            await message.reply("📊 <b>Открытые заявки</b>\n\nВ этом чате нет открытых заявок.")
            return
        
        logger.info(f"[STATUS] Начинаем формирование отчета для {len(created_rows)} заявок...")
        
        # Формируем таблицу
        col1 = 15
        col2 = 12
        col3 = 12
        header = '<b>🟡 Открытые заявки на данный момент:</b>\n'
        header += f"<code>{'Номер заявки'.ljust(col1)}{'RUB'.rjust(col2)}{'IDR'.rjust(col3)}</code>\n"
        header += f"<code>{'-' * (col1 + col2 + col3)}</code>\n"
        
        lines = []
        total_rub = 0
        total_idr = 0
        
        for row in created_rows:
            num = str(row['transaction_number'])
            rub = int(row['rub_amount']) if row['rub_amount'] else 0
            idr = int(row['idr_amount']) if row['idr_amount'] else 0
            lines.append(f"<code>{num.ljust(col1)}{fmt_0(rub).rjust(col2)}{fmt_0(idr).rjust(col3)}</code>")
            total_rub += rub
            total_idr += idr
        
        for row in accept_rows:
            num = str(row['transaction_number'])
            rub = int(row['rub_amount']) if row['rub_amount'] else 0
            idr = int(row['idr_amount']) if row['idr_amount'] else 0
            lines.append(f"<code>{num.ljust(col1)}{fmt_0(rub).rjust(col2)}{fmt_0(idr).rjust(col3)}</code>")
            total_rub += rub
            total_idr += idr
        
        for row in bill_rows:
            num = str(row['transaction_number'])
            rub = int(row['rub_amount']) if row['rub_amount'] else 0
            idr = int(row['idr_amount']) if row['idr_amount'] else 0
            lines.append(f"<code>{num.ljust(col1)}{fmt_0(rub).rjust(col2)}{fmt_0(idr).rjust(col3)}</code>")
            total_rub += rub
            total_idr += idr
        
        table = header + '\n'.join(lines)
        table += f"\n<code>{'-'*(col1+col2+col3)}</code>"
        table += f"\n<code>Итого: {len(created_rows) + len(accept_rows) + len(bill_rows):<5}{fmt_0(total_rub).rjust(col2)}{fmt_0(total_idr).rjust(col3)}</code>"
        
        await message.reply(table, parse_mode="HTML")
        logger.info(f"[STATUS] Отчет отправлен: {len(created_rows) + len(accept_rows) + len(bill_rows)} заявок, RUB={total_rub}, IDR={total_idr}")
        
    except Exception as e:
        logger.error(f"[STATUS] Ошибка при формировании отчета: {e}")
        logger.error(f"[STATUS] Traceback: {traceback.format_exc()}")
        await message.reply("❌ Произошла ошибка при формировании отчета.")

@router.message(Command("restart"))
async def cmd_restart(message: Message):
    """🔄 Команда restart - перезапуск бота"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    logger.info(f"[RESTART] Команда /restart вызвана пользователем {user_id} в чате {chat_id}")
    
    # Проверяем права (только суперадмин)
    if not await is_superadmin(user_id):
        logger.warning(f"[RESTART] Отказ в доступе для пользователя {user_id} - недостаточно прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только суперадмину.")
        return
    
    logger.info(f"[RESTART] Права доступа подтверждены для пользователя {user_id}")
    
    try:
        await message.reply("🔄 Перезапуск бота...")
        logger.info(f"[RESTART] Бот перезапускается по команде пользователя {user_id}")
        
        # Здесь можно добавить логику перезапуска
        # Например, отправить сигнал в основной процесс
        
    except Exception as e:
        logger.error(f"[RESTART] Ошибка при перезапуске: {e}")
        await message.reply("❌ Произошла ошибка при перезапуске.")

@router.message(Command("control"))
async def cmd_control(message: Message, state: FSMContext = None):
    """🟡 Команда control - запрос контроля оплаты"""
    log_user(f"Получена команда /control от пользователя {message.from_user.id} в чате {message.chat.id}")
    log_func(f"Начало обработки команды /control: {message.text or message.caption}")
    
    # Проверяем наличие вложения
    has_attachment = bool(message.photo or message.document or message.video or message.animation)
    is_reply = bool(message.reply_to_message)
    reply_has_attachment = is_reply and bool(
        message.reply_to_message.photo or 
        message.reply_to_message.document or 
        message.reply_to_message.video
    )
    
    if not (has_attachment or reply_has_attachment):
        log_func(f"Команда /control использована без вложения")
        await message.reply("🚫 НЕ ВЫПОЛНЕНО!\n\nПРИЧИНА: команда /control должна быть с фото или документом или отправлена в ответ на сообщение с фото или документом.\n\nИСПОЛЬЗОВАНИЕ:\n/control [примечание] - с вложением\n/control [примечание] - в ответ на сообщение с вложением")
        return
    
    # Используем текст или подпись
    command_text = message.text or message.caption
    if not command_text:
        log_func(f"Команда /control использована без текста и подписи")
        await message.reply("🚫 НЕ ВЫПОЛНЕНО!\n\nПРИЧИНА: команда /control должна быть с фото или документом или отправлена в ответ на сообщение с фото или документом.\n\nИСПОЛЬЗОВАНИЕ:\n/control [примечание] - с вложением\n/control [примечание] - в ответ на сообщение с вложением")
        return
    
    args = command_text.strip().split()
    chat = message.chat
    chat_title = chat.title or chat.full_name or str(chat.id)
    
    if len(args) >= 2:
        # Команда с примечанием (любым текстом после /control)
        crm_number = " ".join(args[1:])
        log_func(f"/control с примечанием: {crm_number}")
    else:
        # Без примечаний
        crm_number = "-"
        log_func(f"/control без примечаний: {command_text}")
    
    # Получаем все заявки со статусом "создана" для этого чата
    if not db.pool:
        await message.reply("❌ Ошибка: база данных недоступна.")
        return
    
    # Делаем недействительными старые сообщения с кнопками control в этом чате
    try:
        # Получаем последние сообщения бота в чате и делаем недействительными те, что содержат кнопки control
        async for msg in message.bot.get_chat_history(chat_id=message.chat.id, limit=10):
            if (msg.from_user and msg.from_user.id == message.bot.id and 
                msg.reply_markup and any(btn.callback_data and btn.callback_data.startswith("control_") 
                                       for row in msg.reply_markup.inline_keyboard for btn in row)):
                try:
                    # Убираем кнопки и добавляем текст о незавершенной команде
                    current_text = msg.text or msg.caption or ""
                    new_text = current_text + "\n\n** ℹ️ КОМАНДА КОНТРОЛЬ НЕ ЗАВЕРШЕНА МЕНЕДЖЕРОМ ℹ️ ВЫЗВАНА НОВАЯ КОМАНДА КОНТРОЛЬ**"
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=msg.message_id,
                        text=new_text,
                        reply_markup=None  # Убираем все кнопки
                    )
                    log_func(f"Сделано недействительным старое сообщение с кнопками control: {msg.message_id}")
                except Exception as e:
                    log_func(f"Не удалось сделать недействительным старое сообщение {msg.message_id}: {e}")
    except Exception as e:
        log_func(f"Ошибка при обработке старых сообщений: {e}")
    
    async with db.pool.acquire() as conn:
        created_orders = await conn.fetch('''
            SELECT transaction_number, rub_amount, idr_amount
            FROM "VSEPExchanger"."transactions"
            WHERE source_chat = $1 AND status = 'created'
            ORDER BY status_changed_at
        ''', str(chat.id))
    
    if not created_orders:
        text = f'''❌ Нет активных заявок для контроля. Сначала создайте заявку.

☢️ <b><i>'то, чего никогда не было и вот опять'</i></b>
Если случился такой удивительный случай:пришла оплата по заявке из прошлой смены - обратитесь к оператору Сервиса (можете даже командой /sos) для попытки реанимировать заявку (предварительно найдите номер заявки в бланке расчёта с прошлой смены)
        '''
        await message.reply(text)
        return
    
    # Создаем кнопки для каждой заявки
    keyboard_buttons = []
    for order in created_orders:
        transaction_number = order['transaction_number']
        rub_amount = int(order['rub_amount']) if order['rub_amount'] else 0
        idr_amount = int(order['idr_amount']) if order['idr_amount'] else 0
        
        # Форматируем суммы для отображения
        rub_formatted = f"{rub_amount:,}".replace(",", " ")
        idr_formatted = f"{idr_amount:,}".replace(",", " ")
        
        button_text = f"💰 {rub_formatted} RUB | {idr_formatted} IDR | #{transaction_number}"
        callback_data = f"control_order_{transaction_number}"
        
        keyboard_buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    # Добавляем кнопку отмены
    keyboard_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="control_cancel")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    base_text = (
        f"🟡 Выберите заявку для контроля:\n\n"
        f"📝 Примечание: {crm_number}\n\n"
        f"Нажмите на кнопку с заявкой, соответствующей вашему чеку:")
    await state.set_state(ControlStates.waiting_for_order_selection)
    await state.update_data(crm_number=crm_number, original_message_id=message.message_id, owner_id=message.from_user.id, base_text=base_text)
    
    msg = await message.reply(
        base_text,
        reply_markup=keyboard
    )
    log_func("Отправлено сообщение с кнопками выбора заявки")
    
    # Если есть старое сообщение — обновляем его и убираем из dict
    old_msg_id = active_control_message[message.chat.id]
    if old_msg_id and old_msg_id != msg.message_id:
        try:
            old_msg = await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=old_msg_id,
                text=base_text + "\n\n** ℹ️ КОМАНДА КОНТРОЛЬ НЕ ЗАВЕРШЕНА МЕНЕДЖЕРОМ ℹ️ ВЫЗВАНА НОВАЯ КОМАНДА КОНТРОЛЬ**",
                reply_markup=None
            )
            log_func(f"Сделано недействительным старое сообщение с кнопками control: {old_msg_id}")
        except Exception as e:
            log_func(f"Не удалось сделать недействительным старое сообщение {old_msg_id}: {e}")

    # Записываем новый message_id
    active_control_message[message.chat.id] = msg.message_id
    
    # Запускаем задачу для автоматического устаревания кнопок через 1 минуту
    task = asyncio.create_task(expire_control_buttons(message.bot, message.chat.id, message.message_id + 1, 60, base_text=base_text))  # +1 потому что reply
    
    # Сохраняем задачу в состоянии для возможности отмены
    await state.update_data(expire_task=task)

@router.message(Command("report"))
async def cmd_report(message: Message):
    """🟡 Команда report - отчет по всем группам запросов"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    log_user(f"Получена команда /report от пользователя {user_id} в чате {chat_id}")
    log_func(f"Начало обработки команды /report")

    # Получаем все ордера для этого чата с разными статусами
    if not db.pool:
        await message.reply("Ошибка: база данных недоступна.")
        return
    async with db.pool.acquire() as conn:
        created_rows = await conn.fetch('''
            SELECT transaction_number, rub_amount, idr_amount
            FROM "VSEPExchanger"."transactions"
            WHERE source_chat = $1 AND status = 'created'
            ORDER BY status_changed_at
        ''', str(chat_id))
        
        accept_rows = await conn.fetch('''
            SELECT transaction_number, rub_amount, idr_amount
            FROM "VSEPExchanger"."transactions"
            WHERE source_chat = $1 AND status = 'accept'
            ORDER BY status_changed_at
        ''', str(chat_id))
        
        bill_rows = await conn.fetch('''
            SELECT transaction_number, rub_amount, idr_amount
            FROM "VSEPExchanger"."transactions"
            WHERE source_chat = $1 AND status = 'bill'
            ORDER BY status_changed_at
        ''', str(chat_id))

    col1 = 15
    col2 = 12
    col3 = 12
    # Время
    times = get_bali_and_msk_time_list()
    dt_line = f"REPORT from🕒 {times[6]} (Bali) / {times[5]} (MSK)"
    
    # Формируем отчет
    report_parts = []
    
    # 1. Ордера со статусом created
    header = f"<b>📋 CREATED</b>\n"
    header += f"Все имеющиеся заявки с не подтвержденными транзакциями (активные по таймауту):\n"
    header += f"<blockquote expandable><code>{'Номер ордера'.ljust(col1)}{'RUB'.rjust(col2)}{'IDR'.rjust(col3)}</code>\n"
    header += f"<code>{'-' * (col1 + col2 + col3)}</code>\n"
    header += f"<code>Всего ордеров: {len(created_rows):<5}</code>\n"
    
    if created_rows:
        lines = []
        total_rub = 0
        total_idr = 0
        for row in created_rows:
            num = str(row['transaction_number'])
            rub = int(row['rub_amount']) if row['rub_amount'] else 0
            idr = int(row['idr_amount']) if row['idr_amount'] else 0
            lines.append(f"<code>{num.ljust(col1)}</code><code>{fmt_0(rub).rjust(col2)}{fmt_0(idr).rjust(col3)}</code>")
            total_rub += rub
            total_idr += idr
        table = header + '\n'.join(lines)
        table += f"\n<code>{'-'*(col1+col2+col3)}</code>"
        table += f"\n<code>ордеров: {len(created_rows):<5}{fmt_0(total_rub).rjust(col2)}{fmt_0(total_idr).rjust(col3)}</code></blockquote>"
    else:
        table = header + f"\n<code>{'Нет ордеров'.center(col1+col2+col3)}</code></blockquote>"
    report_parts.append(table)

    # 2. Ордера со статусом accept
    header = f"<b>💰 ACCEPT</b>\n"
    header += f"Ордера с подтвержденными транзакциями\n"
    header += f"(еще <u>не внесенные в счет на выплату</u>):\n"
    header += f"<blockquote expandable><code>{'Номер ордера'.ljust(col1)}{'RUB'.rjust(col2)}{'IDR'.rjust(col3)}</code>\n"
    header += f"<code>{'-' * (col1 + col2 + col3)}</code>\n"
    header += f"<code>Всего ордеров: {len(accept_rows):<5}</code>\n"
    
    if accept_rows:
        lines = []
        total_rub = 0
        total_idr = 0
        for row in accept_rows:
            num = str(row['transaction_number'])
            rub = int(row['rub_amount']) if row['rub_amount'] else 0
            idr = int(row['idr_amount']) if row['idr_amount'] else 0
            lines.append(f"<code>{num.ljust(col1)}</code><code>{fmt_0(rub).rjust(col2)}{fmt_0(idr).rjust(col3)}</code>")
            total_rub += rub
            total_idr += idr
        table = header + '\n'.join(lines)
        table += f"\n<code>{'-'*(col1+col2+col3)}</code>"
        table += f"\n<code>ордеров: {len(accept_rows):<5}{fmt_0(total_rub).rjust(col2)}{fmt_0(total_idr).rjust(col3)}</code></blockquote>"
    else:
        table = header + f"\n<code>{'Нет ордеров'.center(col1+col2+col3)}</code></blockquote>"
    report_parts.append(table)

    # 3. Ордера со статусом bill
    header = f"<b>♻️ BILL</b>\n"
    header += f"Ордера с подтвержденными транзакциями,\nожидающие зачисления Партнёру\n"
    header += f"(<u>внесенные в счет на выплату</u>):\n"
    header += f"<blockquote expandable><code>{'Номер ордера'.ljust(col1)}{'RUB'.rjust(col2)}{'IDR'.rjust(col3)}</code>\n"
    header += f"<code>{'-' * (col1 + col2 + col3)}</code>\n"
    header += f"<code>Всего ордеров: {len(bill_rows):<5}</code>\n"
    
    if bill_rows:
        lines = []
        total_rub = 0
        total_idr = 0
        for row in bill_rows:
            num = str(row['transaction_number'])
            rub = int(row['rub_amount']) if row['rub_amount'] else 0
            idr = int(row['idr_amount']) if row['idr_amount'] else 0
            lines.append(f"<code>{num.ljust(col1)}</code><code>{fmt_0(rub).rjust(col2)}{fmt_0(idr).rjust(col3)}</code>")
            total_rub += rub
            total_idr += idr
        table = header + '\n'.join(lines)
        table += f"\n<code>{'-'*(col1+col2+col3)}</code>"
        table += f"\n<code>ордеров: {len(bill_rows):<5}{fmt_0(total_rub).rjust(col2)}{fmt_0(total_idr).rjust(col3)}</code></blockquote>"
    else:
        table = header + f"\n<code>{'Нет ордеров'.center(col1+col2+col3)}</code></blockquote>"
    report_parts.append(table)

    # Собираем финальный отчет
    final_report = dt_line + '\n\n' + '\n\n'.join(report_parts)
    final_report += f'''<i>>>> Для просмотра подробной информации об ордере введите команду /order_show 《номер_ордера》
>>> Для формирования счета к выплате и получения реквизитов нажмите кнопку 《Сформировать счет》
<u>В счет вносятся все ордера из категории `ACCEPT` и `BILL`</u></i>'''

    # Создаем кнопки только для администраторов
    reply_markup = None
    if await is_admin_or_superadmin(user_id):
        # Проверяем, есть ли ордера со статусом accept для формирования счета
        if accept_rows:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Сформировать счет", 
                        callback_data=f"report_bill_{user_id}"
                    ),
                    InlineKeyboardButton(
                        text="Отмена", 
                        callback_data=f"report_cancel_{user_id}"
                    )
                ]
            ])
            reply_markup = keyboard

    # Отправляем отчет
    await message.reply(final_report, parse_mode="HTML", reply_markup=reply_markup)

@router.message(Command("report_vsep"))
async def cmd_report_vsep(message: Message, state: FSMContext):
    # Проверка: только для админа/суперадмина и только в чате админов
    if str(message.chat.id) != str(config.ADMIN_GROUP):
        await message.reply("⛔️ Команда доступна только в чате админов.")
        return
    if not await is_admin_or_superadmin(message.from_user.id):
        await message.reply("⛔️ Команда доступна только для админа и суперадмина.")
        return
    
    # Создаем календарь для выбора месяца/года
    calendar = MonthYearCalendar()
    current_year = datetime.now().year
    keyboard = calendar.create_month_year_keyboard(current_year)
    
    await state.set_state(VsepReportStates.waiting_for_month)
    await message.reply(
        "📅 Выберите месяц и год для отчёта:",
        reply_markup=keyboard
    )

@router.message(VsepReportStates.waiting_for_month)
async def report_vsep_month_input(message: Message, state: FSMContext):
    if str(message.chat.id) != str(config.ADMIN_GROUP):
        await message.reply("⛔️ Команда доступна только в чате админов.")
        await state.clear()
        return
    if not await is_admin_or_superadmin(message.from_user.id):
        await message.reply("⛔️ Команда доступна только для админа и суперадмина.")
        await state.clear()
        return
    month = message.text.strip()
    await state.update_data(selected_month=month)
    await state.set_state(VsepReportStates.waiting_for_rate)
    await message.reply(
        "💱 Введите курс IDR к USDT для пересчёта итогов (например: 16000)",
        parse_mode="HTML"
    )

@router.message(VsepReportStates.waiting_for_rate)
async def report_vsep_rate_input(message: Message, state: FSMContext):
    if str(message.chat.id) != str(config.ADMIN_GROUP):
        await message.reply("⛔️ Команда доступна только в чате админов.")
        await state.clear()
        return
    if not await is_admin_or_superadmin(message.from_user.id):
        await message.reply("⛔️ Команда доступна только для админа и суперадмина.")
        await state.clear()
        return
    rate_text = message.text.strip().replace(",", ".")
    try:
        rate = float(rate_text)
        if rate <= 0:
            raise ValueError
    except Exception:
        await message.reply("❗️ Введите корректный курс (например: 16000)")
        return
    data = await state.get_data()
    month = data.get("selected_month")
    await message.reply(f"⏳ Формирую отчёт за <b>{month}</b> по курсу <b>{rate}</b>...", parse_mode="HTML")
    try:
        report_data = await asyncio.get_event_loop().run_in_executor(None, read_sum_all_report, month)
        print(f"[DEBUG] report_data: {report_data}")
        if not report_data:
            await message.reply(f"❌ Нет данных за {month} на листе SUM_ALL.")
            await state.clear()
            return
        # Формируем отчёт по проектам
        lines = []
        total_turnover = {}
        total_commission = {}
        import re
        def parse_num(val, currency):
            if not val:
                return 0.0
            # Сначала заменяем запятые на точки (для десятичных чисел)
            val = re.sub(r",", ".", str(val))
            # Затем удаляем все пробелы (включая неразрывные)
            val = re.sub(r"\s", "", val)
            if currency:
                val = val.replace(currency, "")
            try:
                return float(val)
            except Exception:
                # Пробуем найти любое число в строке
                m = re.search(r"([\d.]+)", val)
                return float(m.group(1)) if m else 0.0
        for row in report_data:
            name = row['project']
            count = row['count']
            turnover = row['turnover']
            commission = row['commission']
            percent = row['commission_percent']
            currency = row['currency']
            comm_currency = row['commission_currency']
            # Если валюта не найдена, определяем по названию проекта
            if not currency:
                if 'SAL' in name.upper():
                    currency = 'USDT'
                else:
                    currency = 'IDR'
            if not comm_currency:
                comm_currency = currency
            tval = parse_num(turnover, currency)
            cval = parse_num(commission, comm_currency)
            print(f"[DEBUG] {name}: оборот={tval} {currency}, комиссия={cval} {comm_currency}")
            total_turnover[currency] = total_turnover.get(currency, 0) + tval
            total_commission[comm_currency] = total_commission.get(comm_currency, 0) + cval
            # Формат блока по проекту
            lines.append(f"<b>{name}</b>\nКол-во сделок: <b>{count}</b>\nОборот: <b>{turnover}</b>\nУчастие: <b>{commission}</b> (<code>{percent}</code>)\n")
        print(f"[DEBUG] total_turnover: {total_turnover}")
        print(f"[DEBUG] total_commission: {total_commission}")
        # Итоги по валютам
        lines.append("<b>Итог: Оборот</b>")
        for cur, val in total_turnover.items():
            # Форматируем в европейском стиле: пробелы как разделители тысяч, запятые как десятичные
            formatted = f"{val:,.2f}".replace(",", " ").replace(".", ",")
            lines.append(f"<b>{formatted} {cur}</b>")
        lines.append("\n<b>Итог: Участие</b>")
        for cur, val in total_commission.items():
            # Форматируем в европейском стиле: пробелы как разделители тысяч, запятые как десятичные
            formatted = f"{val:,.2f}".replace(",", " ").replace(".", ",")
            lines.append(f"<b>{formatted} {cur}</b>")
        # Пересчёт в USDT
        idr_total = total_turnover.get('IDR', 0)
        idr_comm = total_commission.get('IDR', 0)
        usdt_total = total_turnover.get('USDT', 0)
        usdt_comm = total_commission.get('USDT', 0)
        usdt_total_sum = usdt_total + (idr_total / rate if rate else 0)
        usdt_comm_sum = usdt_comm + (idr_comm / rate if rate else 0)
        lines.append(f"\n<b>Пересчёт по курсу {rate:,.2f}:</b>")
        # Форматируем в европейском стиле
        usdt_total_formatted = f"{usdt_total_sum:,.2f}".replace(",", " ").replace(".", ",")
        usdt_comm_formatted = f"{usdt_comm_sum:,.2f}".replace(",", " ").replace(".", ",")
        lines.append(f"Оборот в USDT: <b>{usdt_total_formatted}</b>")
        lines.append(f"Участие в USDT: <b>{usdt_comm_formatted}</b>")
        report_text = '\n'.join(lines)
        await message.reply(report_text, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка при формировании отчёта: {e}")
    await state.clear()

@router.callback_query(lambda c: c.data.startswith("use_bybit_rate_") or c.data == "enter_rate_manually")
async def report_vsep_bybit_rate_choice(call: CallbackQuery, state: FSMContext):
    if str(call.message.chat.id) != str(config.ADMIN_GROUP):
        await call.answer("⛔️ Команда доступна только в чате админов.", show_alert=True)
        await state.clear()
        return
    if not await is_admin_or_superadmin(call.from_user.id):
        await call.answer("⛔️ Команда доступна только для админа и суперадмина.", show_alert=True)
        await state.clear()
        return
    data = await state.get_data()
    month = data.get("selected_month")
    if call.data.startswith("use_bybit_rate_"):
        # Пользователь выбрал использовать курс Bybit
        rate = float(call.data.split("_")[-1])
        await call.message.edit_text(f"⏳ Формирую отчёт за <b>{month}</b> по курсу <b>{rate:,.2f}</b>...", parse_mode="HTML")
        # Дублируем логику из report_vsep_rate_input
        try:
            report_data = await asyncio.get_event_loop().run_in_executor(None, read_sum_all_report, month)
            print(f"[DEBUG] report_data: {report_data}")
            if not report_data:
                await call.message.reply(f"❌ Нет данных за {month} на листе SUM_ALL.")
                await state.clear()
                return
            # ... (оставить остальной код формирования отчёта без изменений)
            # --- КОПИРУЕМ БЛОК ФОРМИРОВАНИЯ ОТЧЁТА из report_vsep_rate_input ---
            lines = []
            total_turnover = {}
            total_commission = {}
            import re
            def parse_num(val, currency):
                if not val:
                    return 0.0
                val = re.sub(r",", ".", str(val))
                val = re.sub(r"\s", "", val)
                if currency:
                    val = val.replace(currency, "")
                try:
                    return float(val)
                except Exception:
                    m = re.search(r"([\d.]+)", val)
                    return float(m.group(1)) if m else 0.0
            for row in report_data:
                name = row['project']
                count = row['count']
                turnover = row['turnover']
                commission = row['commission']
                percent = row['commission_percent']
                currency = row['currency']
                comm_currency = row['commission_currency']
                if not currency:
                    if 'SAL' in name.upper():
                        currency = 'USDT'
                    else:
                        currency = 'IDR'
                if not comm_currency:
                    comm_currency = currency
                tval = parse_num(turnover, currency)
                cval = parse_num(commission, comm_currency)
                print(f"[DEBUG] {name}: оборот={tval} {currency}, комиссия={cval} {comm_currency}")
                total_turnover[currency] = total_turnover.get(currency, 0) + tval
                total_commission[comm_currency] = total_commission.get(comm_currency, 0) + cval
                lines.append(f"<b>{name}</b>\nКол-во сделок: <b>{count}</b>\nОборот: <b>{turnover}</b>\nУчастие: <b>{commission}</b> (<code>{percent}</code>)\n")
            print(f"[DEBUG] total_turnover: {total_turnover}")
            print(f"[DEBUG] total_commission: {total_commission}")
            lines.append("<b>Итог: Оборот</b>")
            for cur, val in total_turnover.items():
                formatted = f"{val:,.2f}".replace(",", " ").replace(".", ",")
                lines.append(f"<b>{formatted} {cur}</b>")
            lines.append("\n<b>Итог: Участие</b>")
            for cur, val in total_commission.items():
                formatted = f"{val:,.2f}".replace(",", " ").replace(".", ",")
                lines.append(f"<b>{formatted} {cur}</b>")
            idr_total = total_turnover.get('IDR', 0)
            idr_comm = total_commission.get('IDR', 0)
            usdt_total = total_turnover.get('USDT', 0)
            usdt_comm = total_commission.get('USDT', 0)
            usdt_total_sum = usdt_total + (idr_total / rate if rate else 0)
            usdt_comm_sum = usdt_comm + (idr_comm / rate if rate else 0)
            lines.append(f"\n<b>Пересчёт по курсу {rate:,.2f}:</b>")
            usdt_total_formatted = f"{usdt_total_sum:,.2f}".replace(",", " ").replace(".", ",")
            usdt_comm_formatted = f"{usdt_comm_sum:,.2f}".replace(",", " ").replace(".", ",")
            lines.append(f"Итог оборот в USDT: <b>{usdt_total_formatted}</b>")
            lines.append(f"Итог участие в USDT: <b>{usdt_comm_formatted}</b>")
            report_text = '\n'.join(lines)
            await call.message.reply(report_text, parse_mode="HTML")
        except Exception as e:
            await call.message.reply(f"❌ Ошибка при формировании отчёта: {e}")
        await state.clear()
    else:
        # Пользователь выбрал ввести курс вручную
        await call.message.edit_text(
            "💱 Введите курс IDR к USDT для пересчёта итогов (например: 16000)",
            parse_mode="HTML"
        )
        await state.set_state(VsepReportStates.waiting_for_rate)

def register_handlers(dp: Dispatcher):
    """Регистрация всех обработчиков"""
    print("[DEBUG] register_handlers: начало регистрации")
    
    # Сначала подключаем основной роутер
    print("[DEBUG] register_handlers: подключаю основной роутер")
    dp.include_router(router)
    print("[DEBUG] register_handlers: основной роутер подключен")
    
    # Затем подключаем роутер для банковских операций
    print("[DEBUG] register_handlers: подключаю банковский роутер")
    dp.include_router(bank_router)
    print("[DEBUG] register_handlers: банковский роутер подключен")
    
    # Подключаем роутер для команды accept
    print("[DEBUG] register_handlers: подключаю accept роутер")
    dp.include_router(accept_router)
    print("[DEBUG] register_handlers: accept роутер подключен")
    
    # Подключаем роутер для команды joke
    print("[DEBUG] register_handlers: подключаю joke роутер")
    dp.include_router(joke_router)
    print("[DEBUG] register_handlers: joke роутер подключен")
    
    # Подключаем роутер для команды dice
    print("[DEBUG] register_handlers: подключаю dice роутер")
    dp.include_router(dice_router)
    print("[DEBUG] register_handlers: dice роутер подключен")
    
    # Подключаем роутер для команды coin
    print("[DEBUG] register_handlers: подключаю coin роутер")
    dp.include_router(coin_router)
    print("[DEBUG] register_handlers: coin роутер подключен")
    
    # Подключаем роутер для команды meme
    print("[DEBUG] register_handlers: подключаю meme роутер")
    dp.include_router(meme_router)
    print("[DEBUG] register_handlers: meme роутер подключен")
    
    # Подключаем роутер для команды order_change
    print("[DEBUG] register_handlers: подключаю order_change роутер")
    dp.include_router(order_change_router)
    print("[DEBUG] register_handlers: order_change роутер подключен")
    
    # Регистрируем остальные callback обработчики напрямую в диспетчер
    dp.callback_query.register(force_open_callback, lambda c: c.data in ["force_open_yes", "force_open_no"])
    dp.callback_query.register(force_close_callback, lambda c: c.data in ["force_close_yes", "force_close_no"])
    dp.callback_query.register(admin_add_confirm_callback, F.data.startswith("admin_add_confirm:"))
    dp.callback_query.register(admin_add_cancel_callback, F.data.startswith("admin_add_cancel:"))
    dp.callback_query.register(admin_remove_confirm_callback, F.data.startswith("admin_remove_confirm:"))
    dp.callback_query.register(admin_remove_cancel_callback, F.data.startswith("admin_remove_cancel:"))
    dp.callback_query.register(operator_add_confirm_callback, F.data.startswith("operator_add_confirm:"))
    dp.callback_query.register(operator_add_cancel_callback, F.data.startswith("operator_add_cancel:"))
    dp.callback_query.register(operator_remove_confirm_callback, F.data.startswith("operator_remove_confirm:"))
    dp.callback_query.register(operator_remove_cancel_callback, F.data.startswith("operator_remove_cancel:"))
    dp.callback_query.register(rate_change_confirm, F.data=="rate_change_confirm")
    dp.callback_query.register(rate_change_cancel, F.data=="rate_change_cancel")
    dp.callback_query.register(report_callback_handler, F.data.regexp(r"^report_(bill|cancel)_"))
    dp.callback_query.register(control_callback_handler, F.data.startswith("control_"))
    dp.callback_query.register(zombie_callback_handler, F.data.startswith("zombie_"))
    
    # Регистрируем обработчик для ввода суммы
    dp.message.register(handle_input_sum, lambda m: m.text and m.text.strip().startswith("/") and (m.text[1:].isdigit() or (m.text[1:].startswith("-") and m.text[2:].isdigit())))
    
    print("[DEBUG] register_handlers: регистрация завершена")

async def _toggle_info_flag(message: Message, flag_name: str, chat_type: str):
    """(Superadmin) Включить/выключить информационное сообщение для чата."""
    user = message.from_user
    chat_id = message.chat.id

    logger.info(f"[{flag_name.upper()}] Команда /toggle_info_{chat_type.lower()} вызвана пользователем {user.id} (@{user.username}) в чате {chat_id}")

    # Проверяем права (только суперадмин)
    if not await is_superadmin(user.id):
        logger.warning(f"[{flag_name.upper()}] Отказ в доступе для пользователя {user.id} - недостаточно прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только суперадмину.")
        return

    logger.info(f"[{flag_name.upper()}] Права доступа подтверждены для пользователя {user.id}")

    try:
        # Используем специальный метод для переключения системной настройки
        new_state = await db.toggle_system_setting(flag_name)
        
        # Обновляем системные настройки в памяти
        await system_settings.load()
        
        status_text = "включен ✅" if new_state else "выключен ❌"
        response_text = f"Информационный скрипт для чата {chat_type} успешно {status_text}"
        
        await message.reply(response_text)
        logger.info(f"[{flag_name.upper()}] Статус изменен на {new_state} пользователем {user.id}")

    except Exception as e:
        logger.error(f"[{flag_name.upper()}] Ошибка при переключении флага: {e}")
        await message.reply("❌ Произошла ошибка при изменении настройки.")


@router.message(Command("toggle_info_mbt"))
async def cmd_toggle_info_mbt(message: Message):
    """(Superadmin) Включить/выключить информационное сообщение для MBT"""
    await _toggle_info_flag(message, "send_info_mbt", "MBT")

@router.message(Command("toggle_info_lgi"))
async def cmd_toggle_info_lgi(message: Message):
    """(Superadmin) Включить/выключить информационное сообщение для LGI"""
    await _toggle_info_flag(message, "send_info_lgi", "LGI")

@router.message(Command("toggle_info_tct"))
async def cmd_toggle_info_tct(message: Message):
    """(Superadmin) Включить/выключить информационное сообщение для TCT"""
    await _toggle_info_flag(message, "send_info_tct", "TCT")

async def expire_control_buttons(bot: Bot, chat_id: int, message_id: int, delay_seconds: int, base_text: str = ""):
    """Автоматическое устаревание кнопок control через указанное время"""
    await asyncio.sleep(delay_seconds)
    
    try:
        # Используем base_text если передан, иначе стандартный текст
        if not base_text:
            base_text = "🟡 Выберите заявку для контроля:\n\n📝 Примечание: ...\n\nНажмите на кнопку с заявкой, соответствующей вашему чеку:"
        base_text = str(base_text)
        new_text = base_text + "\n\n** ℹ️ КОМАНДА КОНТРОЛЬ НЕ ЗАВЕРШЕНА МЕНЕДЖЕРОМ ℹ️ СРОК ЖИЗНИ КНОПОК ЗАКОНЧИЛСЯ**"
        
        # Убираем кнопки и обновляем текст
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=new_text,
            reply_markup=None  # Убираем все кнопки
        )
        # Очищаем message_id
        active_control_message[chat_id] = None
        
        log_func(f"Кнопки control истекли для сообщения {message_id} в чате {chat_id}")
        
    except Exception as e:
        error_msg = str(e).lower()
        if "message to edit not found" in error_msg or "message not found" in error_msg:
            log_func(f"Сообщение {message_id} уже удалено или недоступно для редактирования")
        else:
            log_error(f"Ошибка при истечении кнопок control: {e}")

# === CALLBACK HANDLER для кнопки Принять ===
@router.callback_query(lambda c: c.data.startswith("accept_order_"))
async def accept_order_callback(call: CallbackQuery, state: FSMContext):
    transaction_number = call.data.split("_")[-1]
    user_id = call.from_user.id
    # Проверка прав
    user_rank = await db.get_user_rank(user_id)
    if user_rank not in ("operator", "admin", "superadmin"):
        await call.answer("Только оператор и админ Сервиса могут подтвердить!", show_alert=True)
        return
    # Получаем заявку
    transaction = await db.get_transaction_by_number(transaction_number)
    if not transaction:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    if transaction.get('status') != "control":
        await call.answer(f"Заявка не на контроле (статус: {transaction.get('status')})", show_alert=True)
        return
    # Обновляем статус и историю
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.update_transaction_status(transaction_number, "accept", now_utc)
    # Формируем запись в history
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    user_nick = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
    # Используем ID сообщения с кнопкой для ссылки в истории
    msg_id = call.message.message_id
    chat_id = call.message.chat.id
    if call.message.chat.username:
        link_accept = f"https://t.me/{call.message.chat.username}/{msg_id}"
    else:
        chat_id_num = str(chat_id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link_accept = f"https://t.me/c/{chat_id_num}/{msg_id}"
    accept_entry = f"{now_str}${user_nick}$accept${link_accept}"
    old_history = transaction.get('history', '')
    history = old_history + "%%%" + accept_entry if old_history else accept_entry
    await db.update_transaction_history(transaction_number, history)
    
    # --- Уменьшаем счетчик контроля ---
    counter = await db.get_control_counter(chat_id)
    if counter > 0:
        await db.set_control_counter(chat_id, counter - 1)
        from logger import log_func, log_db
        key = f"{chat_id}_control_counter"
        log_func(f"Счетчик контроля для чата {chat_id} (ключ: {key}) уменьшен: {counter} -> {counter-1}")
        log_db(f"[DB] set_system_setting: {key} = {counter-1}")
    
    # Удаляем кнопку и подписываем сообщение с активной ссылкой
    operator_name = call.from_user.full_name
    operator_username = f"@{call.from_user.username}" if call.from_user.username else ""
    operator_info = f"{operator_username}".strip()
    
    # Отправляем отдельное уведомление в чат о подтверждении платежа
    rub_amount = int(transaction['rub_amount']) if transaction['rub_amount'] else 0
    idr_amount = int(transaction['idr_amount']) if transaction['idr_amount'] else 0
    rub_formatted = f"{rub_amount:,}".replace(",", " ")
    idr_formatted = f"{idr_amount:,}".replace(",", " ")
    
    notification_text = (
        f"✅ **ТРАНЗАКЦИЯ ПОДТВЕРЖДЕНА!**\n\n"
        f"• Номер заявки: <code>{transaction_number}</code>\n"
        f"• Сумма: {rub_formatted} RUB | {idr_formatted} IDR\n"
        f"• Подтвердил: {operator_info}\n"
        f"• Время: {now_str}\n\n"
        f"🔵 Статус заявки: <b>ПОДТВЕРЖДЕНА</b>"
    )
    
    # Отправляем новое сообщение и сохраняем его ID
    notification_msg = await call.message.answer(notification_text, parse_mode="HTML")
    notification_msg_id = notification_msg.message_id
    
    # Формируем ссылку на новое сообщение
    if call.message.chat.username:
        link_to_notification = f"https://t.me/{call.message.chat.username}/{notification_msg_id}"
    else:
        chat_id_num = str(chat_id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link_to_notification = f"https://t.me/c/{chat_id_num}/{notification_msg_id}"
    
    # Создаем активную ссылку на новое сообщение
    active_link_text = f"✅ <a href=\"{link_to_notification}\">Заявка была акцептована</a>"
    
    new_text = call.message.text + f"\n\n{active_link_text}"
    await call.message.edit_text(new_text, reply_markup=None, parse_mode="HTML")
    await call.answer("Заявка акцептована!")

# === КОМАНДА РЕАНИМАЦИИ ЗАЯВОК ===
@router.message(Command("zombie"))
async def cmd_zombie(message: Message, state: FSMContext):
    """Команда реанимации заявок из статуса timeout в created"""
    args = message.text.split()
    
    # Проверка формата команды
    if len(args) < 2:
        await message.reply(
            "❌ Не выполнено.\n"
            "ПРИЧИНА: не указан номер заявки.\n\n"
            "📝 <b>Образец команды:</b>\n"
            "<code>/zombie 2506123456789</code>"
        )
        return
    
    transaction_number = args[1].strip()
    
    # Проверка прав доступа
    user_rank = await db.get_user_rank(message.from_user.id)
    if user_rank not in ("operator", "admin", "superadmin"):
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только оператору, админу и суперадмину.")
        return
    
    # Получаем заявку из базы
    transaction = await db.get_transaction_by_number(transaction_number)
    if not transaction:
        await message.reply(
            "❌ Не выполнено.\n"
            "ПРИЧИНА: заявка с таким номером не найдена."
        )
        return
    
    # Проверяем статус заявки
    if transaction.get('status') != "timeout":
        await message.reply(
            f"❌ Не выполнено.\n"
            f"ПРИЧИНА: текущий статус заявки <b>'{transaction.get('status')}'</b> не подходит для реанимации.\n"
            f"Реанимация возможна только для заявок со статусом <b>timeout</b>."
        )
        return
    
    # Форматируем данные заявки
    rub_amount = int(transaction['rub_amount']) if transaction['rub_amount'] else 0
    idr_amount = int(transaction['idr_amount']) if transaction['idr_amount'] else 0
    rub_formatted = f"{rub_amount:,}".replace(",", " ")
    idr_formatted = f"{idr_amount:,}".replace(",", " ")
    created_at = transaction.get('created_at')
    created_date = created_at.strftime("%d.%m.%Y") if created_at else "неизвестно"
    account_info = transaction.get('account_info', 'не указаны')
    
    # Формируем сообщение подтверждения
    confirm_text = (
        f"🧟‍♂️ <b>ПОДТВЕРЖДЕНИЕ РЕАНИМАЦИИ ЗАЯВКИ</b>\n\n"
        f"• <b>Номер заявки:</b> <code>{transaction_number}</code>\n"
        f"• <b>Дата создания:</b> {created_date}\n"
        f"• <b>Сумма:</b> {rub_formatted} RUB ({idr_formatted} IDR)\n"
        f"• <b>Реквизиты:</b> {account_info}\n\n"
        f"⚠️ <b>Подтвердите, что вы хотите перевести эту заявку из статуса <i>timeout</i> в статус <i>created</i></b>\n\n"
        f"👤 <b>Оператор:</b> {message.from_user.full_name}"
    )
    
    # Создаем клавиатуру с кнопками подтверждения
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧟‍♂️ Да, оживить", 
                    callback_data=f"zombie_confirm_{transaction_number}_{message.from_user.id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", 
                    callback_data=f"zombie_cancel_{message.from_user.id}"
                )
            ]
        ]
    )
    
    await message.reply(confirm_text, reply_markup=keyboard, parse_mode="HTML")

# === CALLBACK HANDLER для кнопок реанимации ===
@router.callback_query(lambda c: c.data.startswith("zombie_"))
async def zombie_callback_handler(call: CallbackQuery, state: FSMContext):
    """Обработчик кнопок реанимации заявок"""
    data_parts = call.data.split("_")
    action = data_parts[1]  # confirm или cancel
    user_id = call.from_user.id
    
    # Проверка прав доступа
    user_rank = await db.get_user_rank(user_id)
    if user_rank not in ("operator", "admin", "superadmin"):
        await call.answer("🚫 Не ваша кнопка!", show_alert=True)
        return
    
    if action == "cancel":
        # Проверяем, что отменяет тот же пользователь
        callback_user_id = int(data_parts[2])
        if user_id != callback_user_id:
            await call.answer("🚫 Не ваша кнопка!", show_alert=True)
            return
        
        await call.message.edit_text(
            call.message.text + "\n\n❌ <b>Реанимация отменена</b>",
            parse_mode="HTML"
        )
        await call.answer("Реанимация отменена")
        return
    
    elif action == "confirm":
        # Проверяем, что подтверждает тот же пользователь
        callback_user_id = int(data_parts[3])
        if user_id != callback_user_id:
            await call.answer("🚫 Не ваша кнопка!", show_alert=True)
            return
        
        transaction_number = data_parts[2]
        
        # Получаем заявку
        transaction = await db.get_transaction_by_number(transaction_number)
        if not transaction:
            await call.answer("❌ Заявка не найдена!", show_alert=True)
            return
        
        if transaction.get('status') != "timeout":
            await call.answer("❌ Статус заявки изменился!", show_alert=True)
            return
        
        try:
            # Обновляем статус заявки
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.update_transaction_status(transaction_number, "created", now_utc)
            
            # Добавляем запись в историю
            now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            user_nick = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
            chat_id = call.message.chat.id
            msg_id = call.message.message_id
            
            # Формируем ссылку на сообщение
            if call.message.chat.username:
                link = f"https://t.me/{call.message.chat.username}/{msg_id}"
            else:
                chat_id_num = str(chat_id)
                if chat_id_num.startswith('-100'):
                    chat_id_num = chat_id_num[4:]
                elif chat_id_num.startswith('-'):
                    chat_id_num = chat_id_num[1:]
                link = f"https://t.me/c/{chat_id_num}/{msg_id}"
            
            # Добавляем запись в историю
            zombie_entry = f"{now_str}${user_nick}$реанимация${link}"
            old_history = transaction.get('history', '')
            history = old_history + "%%%" + zombie_entry if old_history else zombie_entry
            await db.update_transaction_history(transaction_number, history)
            
            # Форматируем данные для сообщения
            rub_amount = int(transaction['rub_amount']) if transaction['rub_amount'] else 0
            idr_amount = int(transaction['idr_amount']) if transaction['idr_amount'] else 0
            rub_formatted = f"{rub_amount:,}".replace(",", " ")
            idr_formatted = f"{idr_amount:,}".replace(",", " ")
            
            # Обновляем сообщение
            success_text = (
                f"👻 <b>ЗАЯВКА ОЖИВЛЕНА!</b>\n\n"
                f"📋 <b></b> <code>{transaction_number}</code>\n"
                f"💰 <b>Сумма:</b> {rub_formatted} RUB ({idr_formatted} IDR)\n"
                f"👤 <b>Оживил:</b> {user_nick}\n"
                f"🕐 <b>Время:</b> {now_str}\n\n"
                f"🔄 <b>Статус заявки изменен:</b> ⚫<i>timeout</i> → ⚪<b>created</b>"
            )
            
            await call.message.edit_text(success_text, parse_mode="HTML")
            await call.answer("👻 Заявка успешно оживлена!")
            
            log_func(f"Заявка {transaction_number} оживлена пользователем {user_id} ({user_nick})")
            
        except Exception as e:
            log_error(f"Ошибка при оживлении заявки {transaction_number}: {e}")
            await call.answer("❌ Произошла ошибка при оживлении!", show_alert=True)
            return

# === КОМАНДА АНЕКДОТОВ ===
@router.message(Command("joke"))
async def cmd_joke(message: Message):
    """Команда для получения случайного анекдота"""
    try:
        log_func(f"Запрос анекдота от пользователя {message.from_user.id}")
        
        # Отправляем сообщение о загрузке
        loading_msg = await message.reply("🎭 Ищу для вас анекдот...")
        
        # Получаем анекдот с информацией об источнике
        joke_data = await get_joke_with_source()
        
        # Формируем красивое сообщение
        joke_text = joke_data["joke"]
        source = joke_data["source"]
        
        # Добавляем эмодзи в зависимости от типа анекдота
        if "программист" in joke_text.lower():
            emoji = "💻"
        elif "git" in joke_text.lower() or "python" in joke_text.lower():
            emoji = "🐍"
        else:
            emoji = "😄"
        
        response_text = (
            f"{emoji} <b>Анекдот:</b>\n\n"
            f"<i>{joke_text}</i>\n\n"
            f"📡 <i>Источник: {source}</i>"
        )
        
        # Обновляем сообщение с анекдотом
        await loading_msg.edit_text(response_text, parse_mode="HTML")
        
        log_func(f"Анекдот успешно отправлен пользователю {message.from_user.id}")
        
    except Exception as e:
        log_error(f"Ошибка при получении анекдота: {e}")
        error_text = (
            "😅 <b>Упс!</b>\n\n"
            "К сожалению, не удалось найти анекдот.\n"
            "Попробуйте позже или напишите свой! 😄"
        )
        
        if 'loading_msg' in locals():
            await loading_msg.edit_text(error_text, parse_mode="HTML")
        else:
            await message.reply(error_text, parse_mode="HTML")

# Обработчик callback'ов для календаря выбора месяца/года
@router.callback_query(lambda c: c.data.startswith("my_"))
async def month_year_calendar_callback(call: CallbackQuery, state: FSMContext):
    """Обработчик callback'ов календаря выбора месяца/года"""
    if str(call.message.chat.id) != str(config.ADMIN_GROUP):
        await call.answer("⛔️ Команда доступна только в чате админов.", show_alert=True)
        await state.clear()
        return
    if not await is_admin_or_superadmin(call.from_user.id):
        await call.answer("⛔️ Команда доступна только для админа и суперадмина.", show_alert=True)
        await state.clear()
        return
    
    calendar = MonthYearCalendar()
    selected, data = calendar.process_selection(call.data)
    
    if data.get("action") == "cancel":
        await call.message.edit_text("❌ Выбор месяца отменён.")
        await state.clear()
        return
    
    if selected and data.get("month"):
        # Месяц выбран, сохраняем данные
        year = data["year"]
        month = data["month"]
        months_short = calendar.months_short['ru_RU']
        month_name = months_short[month - 1]
        month_str = f"{month_name}{year}"
        await state.update_data(selected_month=month_str)
        # Пробуем получить курс с Bybit P2P
        try:
            rate = await get_p2p_idr_usdt_avg_rate()
            if rate and rate > 0:
                rate_str = f"{rate:,.2f}".replace(",", " ").replace(".", ",")
                text = (
                    f"📅 Выбран: <b>{calendar.months['ru_RU'][month-1]} {year}</b>\n\n"
                    f"💱 Курс IDR→USDT с Bybit P2P: <b>{rate_str}</b>\n\n"
                    f"Использовать этот курс?"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Да", callback_data=f"use_bybit_rate_{rate}"),
                        InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="enter_rate_manually")
                    ]
                ])
                await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
                await state.set_state(VsepReportStates.waiting_for_rate)
                return
        except Exception as e:
            print(f"[BYBIT P2P ERROR] {e}")
        await state.set_state(VsepReportStates.waiting_for_rate)
        await call.message.edit_text(
            f"📅 Выбран: <b>{calendar.months['ru_RU'][month-1]} {year}</b>\n\n"
            f"💱 Введите курс IDR к USDT для пересчёта итогов (например: 16000)",
            parse_mode="HTML"
        )
    else:
        # Обновляем календарь с новым годом
        year = data.get("year", datetime.now().year)
        keyboard = calendar.create_month_year_keyboard(year)
        await call.message.edit_reply_markup(reply_markup=keyboard)
