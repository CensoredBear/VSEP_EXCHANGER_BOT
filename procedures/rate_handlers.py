"""
🟣 Обработчики для управления курсами валют
==========================================
Callback handlers для изменения курсов валют с подтверждением
"""
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from db import db
from logger import logger

# === 🟣 CALLBACK HANDLERS ДЛЯ ИЗМЕНЕНИЯ КУРСОВ ===

async def rate_change_confirm(call: CallbackQuery, state: FSMContext):
    """
    🟣 Callback для подтверждения изменения курса
    Обрабатывает подтверждение изменения курса от администратора
    Вычисляет новые курсы для всех зон и сохраняет в базу данных
    """
    data = await state.get_data()
    # Защита: только инициатор может подтверждать
    if call.from_user.id != (call.message.reply_to_message.from_user.id if call.message and call.message.reply_to_message else call.from_user.id):  # type: ignore
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
        try:
            if call.message:
                await call.message.edit_text("Данные устарели, начните заново.")  # type: ignore
        except:
            pass
        await state.clear()
        return
    new_rate = float(data['new_rate'])
    coefs = await db.get_rate_coefficients()
    
    # Проверяем, что коэффициенты получены
    if not coefs:
        try:
            if call.message:
                await call.message.edit_text("❌ Ошибка: не удалось получить коэффициенты курсов. Попробуйте позже.")  # type: ignore
        except:
            pass
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
        try:
            if call.message:
                await call.message.edit_text("❌ Ошибка: база данных недоступна. Попробуйте позже.")  # type: ignore
        except:
            pass
        await state.clear()
        return
    
    await db.pool.execute('UPDATE "VSEPExchanger"."rate" SET is_actual=FALSE WHERE is_actual=TRUE')
    await db.pool.execute('''
        INSERT INTO "VSEPExchanger"."rate" (main_rate, rate1, rate2, rate3, rate4, rate_back, rate_special, created_by, created_at, is_actual)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), TRUE)
    ''', new_rate, rate1, rate2, rate3, rate4, rate_back, rate_special, call.from_user.id)
    try:
        if call.message:
            await call.message.edit_text("Курсы изменены!")  # type: ignore
    except:
        pass
    # Импортируем функцию здесь чтобы избежать циклических импортов
    from handlers import cmd_rate_show
    await cmd_rate_show(call.message)
    await state.clear()

async def rate_change_cancel(call: CallbackQuery, state: FSMContext):
    """
    🟣 Callback для отмены изменения курса
    Обрабатывает отмену изменения курса от администратора
    """
    data = await state.get_data()
    # Защита: только инициатор может отменять
    if call.from_user.id != (call.message.reply_to_message.from_user.id if call.message and call.message.reply_to_message else call.from_user.id):  # type: ignore
        try:
            await call.answer("Только инициатор может отменять изменение курса!", show_alert=True)
        except Exception:
            pass
        return
    try:
        if call.message:
            await call.message.edit_text("Изменение курса отменено.")  # type: ignore
    except:
        pass
    await state.clear() 