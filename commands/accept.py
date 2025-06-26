"""
🟡 Команда accept - Подтверждение транзакции оператором

Этот модуль содержит логику обработки команды /accept для подтверждения
транзакций операторами сервиса.
"""

from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from config import config
from db import db
from permissions import is_operator_or_admin
from messages import get_bali_and_msk_time_list
from utils import fmt_0
from logger import log_func, log_db

router = Router()

@router.message(Command("accept"))
async def cmd_accept(message: Message):
    """
    🟡 Обработчик команды /accept
    
    Подтверждает транзакцию оператором. Команда должна быть отправлена
    в ответ на сообщение с командой /control.
    
    Args:
        message (Message): Сообщение с командой
    """
    reply = message.reply_to_message
    args = (message.text or "").split()
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

    # 4. Нет номера заявки — ошибка
    if len(args) < 2:
        await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: это архивная команда. В текщей реальности 'accept' осуществляется кнопкой под запросом.")
        return

    transaction_number = args[1].strip()
    transaction = await db.get_transaction_by_number(transaction_number)
    if not transaction:
        await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: заявка с таким номером не найдена.")
        return

    if transaction.get('status') not in ("created", "timeout"):
        await message.reply(f"{base_error}\n🚫 Не выполнено.\nПРИЧИНА: это архивная команда. В текщей реальности 'accept' осуществляется кнопкой под запросом.")
        return

    # Проверяем, что message.from_user не None
    if not message.from_user:
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: не удалось определить пользователя.")
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
✅ Платёж  ❯❯❯❯ {rub_fmt} RUB ({idr_fmt} IDR)

<i>отправленный на реквизиты:</i> 
<blockquote><i>{acc_info}</i></blockquote>
    
✅ ТРАНЗАКЦИЯ ПОДТВЕРЖДЕНА
Представителем Сервиса <b>{user_username}</b>
🕒 в: {confirm_time} (Bali)

🔵 Заявка: <b><code>{transaction_number}</code></b>''')
    
    # Отправляем новое сообщение и сохраняем его ID
    notification_msg = await message.reply(caption, parse_mode="HTML")
    notification_msg_id = notification_msg.message_id
    
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
    
    # Ссылка на новое сообщение с подтверждением
    if message.chat.username:
        link_notification = f"https://t.me/{message.chat.username}/{notification_msg_id}"
    else:
        chat_id_num = str(chat_id)
        if chat_id_num.startswith('-100'):
            chat_id_num = chat_id_num[4:]
        elif chat_id_num.startswith('-'):
            chat_id_num = chat_id_num[1:]
        link_notification = f"https://t.me/c/{chat_id_num}/{notification_msg_id}"
    
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
    control_entry = f"{reply_date}${reply_nick}$контроль${link_control}"
    accept_entry = f"{now_str}${user_nick}$accept${link_accept}"
    notification_entry = f"{now_str}${user_nick}$notification${link_notification}"
    # Получаем старую history
    old_history = transaction.get('history', '')
    if old_history:
        history = old_history + "%%%" + control_entry + "%%%" + accept_entry + "%%%" + notification_entry
    else:
        history = control_entry + "%%%" + accept_entry + "%%%" + notification_entry
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