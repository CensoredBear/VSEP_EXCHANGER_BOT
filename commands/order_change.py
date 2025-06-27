"""
🔄 Команда order_change - Изменение статуса заявок
==================================================
Позволяет администраторам и суперадминам изменять статус заявок
с полным логированием и подтверждением.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timezone, timedelta
import traceback

from db import db
from logger import logger, log_system, log_user, log_func, log_db, log_warning, log_error
from permissions import is_admin_or_superadmin, is_superadmin
from utils import fmt_0

# Создаем роутер для команды
router = Router()

# Определяем BALI_TZ локально, чтобы избежать циклического импорта
BALI_TZ = timezone(timedelta(hours=8))

# Состояния FSM для команды order_change
class OrderChangeStates(StatesGroup):
    waiting_for_confirmation = State()

# Все возможные статусы заявок
ALL_STATUSES = {
    'created': '⚪ created - создана',
    'control': '🟡 control - на контроле',
    'accept': '🔵 accept - подтверждена',
    'bill': '🟣 bill - в счете',
    'accounted': '🟢 accounted - оплачена',
    'timeout': '🟤 timeout - истекла',
    'cancel': '⚫ cancel - отменена',
    'night': '🌙 night - ночной запрос',
}

# Статусы, которые нельзя изменять обычным админам
RESTRICTED_STATUSES = ['accounted', 'bill']

async def format_order_card(transaction: dict) -> str:
    """Форматирует карточку заявки для отображения"""
    order_number = transaction.get('transaction_number', 'N/A')
    
    # Определяем возврат или обычная заявка
    is_refund = int(transaction.get('idr_amount', 0)) < 0 or int(transaction.get('rub_amount', 0)) < 0
    idr = abs(int(transaction.get('idr_amount', 0)))
    rub = abs(int(transaction.get('rub_amount', 0)))
    
    # Формируем заголовок
    lines = []
    lines.append(f"<b>📋 Карточка заявки № <code>{order_number}</code></b>")
    
    if is_refund:
        lines.append(f"\n<b>Сумма возврата:</b> {fmt_0(rub)} RUB ⏮ {fmt_0(idr)} IDR")
    else:
        lines.append(f"\n<b>Сумма:</b> {fmt_0(idr)} IDR ⏮ {fmt_0(rub)} RUB")
    
    # Текущий статус
    current_status = transaction.get('status', '-')
    status_display = ALL_STATUSES.get(current_status, current_status)
    lines.append(f"\n<b>🔄 Текущий статус:</b> {status_display}")
    
    # Примечание
    note = transaction.get('note', '-')
    if not note:
        note = '-'
    lines.append(f"\n<b>📝 Примечание:</b> {note}")
    
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
            
            status_disp = ALL_STATUSES.get(status, status)
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
        lines.append("\n<b>📜 Хронология:</b>")
        lines.extend(hist_lines)
    
    # Реквизиты
    acc_info = transaction.get('account_info', '-')
    lines.append(f"\n<b>💳 Реквизиты:</b> {acc_info}")
    
    return '\n'.join(lines)

def create_status_keyboard(current_status: str, is_superadmin: bool) -> InlineKeyboardMarkup:
    """Создает клавиатуру с доступными статусами для изменения"""
    keyboard_buttons = []
    
    for status, display_name in ALL_STATUSES.items():
        # Пропускаем текущий статус
        if status == current_status:
            continue
        
        # Проверяем ограничения для обычных админов
        if status in RESTRICTED_STATUSES and not is_superadmin:
            continue
        
        # Добавляем пробелы в начало для выравнивания по левому краю
        # Используем неразрывные пробелы для лучшего выравнивания
        button_text = f"{display_name}"
        callback_data = f"order_change_status_{status}"
        
        keyboard_buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    # Добавляем кнопку отмены
    keyboard_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="order_change_cancel")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

@router.message(Command("order_change"))
async def cmd_order_change(message: Message, state: FSMContext):
    """🔄 Команда order_change - Изменение статуса заявки"""
    log_user(f"Получена команда /order_change от пользователя {message.from_user.id} в чате {message.chat.id}")
    
    # Проверка прав доступа
    user_id = message.from_user.id
    if not await is_admin_or_superadmin(user_id):
        log_warning(f"Пользователь {user_id} попытался использовать /order_change без прав")
        await message.reply("🚫 Не выполнено.\nПРИЧИНА: команда доступна только администраторам и суперадминам.")
        return
    
    # Проверка наличия номера заявки
    args = (message.text or "").strip().split()
    if len(args) < 2:
        await message.reply(
            "❌ Не выполнено.\n"
            "ПРИЧИНА: не указан номер заявки.\n\n"
            "📝 <b>Образец команды:</b>\n"
            "<code>/order_change 2506123456789</code>",
            parse_mode="HTML"
        )
        return
    
    order_number = args[1].strip()
    log_func(f"Запрос изменения статуса для заявки {order_number}")
    
    # Получение заявки из базы данных
    if not db.pool:
        await message.reply("❌ Ошибка: база данных недоступна.")
        return
    
    transaction = await db.get_transaction_by_number(order_number)
    if not transaction:
        await message.reply(
            "❌ Не выполнено.\n"
            "ПРИЧИНА: заявка с таким номером не найдена."
        )
        return
    
    # Проверка возможности изменения статуса
    current_status = transaction.get('status', '')
    is_superadmin_user = await is_superadmin(user_id)
    
    # Блокировка изменения оплаченных заявок для обычных админов
    if current_status in RESTRICTED_STATUSES and not is_superadmin_user:
        status_display = ALL_STATUSES.get(current_status, current_status)
        await message.reply(
            f"🚫 Не выполнено.\n"
            f"ПРИЧИНА: заявка имеет статус <b>{status_display}</b>.\n\n"
            f"⚠️ <b>Изменение статуса оплаченных или ожидающих оплаты заявок доступно только суперадминистратору.</b>\n\n"
            f"Обратитесь к суперадминистратору для изменения статуса.",
            parse_mode="HTML"
        )
        return
    
    # Форматирование карточки заявки
    order_card = await format_order_card(transaction)
    
    # Создание клавиатуры с доступными статусами
    keyboard = create_status_keyboard(current_status, is_superadmin_user)
    
    # Формирование сообщения
    current_status_display = ALL_STATUSES.get(current_status, current_status)
    message_text = (
        f"🔄 <b>ИЗМЕНЕНИЕ СТАТУСА ЗАЯВКИ</b>\n\n"
        f"{order_card}\n\n"
    
        f"Текущий статус: <b>{current_status_display}</b>\n"

        f"🎯 <b>Выберите новый статус для заявки:</b>\n\n"
        f"‼‼ <b>ВНИМАНИЕ: изменение статуса влияет на финансовые показатели! Будьте внимательны при данной операции !!!</b>\n"
    )
    
    # Сохранение данных в состоянии
    await state.update_data(
        order_number=order_number,
        current_status=current_status,
        user_id=user_id,
        is_superadmin=is_superadmin_user
    )
    
    await message.reply(message_text, reply_markup=keyboard, parse_mode="HTML")
    log_func(f"Отображена карточка заявки {order_number} с кнопками изменения статуса")

@router.callback_query(lambda c: c.data.startswith("order_change_status_"))
async def order_change_status_callback(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора нового статуса"""
    log_user(f"Выбран новый статус для заявки пользователем {call.from_user.id}")
    
    # Получение данных из состояния
    data = await state.get_data()
    order_number = data.get('order_number')
    current_status = data.get('current_status')
    user_id = data.get('user_id')
    is_superadmin = data.get('is_superadmin')
    
    # Проверка, что кнопку нажимает тот же пользователь
    if call.from_user.id != user_id:
        await call.answer("❌ Это не ваша кнопка!", show_alert=True)
        return
    
    # Получение нового статуса
    new_status = call.data.split("_")[-1]
    new_status_display = ALL_STATUSES.get(new_status, new_status)
    current_status_display = ALL_STATUSES.get(current_status, current_status)
    
    # Формирование сообщения подтверждения
    confirm_text = (
        f"⚠️ <b>ПОДТВЕРЖДЕНИЕ ИЗМЕНЕНИЯ СТАТУСА</b>\n\n"
        f"📋 <b>Заявка:</b> <code>{order_number}</code>\n\n"
        f"🔄 <b>Изменение:</b>\n {current_status_display} →→→ {new_status_display}\n\n"
        f"👤 <b>Оператор:</b> {call.from_user.full_name}\n\n"
    )
    
    # Особое предупреждение для суперадмина при изменении оплаченных заявок
    if is_superadmin and current_status in RESTRICTED_STATUSES:
        confirm_text += (
            f"🚨 <b>ВНИМАНИЕ! ВЫ МЕНЯЕТЕ СТАТУС ОПЛАЧЕННОЙ ИЛИ ОЖИДАЮЩЕЙ ОПЛАТЫ ЗАЯВКИ!</b>\n\n"
        )
    
    confirm_text += "<b>⁉ Вы точно хотите изменить статус заявки?</b>"
    
    # Создание клавиатуры подтверждения
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, изменить", callback_data=f"order_change_confirm_{new_status}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="order_change_cancel")
        ]
    ])
    
    # Сохранение нового статуса в состоянии
    await state.update_data(new_status=new_status)
    await state.set_state(OrderChangeStates.waiting_for_confirmation)
    
    await call.message.edit_text(confirm_text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()
    log_func(f"Запрошено подтверждение изменения статуса {current_status} → {new_status}")

@router.callback_query(lambda c: c.data.startswith("order_change_confirm_"))
async def order_change_confirm_callback(call: CallbackQuery, state: FSMContext):
    """Обработчик подтверждения изменения статуса"""
    log_user(f"Подтверждено изменение статуса заявки пользователем {call.from_user.id}")
    
    # Получение данных из состояния
    data = await state.get_data()
    order_number = data.get('order_number')
    current_status = data.get('current_status')
    new_status = data.get('new_status')
    user_id = data.get('user_id')
    
    # Проверка, что кнопку нажимает тот же пользователь
    if call.from_user.id != user_id:
        await call.answer("❌ Это не ваша кнопка!", show_alert=True)
        return
    
    try:
        # Обновление статуса в базе данных
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.update_transaction_status(order_number, new_status, now_utc)
        
        # Формирование записи в историю
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        user_nick = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
        
        # Формирование ссылки на сообщение
        chat_id = call.message.chat.id
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
        
        # Добавление записи в историю
        history_entry = f"{now_str}${user_nick} сменил статус${new_status}${link}"
        
        # Получение текущей истории и добавление новой записи
        transaction = await db.get_transaction_by_number(order_number)
        old_history = transaction.get('history', '') if transaction else ''
        new_history = old_history + "%%%" + history_entry if old_history else history_entry
        
        await db.update_transaction_history(order_number, new_history)
        
        # Формирование сообщения об успехе
        new_status_display = ALL_STATUSES.get(new_status, new_status)
        current_status_display = ALL_STATUSES.get(current_status, current_status)
        
        success_text = (
            f"✅ <b>СТАТУС ЗАЯВКИ ИЗМЕНЕН!</b>\n\n"
            f"📋 <b>Заявка:</b> <code>{order_number}</code>\n"
            f"🔄 <b>Изменение:</b> {current_status_display} → {new_status_display}\n"
            f"👤 <b>Оператор:</b> {user_nick}\n"
            f"⏰ <b>Время:</b> {now_str}\n\n"
            f"📝 <b>Запись добавлена в историю заявки</b>"
        )
        
        await call.message.edit_text(success_text, parse_mode="HTML")
        await call.answer("✅ Статус успешно изменен!")
        
        # Логирование успешного изменения
        log_system(f"Статус заявки {order_number} изменен: {current_status} → {new_status} пользователем {user_id} ({user_nick})")
        log_db(f"[DB] update_transaction_status: {order_number} = {new_status}")
        
    except Exception as e:
        log_error(f"Ошибка при изменении статуса заявки {order_number}: {e}")
        await call.message.edit_text(
            "❌ <b>ОШИБКА ПРИ ИЗМЕНЕНИИ СТАТУСА</b>\n\n"
            "Произошла ошибка при обновлении статуса заявки.\n"
            "Попробуйте позже или обратитесь к администратору.",
            parse_mode="HTML"
        )
        await call.answer("❌ Произошла ошибка!", show_alert=True)
    
    # Очистка состояния
    await state.clear()

@router.callback_query(lambda c: c.data == "order_change_cancel")
async def order_change_cancel_callback(call: CallbackQuery, state: FSMContext):
    """Обработчик отмены изменения статуса"""
    log_user(f"Отменено изменение статуса заявки пользователем {call.from_user.id}")
    
    # Получение данных из состояния
    data = await state.get_data()
    user_id = data.get('user_id')
    
    # Проверка, что кнопку нажимает тот же пользователь
    if call.from_user.id != user_id:
        await call.answer("❌ Это не ваша кнопка!", show_alert=True)
        return
    
    await call.message.edit_text(
        "❌ <b>ИЗМЕНЕНИЕ СТАТУСА ОТМЕНЕНО</b>\n\n"
        "Операция была отменена пользователем.",
        parse_mode="HTML"
    )
    await call.answer("❌ Изменение отменено")
    
    # Очистка состояния
    await state.clear() 