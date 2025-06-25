from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

class CallbackInitiatorGuard(BaseMiddleware):
    async def __call__(self, handler, event: CallbackQuery, data):
        if event.data and event.data.count(":") > 0:
            *_, maybe_id = event.data.split(":")
            if maybe_id.isdigit():
                initiator_id = int(maybe_id)
                if event.from_user.id != initiator_id:
                    await event.answer("Это не ваша кнопка — так не работает", show_alert=True)
                    return
        return await handler(event, data) 