# 🚀 Пошаговая инструкция по настройке VSEP Exchanger Bot

## 📋 Что нужно сделать

### 1. Подготовка к деплою

#### 1.1 Установите Heroku CLI
- Скачайте с [heroku.com/cli](https://devcenter.heroku.com/articles/heroku-cli)
- Установите и войдите в аккаунт:
```bash
heroku login
```

#### 1.2 Установите Git (если не установлен)
- Скачайте с [git-scm.com](https://git-scm.com/)
- Настройте имя и email:
```bash
git config --global user.name "Ваше имя"
git config --global user.email "ваш@email.com"
```

### 2. Настройка переменных окружения

#### 2.1 Отредактируйте файл .env
Откройте файл `.env` и заполните следующие поля:

```env
# Bot Token (получите у @BotFather)
VSEP_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# Chat IDs (ID ваших групп)
VSEP_ADMIN_GROUP=@your_admin_group
VSEP_WORK_GROUP_MBT=@your_work_group_mbt
VSEP_WORK_GROUP_LGI=@your_work_group_lgi
VSEP_WORK_GROUP_TCT=@your_work_group_tct

# Database URL (будет получен от Heroku)
CBCLUB_DB_URL=postgresql://user:password@host/database

# Google Sheets (опционально)
GOOGLE_SHEETS_CREDENTIALS_PATH=credentials.json
GOOGLE_SHEETS_SPREADSHEET_URL=https://docs.google.com/spreadsheets/d/your_sheet_id
GOOGLE_SHEETS_CHAT_TABLE_MAP=chat_table_map
GOOGLE_TABLE_CREDS={"type": "service_account"}

# Other
PHOTO_ID=your_photo_id
LOG_FILE=logs/bot.log
```

### 3. Создание приложения на Heroku

#### 3.1 Создайте новое приложение
```bash
heroku create your-vsep-bot-name
```

#### 3.2 Добавьте PostgreSQL базу данных
```bash
heroku addons:create heroku-postgresql:mini
```

#### 3.3 Получите URL базы данных
```bash
heroku config:get DATABASE_URL
```

### 4. Настройка переменных окружения на Heroku

#### 4.1 Установите все переменные
```bash
# Основные настройки
heroku config:set VSEP_BOT_TOKEN="ваш_токен_бота"
heroku config:set VSEP_ADMIN_GROUP="@ваша_админ_группа"
heroku config:set VSEP_WORK_GROUP_MBT="@ваша_рабочая_группа_mbt"
heroku config:set VSEP_WORK_GROUP_LGI="@ваша_рабочая_группа_lgi"
heroku config:set VSEP_WORK_GROUP_TCT="@ваша_рабочая_группа_tct"

# База данных (URL получите из шага 3.3)
heroku config:set CBCLUB_DB_URL="postgresql://user:password@host/database"

# Google Sheets (если используете)
heroku config:set GOOGLE_SHEETS_CREDENTIALS_PATH="credentials.json"
heroku config:set GOOGLE_SHEETS_SPREADSHEET_URL="https://docs.google.com/spreadsheets/d/your_sheet_id"
heroku config:set GOOGLE_SHEETS_CHAT_TABLE_MAP="chat_table_map"
heroku config:set GOOGLE_TABLE_CREDS='{"type": "service_account"}'

# Дополнительные настройки
heroku config:set PHOTO_ID="ваш_photo_id"
heroku config:set LOG_FILE="logs/bot.log"
```

#### 4.2 Проверьте настройки
```bash
heroku config
```

### 5. Деплой приложения

#### 5.1 Первый деплой
```bash
# Добавьте все файлы в Git
git add .

# Создайте первый коммит
git commit -m "Initial commit"

# Отправьте на Heroku
git push heroku main
```

#### 5.2 Проверьте логи
```bash
heroku logs --tail
```

### 6. Проверка работы

#### 6.1 Откройте приложение
```bash
heroku open
```

#### 6.2 Проверьте статус
```bash
heroku ps
```

#### 6.3 Перезапустите при необходимости
```bash
heroku restart
```

## 🔧 Полезные команды

### Просмотр логов
```bash
# Все логи
heroku logs

# Логи в реальном времени
heroku logs --tail

# Последние 100 строк
heroku logs -n 100
```

### Управление приложением
```bash
# Статус приложения
heroku ps

# Перезапуск
heroku restart

# Остановка
heroku ps:scale worker=0

# Запуск
heroku ps:scale worker=1
```

### Переменные окружения
```bash
# Просмотр всех переменных
heroku config

# Установка переменной
heroku config:set VARIABLE_NAME="value"

# Удаление переменной
heroku config:unset VARIABLE_NAME
```

## 🚨 Решение проблем

### Бот не отвечает
1. Проверьте логи: `heroku logs --tail`
2. Убедитесь, что токен бота правильный
3. Проверьте, что бот не заблокирован

### Ошибки базы данных
1. Проверьте URL базы данных: `heroku config:get DATABASE_URL`
2. Убедитесь, что PostgreSQL добавлен: `heroku addons`
3. Перезапустите приложение: `heroku restart`

### Проблемы с деплоем
1. Проверьте Procfile: должен содержать `worker: python main.py`
2. Убедитесь, что requirements.txt актуален
3. Проверьте runtime.txt: должна быть указана версия Python

## 📞 Поддержка

Если что-то не работает:
1. Проверьте логи: `heroku logs --tail`
2. Убедитесь, что все переменные окружения настроены
3. Проверьте, что база данных подключена
4. Перезапустите приложение: `heroku restart` 