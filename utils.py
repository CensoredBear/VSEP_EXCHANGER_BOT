"""
Утилиты для VSEPExchangerBot
"""
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup
from pydantic import ValidationError
from typing import Union, Dict

from logger import logger

async def safe_send_media_with_caption(
    bot: Bot, 
    chat_id: Union[int, str], 
    file_id: Dict[str, str], 
    caption: str, 
    parse_mode: str = 'HTML', 
    reply_markup: InlineKeyboardMarkup = None,
    reply_to_message_id: int = None
):
    """
    Tries to send a media file by file_id, first as video, then as photo.
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

        if media_type in ['video', 'animation']:
            try:
                await bot.send_video(chat_id, video=media_id, caption=caption, parse_mode=parse_mode, reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)
                return
            except TelegramBadRequest as e:
                if 'wrong file identifier' in e.message.lower() or 'wrong type of file' in e.message.lower():
                    logger.warning(f"[MEDIA_RETRY] Failed to send {media_id} as video, trying as photo. Error: {e.message}")
                else:
                    raise e
        
        await bot.send_photo(chat_id, photo=media_id, caption=caption, parse_mode=parse_mode, reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)

    except (TelegramBadRequest, ValidationError) as e:
        logger.error(f"[MEDIA_ERROR] Unexpected error with file_id {file_id}: {e}")
        logger.info(f"[MEDIA_FALLBACK] Sending text-only message to {chat_id} due to media error.")
        await bot.send_message(chat_id, caption, parse_mode=parse_mode, reply_markup=reply_markup, disable_web_page_preview=True, reply_to_message_id=reply_to_message_id)