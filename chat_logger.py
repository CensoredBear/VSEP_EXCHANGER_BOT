import logging
from datetime import datetime
import pytz
import os
from messages import get_bali_and_msk_time_list
from logger import log_user, LogCategory

def get_time_str():
    """Получить строку с временем в формате Бали/МСК"""
    times = get_bali_and_msk_time_list()
    return f"{times[6]} (Bali) / {times[5]} (MSK)"

# Определяем путь к файлу лога в директории бота
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BOT_DIR, "chat_history.log")

chat_logger = logging.getLogger("chat_history")
chat_logger.setLevel(logging.INFO)

# Удаляем старые хендлеры (если есть)
for hdlr in chat_logger.handlers[:]:
    chat_logger.removeHandler(hdlr)

# Логируем только в файл (chat_history.log)
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("--- Лог истории чатов ---\n")

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_formatter = logging.Formatter("%(message)s")
file_handler.setFormatter(file_formatter)
chat_logger.addHandler(file_handler)

def log_message(event_type, chat, user, text=None, old_text=None, new_text=None, file_type=None, file_id=None):
    """Логирование сообщений в чате"""
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Определяем эмодзи для типа события
    emoji = {
        "send": "📝",
        "edit": "✏️",
        "delete": "🗑️",
        "forward": "↪️",
        "attachment": "📎",
        "callback": "🔘",
        "chat_action": "👥",
        "unknown": "❓"
    }.get(event_type, "❓")
    
    # Формируем информацию о чате
    chat_info = f"[{chat.title if hasattr(chat, 'title') else 'Private'}]"
    
    # Формируем информацию о пользователе
    user_info = f"@{user.username}" if user.username else f"{user.full_name} (ID: {user.id})"
    
    # Формируем сообщение в зависимости от типа события
    if event_type == "send":
        msg = f"[{time_str}] {emoji} {chat_info} {user_info} отправил сообщение:\n\"{text}\"\n"
    elif event_type == "edit":
        msg = f"[{time_str}] {emoji} {chat_info} {user_info} изменил сообщение:\n\"{old_text}\" -> \"{new_text}\"\n"
    elif event_type == "delete":
        msg = f"[{time_str}] {emoji} {chat_info} {user_info} удалил сообщение:\n\"{text}\"\n"
    elif event_type == "forward":
        msg = f"[{time_str}] {emoji} {chat_info} {user_info} переслал сообщение:\n\"{text}\"\n"
    elif event_type == "attachment":
        msg = f"[{time_str}] {emoji} {chat_info} {user_info} отправил вложение: {file_type}\nfile_id: {file_id}\n"
    elif event_type == "callback":
        msg = f"[{time_str}] {emoji} {chat_info} {user_info} нажал кнопку: {text}\n"
    elif event_type == "chat_action":
        msg = f"[{time_str}] {emoji} {chat_info} {user_info} {text}\n"
    else:
        msg = f"[{time_str}] {emoji} {chat_info} {user_info} событие: {event_type}\n"
    
    # Логируем в файл истории чатов
    chat_logger.info(msg)
    
    # Логируем в основной лог с категорией USER
    log_user(msg) 