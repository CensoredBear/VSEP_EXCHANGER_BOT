"""
🟣 Обработчики для управления сменами
====================================
Callback handlers для принудительного открытия/закрытия смен
"""
from aiogram.types import CallbackQuery
from scheduler import scheduler
from logger import logger

# === 🟣 CALLBACK HANDLERS ДЛЯ СМЕН ===

async def force_open_callback(call: CallbackQuery, data: dict):
    """
    🟣 Callback для принудительного открытия смены
    Обрабатывает подтверждение открытия смены от администратора
    """
    print("DATA IN force_open_callback:", data)
    if call.data == "force_open_yes":
        await scheduler.send_shift_start()
        scheduler.sent_start_today = True
        scheduler.sent_end_today = False
        try:
            if call.message:
                await call.message.edit_text("Смена принудительно открыта.")  # type: ignore
        except:
            pass
    else:
        try:
            if call.message:
                await call.message.edit_text("Операция отменена.")  # type: ignore
        except:
            pass

async def force_close_callback(call: CallbackQuery, data: dict):
    """
    🟣 Callback для принудительного закрытия смены
    Обрабатывает подтверждение закрытия смены от администратора
    """
    print("DATA IN force_close_callback:", data)
    if call.data == "force_close_yes":
        await scheduler.send_shift_end()
        scheduler.sent_end_today = True
        try:
            if call.message:
                await call.message.edit_text("Смена принудительно закрыта.")  # type: ignore
        except:
            pass
    else:
        try:
            if call.message:
                await call.message.edit_text("Операция отменена.")  # type: ignore
        except:
            pass 