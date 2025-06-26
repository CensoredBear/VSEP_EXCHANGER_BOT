from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from logger import log_func, log_error
from joke_parser import get_joke_with_source

router = Router()

@router.message(Command("joke"))
async def cmd_joke(message: Message):
    """Команда для получения случайного анекдота"""
    try:
        log_func(f"Запрос анекдота от пользователя {message.from_user.id}")
        loading_msg = await message.reply("🎭 Ищу для вас анекдот...")
        joke_data = await get_joke_with_source()
        joke_text = joke_data["joke"]
        source = joke_data["source"]
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