"""
VSEPExchangerBot Handlers
=========================
Этот модуль содержит обработчики команд Telegram-бота для сервиса обмена.
"""
from aiogram import Dispatcher, Router
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, BotCommand, BotCommandScopeDefault, BotCommandScopeAllGroupChats, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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
    get_control_no_attachment_message
)
from chat_logger import log_message
from procedures.input_sum import handle_input_sum
from scheduler import init_scheduler, scheduler, night_shift
from config import config, system_settings
from google_sync import write_to_google_sheet_async, write_multiple_to_google_sheet
import time
import asyncio
from aiogram.exceptions import TelegramBadRequest, TelegramMigrateToChat
import json

# Создаем роутер для всех обработчиков
router = Router()

# Определяем классы состояний FSM в начале файла
class RateChangeStates(StatesGroup):
    waiting_for_new_rate = State()

class ShiftTimeStates(StatesGroup):
    waiting_for_time = State()

BALI_TZ = timezone(timedelta(hours=8))

async def send_to_admin_group_safe(bot, text, parse_mode="HTML"):
    """Безопасная отправка сообщения в админскую группу с обработкой миграции"""
    try:
        await bot.send_message(config.ADMIN_GROUP, text, parse_mode=parse_mode)
        return True
    except TelegramMigrateToChat as e:
        # Группа была обновлена до супергруппы, используем новый ID
        new_chat_id = e.migrate_to_chat_id
        logger.warning(f"Группа {config.ADMIN_GROUP} была обновлена до супергруппы {new_chat_id}")
        try:
            await bot.send_message(new_chat_id, text, parse_mode=parse_mode)
            # Обновляем конфигурацию
            config.ADMIN_GROUP = str(new_chat_id)
            logger.info(f"Обновлен ADMIN_GROUP на {new_chat_id}")
            return True
        except Exception as e2:
            logger.error(f"Не удалось отправить сообщение в новую группу {new_chat_id}: {e2}")
            return False
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в админскую группу: {e}")
        return False

def fmt_0(val):
    """Format number with 0 decimal places"""
    if val is None:
        return "—"
    return f"{val:,.0f}".replace(",", " ").replace(".", ",")

def fmt_2(val):
    """Format number with 2 decimal places"""
    if val is None:
        return "—"
    return f"{val:,.2f}".replace(",", " ").replace(".", ",")

