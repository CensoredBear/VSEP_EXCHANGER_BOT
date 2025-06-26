from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from logger import log_func
import random

router = Router()

@router.message(Command("coin"))
async def cmd_coin(message: Message):
    """Команда для подбрасывания монетки"""
    try:
        log_func(f"Подброс монетки от пользователя {message.from_user.id}")
        
        # Генерируем случайный результат: орел или решка
        result = random.choice(["орел", "решка"])
        
        # Выбираем эмодзи в зависимости от результата
        if result == "орел":
            emoji = "🪙"
            side_emoji = "🦅"
        else:
            emoji = "🪙"
            side_emoji = "🪙"
        
        # Формируем сообщение
        response_text = (
            f"{emoji} <b>Подброс монетки</b>\n\n"
            f"Выпало: {side_emoji} <b>{result.upper()}</b>\n\n"
            f"👤 <i>Игрок: {message.from_user.full_name}</i>"
        )
        
        await message.reply(response_text, parse_mode="HTML")
        log_func(f"Монетка показала {result} для пользователя {message.from_user.id}")
        
    except Exception as e:
        log_func(f"Ошибка при подбрасывании монетки: {e}")
        await message.reply("❌ Ошибка при подбрасывании монетки. Попробуйте еще раз!") 