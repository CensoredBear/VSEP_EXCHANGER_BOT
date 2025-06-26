"""
Joke Parser Module
==================
Модуль для парсинга анекдотов из различных источников
"""
import aiohttp
import asyncio
import random
from typing import Optional, List, Dict, Any
from logger import logger, log_func, log_error
import re
from bs4 import BeautifulSoup
import json


class JokeParser:
    """Класс для парсинга анекдотов из различных источников"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: List[str] = []
        self.cache_size = 50
        
    async def __aenter__(self):
        """Асинхронный контекстный менеджер - вход"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный контекстный менеджер - выход"""
        if self.session:
            await self.session.close()
    
    async def get_joke_from_anekdot_ru(self) -> Optional[str]:
        """Получить анекдот с anekdot.ru"""
        try:
            log_func("Попытка получить анекдот с anekdot.ru")
            
            # Получаем случайную страницу с анекдотами
            page = random.randint(1, 100)
            url = f"https://www.anekdot.ru/random/anekdot/"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Ищем анекдоты в тексте
                    jokes = soup.find_all('div', class_='text')
                    if jokes:
                        joke = random.choice(jokes).get_text(strip=True)
                        if joke and len(joke) > 20:  # Проверяем, что анекдот не слишком короткий
                            return joke
                            
        except Exception as e:
            log_error(f"Ошибка при получении анекдота с anekdot.ru: {e}")
        
        return None
    
    async def get_joke_from_anekdot_me(self) -> Optional[str]:
        """Получить анекдот с anekdot.me"""
        try:
            log_func("Попытка получить анекдот с anekdot.me")
            
            url = "https://anekdot.me/random"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Ищем анекдоты
                    jokes = soup.find_all('div', class_='anekdot')
                    if jokes:
                        joke = random.choice(jokes).get_text(strip=True)
                        if joke and len(joke) > 20:
                            return joke
                            
        except Exception as e:
            log_error(f"Ошибка при получении анекдота с anekdot.me: {e}")
        
        return None
    
    async def get_joke_from_api(self) -> Optional[str]:
        """Получить анекдот через API"""
        try:
            log_func("Попытка получить анекдот через API")
            
            # Используем бесплатный API для анекдотов
            url = "https://v2.jokeapi.dev/joke/Any?lang=ru&safe-mode"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('type') == 'single':
                        joke = data.get('joke', '')
                    elif data.get('type') == 'twopart':
                        setup = data.get('setup', '')
                        delivery = data.get('delivery', '')
                        joke = f"{setup}\n\n{delivery}"
                    else:
                        return None
                    
                    if joke and len(joke) > 20:
                        return joke
                        
        except Exception as e:
            log_error(f"Ошибка при получении анекдота через API: {e}")
        
        return None
    
    async def get_joke_from_local_cache(self) -> Optional[str]:
        """Получить анекдот из локального кэша"""
        if self.cache:
            return random.choice(self.cache)
        return None
    
    def add_to_cache(self, joke: str):
        """Добавить анекдот в кэш"""
        if joke not in self.cache:
            self.cache.append(joke)
            if len(self.cache) > self.cache_size:
                self.cache.pop(0)  # Удаляем самый старый
    
    async def get_random_joke(self) -> str:
        """Получить случайный анекдот из любого доступного источника"""
        log_func("Запрос случайного анекдота")
        
        # Сначала пробуем из кэша
        joke = await self.get_joke_from_local_cache()
        if joke:
            return joke
        
        # Список источников в порядке приоритета
        sources = [
            self.get_joke_from_api,
            self.get_joke_from_anekdot_ru,
            self.get_joke_from_anekdot_me,
        ]
        
        # Перемешиваем источники для разнообразия
        random.shuffle(sources)
        
        for source_func in sources:
            try:
                joke = await source_func()
                if joke:
                    self.add_to_cache(joke)
                    return joke
            except Exception as e:
                log_error(f"Ошибка при получении анекдота из {source_func.__name__}: {e}")
                continue
        
        # Если ничего не получилось, возвращаем запасной анекдот
        fallback_jokes = [
            "Программист заходит в лифт, а там написано JS... Он сразу понял, что что-то пойдет не так! 😄",
            "Почему программисты путают Рождество и Хэллоуин? Потому что Oct 31 == Dec 25! 🎃",
            "Как программист ломает голову? Git push --force! 💻",
            "Почему Python-разработчики носят очки? Потому что они не могут C#! 🐍",
            "Что сказал программист на свадьбе? 'Да, я согласен' (while true) 💍"
        ]
        
        return random.choice(fallback_jokes)


# Глобальный экземпляр парсера
joke_parser: Optional[JokeParser] = None


async def get_joke() -> str:
    """Получить анекдот (глобальная функция для удобства)"""
    global joke_parser
    
    if joke_parser is None:
        joke_parser = JokeParser()
    
    async with joke_parser as parser:
        return await parser.get_random_joke()


async def get_joke_with_source() -> Dict[str, Any]:
    """Получить анекдот с информацией об источнике"""
    joke = await get_joke()
    
    # Определяем источник по содержимому
    if "программист" in joke.lower() or "git" in joke.lower() or "python" in joke.lower():
        source = "Локальный кэш (программистские шутки)"
    elif "jokeapi" in joke.lower():
        source = "JokeAPI"
    else:
        source = "Внешний источник"
    
    return {
        "joke": joke,
        "source": source,
        "timestamp": asyncio.get_event_loop().time()
    } 