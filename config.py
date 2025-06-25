import os
import json
from typing import Dict, Optional, TYPE_CHECKING
from datetime import datetime, time

from pydantic import BaseModel, SecretStr, Field
from dotenv import load_dotenv

# Этот блок нужен для подсказок типов и не вызывает циклического импорта
if TYPE_CHECKING:
    from db import db
    from logger import logger

# Определяем директорию бота
BOT_DIR = os.path.dirname(os.path.abspath(__file__))

class Config(BaseModel):
    """
    Класс для хранения конфигурации бота, загружаемой из .env файла.
    """
    # Загрузка переменных окружения
    load_dotenv()

    BOT_TOKEN: SecretStr = os.getenv('VSEP_BOT_TOKEN')
    ADMIN_GROUP: str = os.getenv('VSEP_ADMIN_GROUP')
    WORK_GROUP_MBT: str = os.getenv('VSEP_WORK_GROUP_MBT')
    WORK_GROUP_LGI: str = os.getenv('VSEP_WORK_GROUP_LGI')
    WORK_GROUP_TCT: str = os.getenv('VSEP_WORK_GROUP_TCT')
    CBCLUB_DB_URL: str = os.getenv('CBCLUB_DB_URL')
    GOOGLE_SHEETS_CREDENTIALS_PATH: str = os.getenv('GOOGLE_SHEETS_CREDENTIALS_PATH')
    GOOGLE_SHEETS_SPREADSHEET_URL: str = os.getenv('GOOGLE_SHEETS_SPREADSHEET_URL')
    GOOGLE_SHEETS_CHAT_TABLE_MAP: str = os.getenv('GOOGLE_SHEETS_CHAT_TABLE_MAP')
    PHOTO_ID: str = os.getenv('PHOTO_ID')
    LOG_FILE: str = os.getenv('LOG_FILE', os.path.join(BOT_DIR, 'logs', 'bot.log'))

class SystemSettings:
    """
    Класс для хранения системных настроек, загружаемых из базы данных.
    """
    shift_start_time: time = Field(default=time(9, 0))
    shift_end_time: time = Field(default=time(23, 0))
    night_shift_enabled: bool = Field(default=False)
    media_start: Optional[Dict[str, str]] = None
    media_finish: Optional[Dict[str, str]] = None
    media_mbt: Optional[Dict[str, str]] = None
    media_lgi: Optional[Dict[str, str]] = None
    media_tct: Optional[Dict[str, str]] = None
    # Флаги для отправки информационного сообщения
    send_info_mbt: bool = True
    send_info_lgi: bool = True
    send_info_tct: bool = True

    def __init__(self, **data):
        # Преобразуем строки времени в объекты time
        if 'shift_start_time' in data and isinstance(data['shift_start_time'], str):
            time_str = data['shift_start_time']
            try:
                # Пробуем сначала формат с секундами
                data['shift_start_time'] = datetime.strptime(time_str, '%H:%M:%S').time()
            except ValueError:
                # Если не получилось, пробуем формат без секунд
                data['shift_start_time'] = datetime.strptime(time_str, '%H:%M').time()
        
        if 'shift_end_time' in data and isinstance(data['shift_end_time'], str):
            time_str = data['shift_end_time']
            try:
                # Пробуем сначала формат с секундами
                data['shift_end_time'] = datetime.strptime(time_str, '%H:%M:%S').time()
            except ValueError:
                # Если не получилось, пробуем формат без секунд
                data['shift_end_time'] = datetime.strptime(time_str, '%H:%M').time()

        # Парсим медиа-настройки
        for key in ['media_start', 'media_finish', 'media_mbt', 'media_lgi', 'media_tct']:
            if key in data and isinstance(data[key], str):
                data[key] = self._parse_media_setting(data[key])

        # Обрабатываем булевы значения из строк
        def parse_bool(value) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ['true', '1', 'yes', 'on']
            return False

        # Устанавливаем остальные атрибуты
        self.shift_start_time = data.get('shift_start_time', time(9, 0))
        self.shift_end_time = data.get('shift_end_time', time(23, 0))
        self.night_shift_enabled = parse_bool(data.get('night_shift_enabled', False))
        self.media_start = data.get('media_start')
        self.media_finish = data.get('media_finish')
        self.media_mbt = data.get('media_mbt')
        self.media_lgi = data.get('media_lgi')
        self.media_tct = data.get('media_tct')
        self.send_info_mbt = parse_bool(data.get('send_info_mbt', True))
        self.send_info_lgi = parse_bool(data.get('send_info_lgi', True))
        self.send_info_tct = parse_bool(data.get('send_info_tct', True))

    def _parse_media_setting(self, value: str) -> dict | None:
        """Парсит настройку медиа, поддерживая старый и новый формат."""
        if not value:
            return None
        try:
            # Новый формат: JSON-строка {'id': '...', 'type': '...'}
            media_info = json.loads(value)
            if isinstance(media_info, dict) and 'id' in media_info and 'type' in media_info:
                return media_info
        except (json.JSONDecodeError, TypeError):
            # Старый формат: просто file_id
            return {'id': value, 'type': 'photo'} # По умолчанию считаем фото
        return None

    async def load(self) -> bool:
        """
        Перезагружает настройки из базы данных.
        Возвращает True, если настройки найдены и загружены, иначе False.
        """
        from db import db
        from logger import logger
        settings_data = await db.get_all_system_settings()
        if not settings_data:
            logger.warning("SystemSettings.load: Настройки в базе данных не найдены.")
            return False
            
        self.__init__(**settings_data)
        logger.info("Системные настройки перезагружены.")
        return True

async def load_system_settings() -> "SystemSettings":
    """Асинхронно загружает системные настройки из базы данных."""
    from db import db
    settings_data = await db.get_all_system_settings()
    return SystemSettings(**settings_data)

# Создаем экземпляр конфигурации
config = Config()

# Создаем экземпляр системных настроек
system_settings = SystemSettings()