from aiogram import BaseMiddleware
from aiogram.types import Message
from db import db
from logger import logger, log_system, log_user, log_func, log_warning, log_error
from typing import Callable, Dict, Any, Awaitable
from aiogram.types import CallbackQuery, ChatMemberUpdated
from chat_logger import log_message

class UserSaveMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.from_user:
            user = event.from_user
            # log_func(f"Проверка пользователя: id={user.id}, username={user.username}")
            await db.add_user_if_not_exists(user.id, user.username or user.full_name or "unknown")
        return await handler(event, data)

class ChatLoggerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery | ChatMemberUpdated,
        data: Dict[str, Any]
    ) -> Any:
        try:
            if isinstance(event, Message):
                log_message("message", event.chat, event.from_user, text=event.text or f"<{event.content_type}>")
            elif isinstance(event, CallbackQuery):
                if event.message:
                    log_message("callback", event.message.chat, event.from_user, text=f"callback: {event.data}")
            elif isinstance(event, ChatMemberUpdated):
                action = "присоединился" if event.new_chat_member.status in ["member", "administrator", "creator"] else "покинул"
                log_message("chat_action", event.chat, event.new_chat_member.user, text=f"пользователь {action} чат")
        except Exception as e:
            logger.error(f"Error in ChatLoggerMiddleware: {e}")
        
        return await handler(event, data) 