def fmt_delta(coef):
    """Format coefficient as percentage delta"""
    if coef is None:
        return "—"
    delta = (coef - 1) * 100
    if abs(delta) < 0.01:
        return "(базовый)"
    sign = "+" if delta > 0 else ""
    return f"({sign}{delta:.2f}%)".replace(".", ",")

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
    main_coef = float(coefs['main_rate'])
    rate1 = new_rate * float(coefs['rate1']) / main_coef
    rate2 = new_rate * float(coefs['rate2']) / main_coef
    rate3 = new_rate * float(coefs['rate3']) / main_coef
    rate4 = new_rate * float(coefs['rate4']) / main_coef
    rate_back = new_rate * float(coefs['rate_back']) / main_coef
    old_rate_row = await db.get_actual_rate()
    old_rate_special = old_rate_row['rate_special'] if old_rate_row else None
    rate_special = old_rate_special
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
        log_func(f"Получен список операторов: {len(operators)}")
        
        # Счетчик контроля
        counter = await db.get_control_counter(chat_id)
        new_counter = counter + 1
        await db.set_control_counter(chat_id, new_counter)
        log_func(f"Счетчик контроля для чата {chat_id} увеличен: {counter} -> {new_counter}")
        
        # Формируем текст уведомления
        operators_text = ", ".join([op.get('nickneim', str(op['id'])) for op in operators])
        counter_emoji = "🟨" if new_counter == 1 else "🟥" * new_counter
        notify_text = f"""<b>⚠️⚠️⚠️ ВНИМАНИЮ ОПЕРАТОРОВ:</b> 👨‍💻 {operators_text}
⚜️ <b>ЗАПРОС КОНТРОЛЯ ОПЛАТЫ</b> из чата: {chat_title}
🔗 <b>Ссылка:</b> <a href='{link}'>Перейти к сообщению</a>
👤 <b>Автор:</b> {user_nick}
📝 <b>Примечание:</b> {crm_number}

{counter_emoji}
<b>Счетчик контроля:</b> {new_counter}
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
    
    if call.data == "control_without_crm":
        log_func("Обработка нажатия кнопки 'Подтвердить без CRM'")
        # Удаляем кнопки
        await call.message.edit_reply_markup(reply_markup=None)
        # Обрабатываем запрос без CRM
        await process_control_request(call.message, "без CRM")
    elif call.data == "control_cancel":
        log_func("Обработка нажатия кнопки 'Отмена'")
        # Удаляем сообщение полностью
        await call.message.delete()
        log_func("Сообщение с кнопками удалено")
    
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
             old_history = transaction.get('history', '')
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
    admins = await db.get_admins()
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
"""🟡 Команда accept"""
@router.message(Command("accept"))
async def cmd_accept(message: Message):
    reply = message.reply_to_message
    args = message.text.split()
    base_error = "<blockquote>Команда должна быть отправлена в ответ на сообщение с командой [control].</blockquote>"
    
    # 1. Не в ответ на сообщение — ошибка
    if not reply:
        await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: команда отправлена НЕ в ответ на сообщение с командой [control].")
        return

    # 2. Проверяем, что сообщение содержит команду /control
    reply_text = (getattr(reply, 'text', None) or getattr(reply, 'caption', None) or "")
    if "/control" not in reply_text:
        await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: команда должна быть отправлена в ответ на сообщение с командой [control].")
        return

    # # 3. Нет фото/документа — ошибка
    # if not (
    #     (getattr(message, "photo", None) or getattr(message, "document", None)) or
    #     (reply and (getattr(reply, "photo", None) or getattr(reply, "document", None)))
    # ):
    #     await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: команда должна быть отправлена с фото или документом (или в ответ на сообщение с фото/документом).")
    #     return

    # 4. Нет номера заявки — ошибка
    if len(args) < 2:
        await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: не указан номер заявки.")
        return

    transaction_number = args[1].strip()
    transaction = await db.get_transaction_by_number(transaction_number)
    if not transaction:
        await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: заявка с таким номером не найдена.")
        return

    if transaction.get('status') not in ("created", "timeout"):
        await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: текущий статус заявки <b>'{transaction.get('status')}'</b> не валиден для подтверждения.")
        return

    user_rank = await db.get_user_rank(message.from_user.id)
    if user_rank not in ("operator", "admin"):
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только оператору сервиса и администратору.")
        return

    user = message.from_user
    times = get_bali_and_msk_time_list()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    # Извлекаем note из команды /control
    note_from_control = None
    idx = reply_text.find("/control")
    note_from_control = reply_text[idx + len("/control"):].strip()
    # Обновляем note заявки
    await db.update_transaction_note(transaction_number, note_from_control)

    await db.update_transaction_status(transaction_number, "accept", now_utc)
    confirm_time = times[6]  # дата+время по Бали
    user_username = f"@{user.username}" if user.username else user.full_name
    rub = transaction.get('rub_amount', '-')
    idr = transaction.get('idr_amount', '-')
    acc_info = transaction.get('account_info', '-')
    # Форматируем числа с разрядностью через пробел
    try:
        rub_fmt = fmt_0(int(rub))
    except Exception:
        rub_fmt = str(rub)
    try:
        idr_fmt = fmt_0(int(idr))
    except Exception:
        idr_fmt = str(idr)
    caption = (f'''
✅ Платёж по заявке {transaction_number}
   ❯❯❯❯ {rub_fmt} RUB ({idr_fmt} IDR)
отправленный на реквизиты: 
<blockquote>{acc_info}</blockquote>
    
✅ ПОДТВЕРЖДЕН Представителем Сервиса {user_username}
🕒 время подтверждения: {confirm_time} (Bali)''')
    # # --- Формируем ответ с вложением, если оно есть ---
    # control_media = None
    # control_caption = None
    # # 1. Вложение в самом сообщении с /control
    # if getattr(reply, 'photo', None):
    #     control_media = reply.photo[-1].file_id  # самое большое фото
    #     control_caption = caption
    #     await message.reply_photo(control_media, caption=control_caption)
    # elif getattr(reply, 'document', None):
    #     control_media = reply.document.file_id
    #     control_caption = caption
    #     await message.reply_document(control_media, caption=control_caption)
    # # 2. Вложение в сообщении, на которое ссылается /control
    # elif getattr(reply, 'reply_to_message', None):
    #     orig = reply.reply_to_message
    #     if getattr(orig, 'photo', None):
    #         control_media = orig.photo[-1].file_id
    #         control_caption = caption
    #         await message.reply_photo(control_media, caption=control_caption)
    #     elif getattr(orig, 'document', None):
    #         control_media = orig.document.file_id
    #         control_caption = caption
    #         await message.reply_document(control_media, caption=control_caption)
    #     else:
    #         await message.reply(caption)
    # else:
    await message.reply(caption)
    # Добавляем запись в history
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    user_nick = f"@{user.username}" if user.username else user.full_name
    chat_id = message.chat.id
    msg_id = message.message_id
    # Ссылка на текущее сообщение (accept)
    if message.chat.username:
        link_accept = f"https://t.me/{message.chat.username}/{msg_id}"
    else:
        chat_id_num = str(chat_id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link_accept = f"https://t.me/c/{chat_id_num}/{msg_id}"
    # Данные о сообщении-контроле (reply)
    reply_user = reply.from_user
    reply_nick = f"@{reply_user.username}" if reply_user and reply_user.username else (reply_user.full_name if reply_user else "unknown")
    reply_date = reply.date.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if hasattr(reply, 'date') and reply.date else "unknown"
    reply_msg_id = reply.message_id if hasattr(reply, 'message_id') else None
    if message.chat.username and reply_msg_id:
        link_control = f"https://t.me/{message.chat.username}/{reply_msg_id}"
    elif reply_msg_id:
        chat_id_num = str(chat_id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link_control = f"https://t.me/c/{chat_id_num}/{reply_msg_id}"
    else:
        link_control = "-"
    # Формируем две записи
    control_entry = f"{reply_date}${reply_nick}$control${link_control}"
    accept_entry = f"{now_str}${user_nick}$accept${link_accept}"
    # Получаем старую history
    old_history = transaction.get('history', '')
    if old_history:
        history = old_history + "%%%" + control_entry + "%%%" + accept_entry
    else:
        history = control_entry + "%%%" + accept_entry
    await db.update_transaction_history(transaction_number, history)
    # --- Счетчик контроля ---
    key = f"{chat_id}_control_counter"
    counter = await db.get_control_counter(chat_id)
    if counter > 0:
        await db.set_control_counter(chat_id, counter - 1)
        log_func(f"Счетчик контроля для чата {chat_id} (ключ: {key}) уменьшен: {counter} -> {counter-1}")
        log_db(f"[DB] set_system_setting: {key} = {counter-1}")
    else:
        await message.reply(f'''
        ВНИМАНИЕ!!!
                            
<b>🟡 ACCEPT without CONTROL</b>

<u>Команда принята, подтврждение заявки выполнено.</u>

<blockquote><i>Флаг лишь отмечает, что количество CONTROL меньше количества ACCEPT. Это не является критической ошибкой – однако, рекомендуется проверить корректность всех проведенных ордеров. Если найдете ошибку – обращайтесь к суперадмину для ручной корректировки.</i></blockquote>''')
        log_func(f"Попытка уменьшить счетчик контроля при нуле для чата {chat_id} (ключ: {key})")

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
        lines.append(
            '0'.ljust(coln1) +
            fmt_0(limits['main_rate']).ljust(coln2) +
            fmt_2(rate['main_rate']).ljust(coln4) +
            fmt_delta(coefs['main_rate']).ljust(coln5)
        )
        lines.append(
            fmt_0(limits['main_rate']).ljust(coln1) +
            fmt_0(limits['rate1']).ljust(coln2) +
            fmt_2(rate['rate1']).ljust(coln4) +
            fmt_delta(coefs['rate1']).ljust(coln5)
        )
        lines.append(
            fmt_0(limits['rate1']).ljust(coln1) +
            fmt_0(limits['rate2']).ljust(coln2) +
            fmt_2(rate['rate2']).ljust(coln4) +
            fmt_delta(coefs['rate2']).ljust(coln5)
        )
        lines.append(
            fmt_0(limits['rate2']).ljust(coln1) +
            fmt_0(limits['rate3']).ljust(coln2) +
            fmt_2(rate['rate3']).ljust(coln4) +
            fmt_delta(coefs['rate3']).ljust(coln5)
        )
        lines.append(
            fmt_0(limits['rate3']).ljust(coln1) +
            '∞'.ljust(coln2) +
            fmt_2(rate['rate4']).ljust(coln4) +
            fmt_delta(coefs['rate4']).ljust(coln5)
        )
        # Обратный курс и спец. лимит
        lines.append('')
        lines.append(
            code('Обратный курс (возврат)....').ljust(coln1 + coln2) +
            fmt_2(rate['rate_back']).ljust(coln4) +
            fmt_delta(coefs['rate_back']).ljust(coln5)
        )
        lines.append(
            code('Специальные реквизиты от...').ljust(coln1 + coln2) +
            code(fmt_0(rate['rate_special']) + ' руб').ljust(coln4) +
            ' '.ljust(coln5)
        )

        # Информация о последнем изменении
        user_id = rate.get("created_by")
        from_user = "—"
        if user_id:
            admins = await db.get_admins()
            operators = await db.get_operators()
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
    admins = await db.get_admins()
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
            admins = await db.get_admins()
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
            admins = await db.get_admins()
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
            ops = await db.get_operators()
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
            ops = await db.get_operators()
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
    ops = await db.get_operators()
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
        old_history = transaction.get('history', '')
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
            transaction.get('used_rate', 0),
            'accounted',
            transaction.get('note', ''),
            transaction.get('acc_info', ''),
            history,
            str(chat_id),
            transaction.get('created_at', now_utc),
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
    main_coef = float(coefs['main_rate'])
    rate1 = new_rate * float(coefs['rate1']) / main_coef
    rate2 = new_rate * float(coefs['rate2']) / main_coef
    rate3 = new_rate * float(coefs['rate3']) / main_coef
    rate4 = new_rate * float(coefs['rate4']) / main_coef
    rate_back = new_rate * float(coefs['rate_back']) / main_coef
    
    # Получаем текущий курс
    old_rate_row = await db.get_actual_rate()
    old_rate = old_rate_row['main_rate'] if old_rate_row else 0
    
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

"""🟡 Запуск бота"""
async def send_startup_message(bot: Bot):
    """🟡 Запуск бота"""
    try:
        message = "🤖 VSEP Бот запущен и готов к работе!"
        await send_to_admin_group_safe(bot, message, parse_mode=None)
        logger.info("Отправлено сообщение о запуске бота в админскую группу")
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения о запуске: {e}")

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
        async with db.pool.acquire() as conn:
            logger.info(f"[STATUS] Соединение с БД получено, выполняем SQL запрос...")
            rows = await conn.fetch('''
                SELECT transaction_number, rub_amount, idr_amount
                FROM "VSEPExchanger"."transactions"
                WHERE source_chat = $1 AND status = 'created'
                ORDER BY created_at
            ''', str(chat_id))
            
            logger.info(f"[STATUS] Получено {len(rows)} открытых заявок из БД для чата {chat_id}")
        
        if not rows:
            logger.info(f"[STATUS] В чате {chat_id} нет открытых заявок")
            await message.reply("📊 <b>Открытые заявки</b>\n\nВ этом чате нет открытых заявок.")
            return
        
        logger.info(f"[STATUS] Начинаем формирование отчета для {len(rows)} заявок...")
        
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
        
        for row in rows:
            num = str(row['transaction_number'])
            rub = int(row['rub_amount']) if row['rub_amount'] else 0
            idr = int(row['idr_amount']) if row['idr_amount'] else 0
            lines.append(f"<code>{num.ljust(col1)}{fmt_0(rub).rjust(col2)}{fmt_0(idr).rjust(col3)}</code>")
            total_rub += rub
            total_idr += idr
        
        table = header + '\n'.join(lines)
        table += f"\n<code>{'-'*(col1+col2+col3)}</code>"
        table += f"\n<code>Итого: {len(rows):<5}{fmt_0(total_rub).rjust(col2)}{fmt_0(total_idr).rjust(col3)}</code>"
        
        await message.reply(table, parse_mode="HTML")
        logger.info(f"[STATUS] Отчет отправлен: {len(rows)} заявок, RUB={total_rub}, IDR={total_idr}")
        
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
    
    await message.reply(f"🟡 Запрос на контроль оплаты принят.\nПримечание: {crm_number}\n\nОператоры уведомлены.\nОжидайте подтверждения получения транзакции.")
    log_func("Отправлено сообщение с принятием контроля")
    await process_control_request(message, crm_number)

@router.message(Command("report"))
async def cmd_report(message: Message):
    """🟡 Команда report - отчет по всем группам запросов"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    log_user(f"Получена команда /report от пользователя {user_id} в чате {chat_id}")
    log_func(f"Начало обработки команды /report")

    # Получаем все ордера для этого чата с разными статусами
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
