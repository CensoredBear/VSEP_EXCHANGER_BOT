from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram import F, Dispatcher, Router
from logger import logger
from db import db
from aiogram.filters import Command
from permissions import is_operator_or_admin, is_admin_or_superadmin
import re
from chat_logger import log_message
from config import config

bank_router = Router()

class BankNewStates(StatesGroup):
    bank = State()
    card_number = State()
    recipient_name = State()
    sbp_phone = State()
    confirm = State()

class BankChangeActualStates(StatesGroup):
    waiting_action = State()
    waiting_number = State()
    change_type = State()

class BankRemoveStates(StatesGroup):
    waiting_number = State()
    confirm = State()

@bank_router.message(Command("bank_new"))
async def cmd_bank_new(message: Message, state: FSMContext):
    if str(message.chat.id) != config.ADMIN_GROUP:
        await message.reply("Извините, команда невозможна в данном чате.")
        return
    if not await is_operator_or_admin(message.from_user.id):
        await message.reply("🛑 Команда доступна только админам и операторам сервиса.")
        logger.warning(f"{message.from_user.id} попытался вызвать /bank_new без прав admin/operator")
        return
    await state.set_state(BankNewStates.bank)
    current_state = await state.get_state()
    logger.info(f"[FSM] User {message.from_user.id} state set to: {current_state}")
    await state.update_data(initiator_id=message.from_user.id)
    await message.answer(
        f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n✍🏻 Введите название банка:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]]
        )
    )
    logger.info(f"{message.from_user.id} начал диалог добавления реквизитов")

@bank_router.message(BankNewStates.bank)
async def banknew_bank(message: Message, state: FSMContext):
    logger.info(f"[FSM] Entered banknew_bank handler for user {message.from_user.id} with text: '{message.text}'")
    current_state = await state.get_state()
    logger.info(f"[FSM] Current state for user {message.from_user.id} is {current_state}")
    data = await state.get_data()
    logger.info(f"[FSM] State data for user {message.from_user.id}: {data}")

    if message.from_user.id != data.get("initiator_id"):
        await message.answer("⛔️ Это не ваш диалог добавления реквизитов!", show_alert=True)
        return
    bank = message.text.strip()
    if not bank.isalpha() or " " in bank:
        await message.answer("🚫 НЕ принято.\n\nПричина: Название банка должно содержать только буквы и быть одним словом. Попробуйте ещё раз.")
        return
    bank = bank.upper()
    await state.update_data(bank=bank)
    await state.set_state(BankNewStates.card_number)
    await message.answer(
        f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n✍🏻 Введите номер карты (или нажмите кнопку, если не требуется предоставление номера):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Только СБП", callback_data="card_number_sbp_only")],
                [InlineKeyboardButton(text="Назад", callback_data="banknew_back:bank"), InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]
            ]
        )
    )
@bank_router.callback_query(F.data == "card_number_sbp_only", BankNewStates.card_number)
@bank_router.message(BankNewStates.card_number)
async def banknew_card_number(message_or_call: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if isinstance(message_or_call, CallbackQuery):
        user_id = message_or_call.from_user.id
        message = message_or_call.message
    else:
        user_id = message_or_call.from_user.id
        message = message_or_call
        
    if user_id != data.get("initiator_id"):
        await message.answer("⛔️ Это не ваш диалог добавления реквизитов!", show_alert=True)
        return
    
    if isinstance(message_or_call, CallbackQuery) and message_or_call.data == "card_number_sbp_only":
        await state.update_data(card_number="перевод_по_СБП")
        await state.set_state(BankNewStates.recipient_name)
        await message.edit_text(
            "↪ Введите имя получателя:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Назад", callback_data="banknew_back:card_number"), InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]
                ]
            )
        )
        return

    card_number = message.text.strip()
    if not card_number.isdigit() or len(card_number) != 20:
        await message.answer(
            f"🚫 НЕ принято.\n\nПричина: Номер карты должен содержать ровно 20 знаков (только цифр).\n\n"
            f"Сейчас вы ввели: {card_number} - {len(card_number)} знаков.\nПопробуйте ещё раз."
        )
        return

    await state.update_data(card_number=card_number)
    await state.set_state(BankNewStates.recipient_name)
    await message.answer(
        f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n✍🏻 Введите имя получателя:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="banknew_back:card_number"), InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]
            ]
        )
    )

