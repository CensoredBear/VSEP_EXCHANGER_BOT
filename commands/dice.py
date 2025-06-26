from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from logger import log_func
import random

router = Router()

@router.message(Command("dice"))
async def cmd_dice(message: Message):
    """Команда для бросания кубика"""
    try:
        log_func(f"Бросок кубика от пользователя {message.from_user.id}")
        
        # Генерируем случайное число от 1 до 6
        result = random.randint(1, 6)
        
        # Выбираем эмодзи кубика в зависимости от результата
        dice_emojis = {
            1: "⚀",
            2: "⚁", 
            3: "⚂",
            4: "⚃",
            5: "⚄",
            6: "⚅"
        }
        
        dice_emoji = dice_emojis[result]
        
        # Формируем сообщение
        response_text = (
            f"🎲 <b>Бросок кубика</b>\n\n"
            f"Выпало: {dice_emoji} <b>{result}</b>\n\n"
            f"👤 <i>Игрок: {message.from_user.full_name}</i>"
        )
        
        await message.reply(response_text, parse_mode="HTML")
        log_func(f"Кубик показал {result} для пользователя {message.from_user.id}")
        
    except Exception as e:
        log_func(f"Ошибка при бросании кубика: {e}")
        await message.reply("❌ Ошибка при бросании кубика. Попробуйте еще раз!") 