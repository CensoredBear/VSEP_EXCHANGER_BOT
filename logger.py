import logging
import sys
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config import config

# Создаём директорию для логов по абсолютному пути из config.LOG_FILE
log_dir = Path(config.LOG_FILE).parent
log_dir.mkdir(parents=True, exist_ok=True)

# Категории логов
class LogCategory:
    SYSTEM = "SYSTEM"
    USER = "USER"
    DB = "DB"
    FUNC = "FUNC"
    INFO = "INFO"

# Настройка форматирования
class CustomFormatter(logging.Formatter):
    """Форматтер с цветами для консоли"""
    
    # Проверяем, нужно ли использовать цвета
    use_colors = not os.getenv('NO_COLOR') and sys.stdout.isatty()
    
    grey = "\x1b[38;21m" if use_colors else ""
    blue = "\x1b[38;5;39m" if use_colors else ""
    yellow = "\x1b[38;5;226m" if use_colors else ""
    red = "\x1b[38;5;196m" if use_colors else ""
    bold_red = "\x1b[31;1m" if use_colors else ""
    reset = "\x1b[0m" if use_colors else ""

    def __init__(self, fmt):
        super().__init__()
        self.fmt = fmt
        self.FORMATS = {
            logging.DEBUG: self.grey + self.fmt + self.reset,
            logging.INFO: self.blue + self.fmt + self.reset,
            logging.WARNING: self.yellow + self.fmt + self.reset,
            logging.ERROR: self.red + self.fmt + self.reset,
            logging.CRITICAL: self.bold_red + self.fmt + self.reset
        }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)

def setup_logger():
    # Создаем логгер
    logger = logging.getLogger('VSEPExchangerBot')
    logger.setLevel(logging.DEBUG)

    # Формат для файла (как в VSEPProgramsBot)
    file_formatter = logging.Formatter(
        '%(asctime)s [%(name)s] [%(levelname)s] (%(filename)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Проверяем, нужно ли использовать цвета
    use_colors = not os.getenv('NO_COLOR') and sys.stdout.isatty()
    
    if use_colors:
        # Формат для консоли с цветами (локальная разработка)
        console_formatter = CustomFormatter(
            '%(asctime)s [%(name)s] [%(levelname)s] (%(filename)s:%(lineno)d) - %(message)s'
        )
    else:
        # Простой формат для Heroku без цветов
        console_formatter = logging.Formatter(
            '%(asctime)s [%(name)s] [%(levelname)s] (%(filename)s:%(lineno)d) - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    # Хендлер для файла (все логи)
    file_handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8',
        mode='a'
    )
    file_handler.setLevel(logging.NOTSET)  # Пишем вообще всё
    file_handler.setFormatter(file_formatter)

    # Хендлер для консоли (все логи)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    # Очищаем старые хендлеры
    logger.handlers.clear()
    # Добавляем хендлеры к логгеру
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# Создаем глобальный логгер
logger = setup_logger()

# Функции для логирования с категориями
def log_system(message, level=logging.INFO):
    logger.log(level, message, extra={'category': LogCategory.SYSTEM})

def log_user(message, level=logging.INFO):
    logger.log(level, message, extra={'category': LogCategory.USER})

def log_db(message, level=logging.INFO):
    logger.log(level, message, extra={'category': LogCategory.DB})

def log_func(message, level=logging.INFO):
    logger.log(level, message, extra={'category': LogCategory.FUNC})

def log_info(message, level=logging.INFO):
    logger.log(level, message, extra={'category': LogCategory.INFO})

def log_warning(message):
    logger.warning(message, extra={'category': LogCategory.SYSTEM})

def log_error(message):
    logger.error(message, extra={'category': LogCategory.SYSTEM}) 