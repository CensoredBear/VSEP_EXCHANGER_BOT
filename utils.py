"""
Утилиты для VSEPExchangerBot
"""
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup
from pydantic import ValidationError
from typing import Union, Dict, Optional

from logger import logger

async def safe_send_media_with_caption(
    bot: Bot, 
    chat_id: Union[int, str], 
    file_id: Optional[Dict[str, str]], 
    caption: str, 
    parse_mode: str = 'HTML', 
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    reply_to_message_id: Optional[int] = None
):
    """
    Tries to send a media file by file_id, using the appropriate method based on media type.
    Falls back to sending a text message if sending media fails.
    """
    try:
        if not file_id or 'id' not in file_id:
            logger.warning(f"[MEDIA_FAIL] No file_id provided for chat {chat_id}. Sending text only.")
            await bot.send_message(chat_id, caption, parse_mode=parse_mode, reply_markup=reply_markup, disable_web_page_preview=True, reply_to_message_id=reply_to_message_id)
            return

        media_id = file_id['id']
        media_type = file_id.get('type')

        logger.info(f"[MEDIA_ATTEMPT] Trying to send media {media_id} (type: {media_type}) to {chat_id}")

        # Отправляем анимации (GIF) через send_animation
        if media_type == 'animation':
            try:
                await bot.send_animation(chat_id, animation=media_id, caption=caption, parse_mode=parse_mode, reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)
                return
            except TelegramBadRequest as e:
                logger.warning(f"[MEDIA_RETRY] Failed to send {media_id} as animation, trying as photo. Error: {e.message}")
        
        # Отправляем видео через send_video
        elif media_type == 'video':
            try:
                await bot.send_video(chat_id, video=media_id, caption=caption, parse_mode=parse_mode, reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)
                return
            except TelegramBadRequest as e:
                logger.warning(f"[MEDIA_RETRY] Failed to send {media_id} as video, trying as photo. Error: {e.message}")
        
        # Для всех остальных типов (включая photo и неизвестные) используем send_photo
        await bot.send_photo(chat_id, photo=media_id, caption=caption, parse_mode=parse_mode, reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)

    except (TelegramBadRequest, ValidationError) as e:
        logger.error(f"[MEDIA_ERROR] Unexpected error with file_id {file_id}: {e}")
        logger.info(f"[MEDIA_FALLBACK] Sending text-only message to {chat_id} due to media error.")
        await bot.send_message(chat_id, caption, parse_mode=parse_mode, reply_markup=reply_markup, disable_web_page_preview=True, reply_to_message_id=reply_to_message_id)

# === 🔵 ФУНКЦИИ ФОРМАТИРОВАНИЯ ЧИСЕЛ ===

def fmt_0(val):
    """
    🔵 Форматирует число с 0 знаками после запятой
    Заменяет запятые на пробелы для разделения тысяч, точки на запятые
    Возвращает "—" если значение None
    """
    if val is None:
        return "—"
    return f"{val:,.0f}".replace(",", " ").replace(".", ",")

def fmt_2(val):
    """
    🔵 Форматирует число с 2 знаками после запятой
    Заменяет запятые на пробелы для разделения тысяч, точки на запятые
    Возвращает "—" если значение None
    """
    if val is None:
        return "—"
    return f"{val:,.2f}".replace(",", " ").replace(".", ",")

def fmt_delta(coef):
    """
    🔵 Форматирует коэффициент как процентное изменение
    Вычисляет дельту от базового значения (коэффициент - 1) * 100
    Возвращает "(базовый)" если дельта меньше 0.01%
    Возвращает "—" если значение None
    """
    if coef is None:
        return "—"
    delta = (coef - 1) * 100
    if abs(delta) < 0.01:
        return "(базовый)"
    sign = "+" if delta > 0 else ""
    return f"({sign}{delta:.2f}%)".replace(".", ",")