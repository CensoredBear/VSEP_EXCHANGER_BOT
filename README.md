# VSEP Exchanger Bot

Независимый Telegram бот для обмена валют VSEP.

## 🚀 Быстрый старт

### Локальная разработка

1. **Клонируйте репозиторий:**
   ```bash
   git clone <your-repo-url>
   cd VSEPExchangerBot_Standalone
   ```

2. **Создайте виртуальное окружение:**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Настройте переменные окружения:**
   ```bash
   copy env_example.txt .env
   # Отредактируйте .env файл с вашими настройками
   ```

5. **Запустите бота:**
   ```bash
   python main.py
   ```

### Деплой на Heroku

1. **Создайте приложение на Heroku:**
   ```bash
   heroku create your-app-name
   ```

2. **Добавьте PostgreSQL базу данных:**
   ```bash
   heroku addons:create heroku-postgresql:mini
   ```

3. **Настройте переменные окружения:**
   ```bash
   heroku config:set VSEP_BOT_TOKEN=your_bot_token
   heroku config:set VSEP_ADMIN_GROUP=@your_admin_group
   heroku config:set VSEP_WORK_GROUP_MBT=@your_work_group_mbt
   heroku config:set VSEP_WORK_GROUP_LGI=@your_work_group_lgi
   heroku config:set VSEP_WORK_GROUP_TCT=@your_work_group_tct
   heroku config:set CBCLUB_DB_URL=your_database_url
   ```

4. **Деплойте приложение:**
   ```bash
   git add .
   git commit -m "Initial commit"
   git push heroku main
   ```

## 📁 Структура проекта

```
VSEPExchangerBot_Standalone/
├── main.py              # Главный файл бота
├── config.py            # Конфигурация
├── db.py                # Работа с базой данных
├── handlers.py          # Обработчики команд
├── scheduler.py         # Планировщик задач
├── requirements.txt     # Зависимости Python
├── Procfile            # Конфигурация Heroku
├── runtime.txt         # Версия Python
├── .env                # Переменные окружения
├── procedures/         # Процедуры обработки
├── media/              # Медиа файлы
└── logs/               # Логи
```

## 🔧 Конфигурация

### Обязательные переменные окружения:

- `VSEP_BOT_TOKEN` - Токен Telegram бота
- `VSEP_ADMIN_GROUP` - ID админ группы
- `VSEP_WORK_GROUP_MBT` - ID рабочей группы MBT
- `VSEP_WORK_GROUP_LGI` - ID рабочей группы LGI
- `VSEP_WORK_GROUP_TCT` - ID рабочей группы TCT
- `CBCLUB_DB_URL` - URL базы данных PostgreSQL

### Опциональные переменные:

- `GOOGLE_SHEETS_CREDENTIALS_PATH` - Путь к Google Sheets credentials
- `GOOGLE_SHEETS_SPREADSHEET_URL` - URL Google таблицы
- `PHOTO_ID` - ID фото для бота
- `LOG_FILE` - Путь к файлу логов

## 📝 Логирование

Логи сохраняются в папку `logs/` и содержат:
- Информацию о запуске/остановке бота
- Ошибки и исключения
- Действия пользователей
- Системные события

## 🤝 Поддержка

При возникновении проблем:
1. Проверьте логи в папке `logs/`
2. Убедитесь, что все переменные окружения настроены
3. Проверьте подключение к базе данных

## 📄 Лицензия

Этот проект является частью VSEP Exchange системы.

## Универсальная функция отправки сообщений

В проекте используется универсальная функция `send_message` (см. `messages.py`), которая позволяет отправлять любые сообщения:
- обычные
- с автоудалением через N секунд
- как ответ на другое сообщение
- в тред/тему
- с клавиатурой
- с задержкой отправки
- пересылка сообщений
- любые параметры aiogram

### Пример использования:
```python
from messages import send_message

# Обычное сообщение
await send_message(bot, chat_id, "Привет!")

# Сообщение с автоудалением
await send_message(bot, chat_id, "Временное!", delete_after=10)

# Ответ на сообщение
await send_message(bot, chat_id, "Ответ!", reply_to_message_id=msg_id)

# С задержкой
await send_message(bot, chat_id, "Через 5 секунд", delay=5)

# Пересылка
await send_message(bot, chat_id, forward_from_chat_id=from_id, forward_message_id=msg_id)
```

## Функция времени для сообщений

Для вставки времени события по Бали и Москве используйте функцию:
```python
from messages import get_bali_and_msk_time_str

text = f"...\n{get_bali_and_msk_time_str()}"
```

---

**Рекомендуется использовать эти функции для всех отправок сообщений в проекте!**

---

## Модуль логирования истории чатов

В проекте есть отдельный модуль `chat_logger.py` для логирования всей истории переписки в чатах:
- отправка сообщений
- редактирование
- удаление
- пересылка
- вложения (фото, документы и т.д.)

Логи выводятся в файл `chat_history.log` (через FileHandler) и в консоль (StreamHandler) для отображения в чате.

### Пример использования:
```python
from chat_logger import log_message

# Логируем отправку сообщения
log_message("send", chat, user, text="Привет!")

# Логируем редактирование
log_message("edit", chat, user, old_text="Старый текст", new_text="Новый текст")

# Логируем удаление
log_message("delete", chat, user, text="Удалённый текст")

# Логируем вложение
log_message("attachment", chat, user, file_type="фото", file_id="AgACAgIAAxkBAA...")
```

### Пример вывода в чате (StreamHandler):
```
[09.06.2024 19:30:00 (Bali) / 09.06.2024 19:30:00 (MSK)] 📝 [chat: 123456 | My Chat] [user: @user (123)] отправил сообщение:
"Привет!"
```

---

**Используйте log_message для фиксации всех событий в чатах!** 