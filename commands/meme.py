from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from logger import log_func, log_error
import aiohttp
import random
import asyncio
from typing import Optional

router = Router()

async def get_meme_from_api() -> Optional[dict]:
    """Получить мем через API"""
    try:
        log_func("Попытка получить мем через API")
        
        # Используем бесплатный API для мемов
        url = "https://meme-api.com/gimme"
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    return {
                        "title": data.get("title", "Мем"),
                        "url": data.get("url", ""),
                        "author": data.get("author", "Неизвестно"),
                        "subreddit": data.get("subreddit", ""),
                        "source": "Reddit API"
                    }
                        
    except Exception as e:
        log_error(f"Ошибка при получении мема через API: {e}")
    
    return None

async def get_meme_from_local_cache() -> Optional[dict]:
    """Получить мем из локального кэша"""
    local_memes = [
        {
            "title": "Программист на работе",
            "url": "https://picsum.photos/400/300?random=1",
            "author": "Local Cache",
            "subreddit": "programming",
            "source": "Локальный кэш"
        },
        {
            "title": "Git в реальной жизни",
            "url": "https://picsum.photos/400/300?random=2", 
            "author": "Local Cache", 
            "subreddit": "programming",
            "source": "Локальный кэш"
        },
        {
            "title": "Python vs JavaScript",
            "url": "https://picsum.photos/400/300?random=3",
            "author": "Local Cache",
            "subreddit": "programming", 
            "source": "Локальный кэш"
        },
        {
            "title": "Отладка кода",
            "url": "https://picsum.photos/400/300?random=4",
            "author": "Local Cache",
            "subreddit": "programming",
            "source": "Локальный кэш"
        },
        {
            "title": "Комментарии в коде",
            "url": "https://picsum.photos/400/300?random=5",
            "author": "Local Cache",
            "subreddit": "programming",
            "source": "Локальный кэш"
        }
    ]
    
    return random.choice(local_memes)

async def get_random_meme() -> dict:
    """Получить случайный мем из любого доступного источника"""
    log_func("Запрос случайного мема")
    
    # Сначала пробуем API
    meme = await get_meme_from_api()
    if meme and meme.get('url'):
        # Проверяем, что URL выглядит валидным для изображения
        url = meme['url'].lower()
        if any(ext in url for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            log_func(f"API вернул валидный мем: {meme['title']}")
            return meme
        else:
            log_func(f"API вернул мем с невалидным URL: {meme['url']}, пробуем локальный кэш")
    
    # Если API не работает или вернул невалидный URL, берем из локального кэша
    meme = await get_meme_from_local_cache()
    if meme:
        log_func(f"Используем мем из локального кэша: {meme['title']}")
        return meme
    
    # Fallback
    log_func("Используем fallback мем")
    return {
        "title": "Мем недоступен",
        "url": "https://picsum.photos/400/300?random=999",
        "author": "System",
        "subreddit": "general",
        "source": "Fallback"
    }

@router.message(Command("meme"))
async def cmd_meme(message: Message):
    """Команда для получения случайного мема"""
    loading_msg = None
    try:
        log_func(f"Запрос мема от пользователя {message.from_user.id}")
        
        # Отправляем сообщение о загрузке
        loading_msg = await message.reply("🎭 Ищу для вас мем...")
        
        # Получаем мем
        meme_data = await get_random_meme()
        
        # Формируем сообщение
        response_text = (
            f"🎭 <b>Случайный мем</b>\n\n"
            f"📝 <b>{meme_data['title']}</b>\n"
            f"👤 <i>Автор: {meme_data['author']}</i>\n"
            f"📂 <i>Сообщество: r/{meme_data['subreddit']}</i>\n"
            f"📡 <i>Источник: {meme_data['source']}</i>"
        )
        
        # Удаляем сообщение о загрузке
        if loading_msg:
            try:
                await loading_msg.delete()
            except Exception:
                pass  # Игнорируем ошибки при удалении
        
        # Отправляем мем как фото с подписью
        try:
            await message.reply_photo(
                photo=meme_data['url'],
                caption=response_text,
                parse_mode="HTML"
            )
        except Exception as photo_error:
            log_error(f"Ошибка при отправке фото мема: {photo_error}")
            
            # Если это был API мем, пробуем локальный кэш
            if meme_data['source'] == "Reddit API":
                log_func("Пробуем локальный кэш после ошибки API")
                try:
                    local_meme = await get_meme_from_local_cache()
                    if local_meme:
                        local_response_text = (
                            f"🎭 <b>Случайный мем (локальный кэш)</b>\n\n"
                            f"📝 <b>{local_meme['title']}</b>\n"
                            f"👤 <i>Автор: {local_meme['author']}</i>\n"
                            f"📂 <i>Сообщество: r/{local_meme['subreddit']}</i>\n"
                            f"📡 <i>Источник: {local_meme['source']}</i>"
                        )
                        
                        await message.reply_photo(
                            photo=local_meme['url'],
                            caption=local_response_text,
                            parse_mode="HTML"
                        )
                        log_func(f"Локальный мем успешно отправлен пользователю {message.from_user.id}")
                        return
                except Exception as local_error:
                    log_error(f"Ошибка при отправке локального мема: {local_error}")
            
            # Если не удалось отправить как фото, отправляем как текст с ссылкой
            fallback_text = (
                f"🎭 <b>Случайный мем</b>\n\n"
                f"📝 <b>{meme_data['title']}</b>\n"
                f"👤 <i>Автор: {meme_data['author']}</i>\n"
                f"📂 <i>Сообщество: r/{meme_data['subreddit']}</i>\n"
                f"📡 <i>Источник: {meme_data['source']}</i>\n\n"
                f"🔗 <a href=\"{meme_data['url']}\">Ссылка на мем</a>"
            )
            await message.reply(fallback_text, parse_mode="HTML")
        
        log_func(f"Мем успешно отправлен пользователю {message.from_user.id}")
        
    except Exception as e:
        log_error(f"Ошибка при получении мема: {e}")
        error_text = (
            "😅 <b>Упс!</b>\n\n"
            "К сожалению, не удалось найти мем.\n"
            "Попробуйте позже! 😄"
        )
        
        # Проверяем, существует ли сообщение для редактирования
        if loading_msg:
            try:
                await loading_msg.edit_text(error_text, parse_mode="HTML")
            except Exception as edit_error:
                log_error(f"Ошибка при редактировании сообщения: {edit_error}")
                # Если не удалось отредактировать, отправляем новое сообщение
                try:
                    await message.reply(error_text, parse_mode="HTML")
                except Exception:
                    pass  # Игнорируем все ошибки
        else:
            try:
                await message.reply(error_text, parse_mode="HTML")
            except Exception:
                pass  # Игнорируем все ошибки 