@bank_router.message(BankNewStates.recipient_name)
async def banknew_recipient_name(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("initiator_id"):
        await message.answer("⛔️ Это не ваш диалог добавления реквизитов!", show_alert=True)
        return
    name = message.text.strip()
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё. ]+", name):
        await message.answer("🚫 НЕ принято.\n\nПричина: Имя получателя должно содержать только буквы, точку и пробел. Попробуйте ещё раз.")
        return
    name = name.upper()
    await state.update_data(recipient_name=name)
    await state.set_state(BankNewStates.sbp_phone)
    await message.answer(
        f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n✍🏻 Введите телефон для СБП:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="banknew_back:recipient_name"), InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]
            ]
        )
    )

@bank_router.message(BankNewStates.sbp_phone)
async def banknew_sbp_phone(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("initiator_id"):
        await message.answer("⛔️ Это не ваш диалог добавления реквизитов!", show_alert=True)
        return
    phone = message.text.strip().replace(" ", "")
    phone_digits = re.sub(r"[^\d+]", "", phone)
    if phone_digits.startswith("+7") and len(phone_digits) == 12:
        norm_phone = phone_digits
    elif phone_digits.startswith("8") and len(phone_digits) == 11:
        norm_phone = "+7" + phone_digits[1:]
    elif phone_digits.startswith("7") and len(phone_digits) == 11:
        norm_phone = "+" + phone_digits
    elif len(phone_digits) == 10 and (phone_digits.startswith("7") or phone_digits.startswith("8")):
        norm_phone = "+7" + phone_digits[1:]
    elif len(phone_digits) == 10:
        norm_phone = "+7" + phone_digits
    else:
        await message.answer("Телефон должен быть в формате +7XXXXXXXXXX или 8XXXXXXXXXX (10 цифр). Попробуйте ещё раз.")
        return
    if not re.fullmatch(r"\+7\d{10}", norm_phone):
        await message.answer("Телефон должен быть в формате +7XXXXXXXXXX. Попробуйте ещё раз.")
        return
    await state.update_data(sbp_phone=norm_phone)
    data = await state.get_data()
    await state.set_state(BankNewStates.confirm)
    text = (
        f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n"
        f"<b>🔎 Проверьте данные для внесения:</b>\n\n"
        f"Банк: {data['bank']}\n"
        f"Карта: {data['card_number']}\n"
        f"Имя: {data['recipient_name']}\n"
        f"Телефон: {data['sbp_phone']}\n"
    )
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Подтвердить", callback_data="banknew_confirm")],
                [InlineKeyboardButton(text="Назад", callback_data="banknew_back:sbp_phone"), InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]
            ]
        )
    )

@bank_router.callback_query(F.data.startswith("banknew_back:"))
async def banknew_back(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if call.from_user.id != data.get("initiator_id"):
        await call.answer("⛔️ Это не ваш диалог!", show_alert=True)
        return
    step = call.data.split(":")[1]
    if step == "bank":
        await state.set_state(BankNewStates.bank)
        await call.message.edit_text(
            f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n✍🏻 Введите название банка:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]]
            )
        )
    elif step == "card_number":
        await state.set_state(BankNewStates.card_number)
        await call.message.edit_text(
            f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n✍🏻 Введите номер карты (или нажмите кнопку, если не требуется предоставление номера):",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Только СБП", callback_data="card_number_sbp_only")],
                    [InlineKeyboardButton(text="Назад", callback_data="banknew_back:bank"), InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]
                ]
            )
        )
    elif step == "recipient_name":
        await state.set_state(BankNewStates.recipient_name)
        await call.message.edit_text(
            f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n✍🏻 Введите имя получателя:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Назад", callback_data="banknew_back:card_number"), InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]
                ]
            )
        )
    elif step == "sbp_phone":
        await state.set_state(BankNewStates.sbp_phone)
        await call.message.edit_text(
            f"💳 ВНЕСЕНИЕ НОВЫХ РЕКВИЗИТОВ\n\n✍🏻 Введите телефон для СБП:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Назад", callback_data="banknew_back:recipient_name"), InlineKeyboardButton(text="Отмена", callback_data="banknew_cancel")]
                ]
            )
        )
    await call.answer()

@bank_router.callback_query(F.data == "banknew_cancel")
async def banknew_cancel(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if call.from_user.id != data.get("initiator_id"):
        await call.answer("⛔️ Это не ваш диалог!", show_alert=True)
        return
    await state.clear()
    await call.message.delete()
    log_message("delete", call.message.chat, call.from_user, text="[удалено ботом]")
    await call.message.answer("Все действия отменены.")
    await call.answer()

@bank_router.callback_query(F.data == "banknew_confirm")
async def banknew_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if call.from_user.id != data.get("initiator_id"):
        await call.answer("⛔️ Это не ваш диалог!", show_alert=True)
        return
    user_id = call.from_user.id
    await db.add_bank_account(
        account_id=data['card_number'],
        bank=data['bank'],
        card_number=data['card_number'],
        recipient_name=data['recipient_name'],
        sbp_phone=data['sbp_phone'],
        is_special=False,
        is_active=True,
        created_by=user_id
    )
    await state.clear()
    await call.message.edit_text("✅ Новые реквизиты успешно внесены в базу.")
    logger.info(f"Пользователь {user_id} внёс новые реквизиты: {data}")
    await call.answer()

@bank_router.message(Command("bank_change"))
async def cmd_bank_change(message: Message, state: FSMContext):
    if str(message.chat.id) != config.ADMIN_GROUP:
        await message.reply("Извините, команда невозможна в данном чате.")
        return
    if not await is_operator_or_admin(message.from_user.id):
        await message.reply("🛑 Команда доступна только админам и операторам сервиса.")
        return
    accounts = await db.get_active_bank_accounts()
    if not accounts:
        await message.reply("💳 Нет активных реквизитов.")
        return
    text = "<b>💳 Активные реквизиты:</b>\n"
    for acc in accounts:
        status = []
        if acc.get("is_actual"):
            status.append('🟢 "Актуальные"')
        if acc.get("is_special"):
            status.append('🔴 "Спец"')
        status_str = ", ".join(status) if status else "обычные"
        text += f"<b>{acc['account_number']}</b>: {acc['bank']}, {acc['card_number']}, {acc['recipient_name']}, {acc['sbp_phone']} — {status_str}\n"
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Сменить "Актуальные"', callback_data="change_actual")],
            [InlineKeyboardButton(text='Сменить "Спец"', callback_data="change_special")],
            [InlineKeyboardButton(text='Сменить "Актуальные" и "Спец"', callback_data="change_both")],
            [InlineKeyboardButton(text="Отмена", callback_data="bank_change_cancel")]
        ]
    )
    await state.set_state(BankChangeActualStates.waiting_action)
    await message.reply(text + "\n✍🏻 Выберите действие:", reply_markup=kb)

@bank_router.callback_query(F.data.in_(["change_actual", "change_special", "change_both"]))
async def bank_change_actual_action(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    initiator_id = call.message.reply_to_message.from_user.id if call.message.reply_to_message else call.from_user.id
    if call.from_user.id != initiator_id:
        await call.answer("⛔️ Это не ваш диалог!", show_alert=True)
        return

    change_map = {
        "change_actual": {"type": "actual", "text": '<b>🟢 "Актуальные"</b>'},
        "change_special": {"type": "special", "text": '<b>🔴 "Спец"</b>'},
        "change_both": {"type": "both", "text": '<b>🟢 "Актуальные"</b> и <b>🔴 "Спец"</b>'}
    }
    
    action_info = change_map.get(call.data)
    if not action_info: return

    await state.update_data(change_type=action_info["type"], initiator_id=initiator_id)
    await state.set_state(BankChangeActualStates.waiting_number)
    
    await call.message.edit_text(
        f"💳 ✍🏻 Введите <b>номер реквизита</b>, который станет {action_info['text']}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="bank_change_cancel")]
        ])
    )
    await call.answer()

@bank_router.callback_query(F.data == "bank_change_cancel")
async def bank_change_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Действие отменено.")
    await call.answer()

@bank_router.message(BankChangeActualStates.waiting_number)
async def bank_change_actual_number(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("initiator_id"):
        await message.answer("⛔️ Это не ваш диалог!")
        return
    
    try:
        number = int(message.text.strip())
        # Проверяем, существует ли такой реквизит
        if not await db.get_bank_account_by_number(number):
            await message.answer("🛑 Реквизит с таким номером не найден. Попробуйте снова.")
            return
    except (ValueError, TypeError):
        await message.answer("🚫 НЕ принято.\n\nПричина: Введите корректный номер реквизита!")
        return
    
    change_type = data.get("change_type")
    
    if change_type == "actual":
        await db.set_actual_bank_account(number)
        await message.answer(f'🔎 Реквизит <b>{number}</b> теперь <b>🟢 "Актуальный"</b>.')
    elif change_type == "special":
        await db.set_special_bank_account(number)
        await message.answer(f'🔎 Реквизит <b>{number}</b> теперь <b>🔴 "Спец"</b>.')
    elif change_type == "both":
        await db.set_actual_bank_account(number)
        await db.set_special_bank_account(number)
        await message.answer(f'🔎 Реквизит <b>{number}</b> теперь <b>🟢 "Актуальный"</b> и <b>🔴 "Спец"</b>.')
        
    await state.clear()

@bank_router.message(Command("bank_remove"))
async def cmd_bank_remove(message: Message, state: FSMContext):
    if str(message.chat.id) != config.ADMIN_GROUP:
        await message.reply("Извините, команда невозможна в данном чате.")
        return
    if not await is_admin_or_superadmin(message.from_user.id):
        await message.reply("🛑 Команда доступна только админам и суперадминам.")
        return
    await state.set_state(BankRemoveStates.waiting_number)
    await message.reply(
        "💳 Реквизиты будут переведены в архив (станут неактивными) без возможности восстановления в активные.\n\n✍🏻 Введите <b>номер реквизитов</b> для перевода в архив:")

@bank_router.message(BankRemoveStates.waiting_number)
async def bank_remove_number(message: Message, state: FSMContext):
    if str(message.chat.id) != config.ADMIN_GROUP:
        await message.reply("Извините, команда невозможна в данном чате.")
        return
    if not await is_admin_or_superadmin(message.from_user.id):
        await message.reply("🛑 Команда доступна только админам и суперадминам.")
        return
    try:
        number = int(message.text.strip())
    except ValueError:
        await message.answer("🚫 НЕ принято.\n\nПричина: Введите корректный номер реквизита!")
        return
    acc = await db.get_bank_account_by_number(number)
    if not acc:
        await message.answer("🛑 Реквизит с таким номером не найден.")
        return
    if acc.get("is_actual") or acc.get("is_special"):
        status = []
        if acc.get("is_actual"): status.append("актуальными")
        if acc.get("is_special"): status.append("специальными")
        await message.answer(f"🚫 НЕ принято.\n\nПричина: Реквизиты являются {' и '.join(status)}. Прежде чем их перевести в архив, снимите с них уникальность (передайте другим реквизитам).")
        await state.clear()
        return
    if not acc.get("is_active"):
        await message.answer("🛑 Реквизит уже неактивен (в архиве).")
        await state.clear()
        return
    await state.update_data(account_number=number)
    text = f"<b>💳 Реквизит для перевода в архив:</b>\n{acc['bank']}, {acc['card_number']}, {acc['recipient_name']}, {acc['sbp_phone']}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Подтвердить перевод в архив", callback_data="remove_confirm")]]
    )
    await state.set_state(BankRemoveStates.confirm)
    await message.answer(text, reply_markup=kb)

@bank_router.callback_query(F.data == "remove_confirm")
async def bank_remove_confirm(call: CallbackQuery, state: FSMContext):
    if str(call.message.chat.id) != config.ADMIN_GROUP:
        await call.answer("🛑 Команда доступна только в админском чате.", show_alert=True)
        return
    data = await state.get_data()
    number = data.get("account_number")
    if not number:
        await call.answer("🛑 Ошибка: номер реквизита не найден.", show_alert=True)
        return
    await db.deactivate_bank_account(number)
    await state.clear()
    await call.message.edit_text("🔎 Реквизит переведён в архив (неактивен).")
    await call.answer() 