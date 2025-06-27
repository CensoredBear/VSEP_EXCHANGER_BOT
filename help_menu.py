from typing import List
from aiogram.types import BotCommand

HELP_COMMANDS = {
    "user": [
        ("/start", "Запустить бота"),
        ("/help", "Показать справку"),
        ("/balance", "Проверить баланс"),
        ("/exchange", "Обменять валюту"),
        ("/history", "История операций"),
        ("/sos", "Связаться с поддержкой"),
        ("/control", "Запросить контроль оплаты"),
        ("/joke", "Получить случайный анекдот"),
        ("/dice", "Бросить кубик"),
        ("/coin", "Подбросить монетку"),
        ("/meme", "Получить случайный мем")
    ],
    "operator": [
        ("/start", "Запустить бота"),
        ("/help", "Показать справку"),
        ("/balance", "Проверить баланс"),
        ("/exchange", "Обменять валюту"),
        ("/history", "История операций"),
        ("/support", "Связаться с поддержкой"),
        ("/confirm", "Подтвердить заявку"),
        ("/reject", "Отклонить заявку"),
        ("/report", "Получить отчет"),
        ("/joke", "Получить случайный анекдот"),
        ("/dice", "Бросить кубик"),
        ("/coin", "Подбросить монетку"),
        ("/meme", "Получить случайный мем")
    ],
    "admin": [
        ("/start", "Запустить бота"),
        ("/help", "Показать справку"),
        ("/balance", "Проверить баланс"),
        ("/exchange", "Обменять валюту"),
        ("/history", "История операций"),
        ("/support", "Связаться с поддержкой"),
        ("/confirm", "Подтвердить заявку"),
        ("/reject", "Отклонить заявку"),
        ("/report", "Получить отчет"),
        ("/users", "Управление пользователями"),
        ("/settings", "Настройки бота"),
        ("/broadcast", "Рассылка сообщений"),
        ("/stats", "Статистика бота"),
        ("/joke", "Получить случайный анекдот"),
        ("/dice", "Бросить кубик"),
        ("/coin", "Подбросить монетку"),
        ("/meme", "Получить случайный мем"),
        ("/order_show", "Показать информацию о заявке"),
        ("/order_change", "Изменить статус заявки"),
        ("/transfer", "Подтвердить перевод средств")
    ],
    "superadmin": [
        ("/start", "Запустить бота"),
        ("/help", "Показать справку"),
        ("/balance", "Проверить баланс"),
        ("/exchange", "Обменять валюту"),
        ("/history", "История операций"),
        ("/support", "Связаться с поддержкой"),
        ("/confirm", "Подтвердить заявку"),
        ("/reject", "Отклонить заявку"),
        ("/report", "Получить отчет"),
        ("/users", "Управление пользователями"),
        ("/settings", "Настройки бота"),
        ("/broadcast", "Рассылка сообщений"),
        ("/stats", "Статистика бота"),
        ("/restart", "Перезапустить бота"),
        ("/worktime", "Изменить рабочее время смены"),
        ("/work_open", "Принудительно открыть смену (только для суперадмина)"),
        ("/work_close", "Принудительно закрыть смену (только для суперадмина)"),
        ("/reset_control", "Сбросить счетчик контроля для текущего чата (только для суперадмина)"),
        ("/set_media_mbt", "Установить медиа для MBT (фото/видео)"),
        ("/set_media_start", "Установить медиа для начала смены (фото/видео)"),
        ("/set_media_finish", "Установить медиа для окончания смены (фото/видео)"),
        ("/toggle_info_mbt", "Включить/выключить информационное сообщение для MBT"),
        ("/toggle_info_lgi", "Включить/выключить информационное сообщение для LGI"),
        ("/toggle_info_tct", "Включить/выключить информационное сообщение для TCT"),
        ("/joke", "Получить случайный анекдот"),
        ("/dice", "Бросить кубик"),
        ("/coin", "Подбросить монетку"),
        ("/meme", "Получить случайный мем")
    ]
}

STATUS_ORDER = ["user", "operator", "admin", "superadmin"]

def get_help_commands_for_status(status):
    """Вернуть список команд для help-меню и меню Telegram по статусу"""
    commands = []
    for s in STATUS_ORDER:
        commands += HELP_COMMANDS.get(s, [])
        if s == status:
            break
    return commands

def build_help_text(status):
    """Сформировать help-текст для пользователя по статусу"""
    commands = get_help_commands_for_status(status)
    text = f"Доступные команды для статуса {status} (и ниже):\n"
    for cmd, desc in commands:
        text += f"{cmd} — {desc}\n"
    return text

def get_bot_commands_for_status(status: str) -> List[BotCommand]:
    """Получение списка команд бота в зависимости от статуса пользователя"""
    if status == "superadmin":
        return [
            BotCommand(command="start", description="Начало работы с ботом"),
            BotCommand(command="help", description="Показать справку по командам"),
            BotCommand(command="check", description="Проверить статус заявки"),
            BotCommand(command="sos", description="Отправить SOS в админскую группу"),
            BotCommand(command="accept", description="Подтвердить оплату"),
            BotCommand(command="control", description="Запросить контроль оплаты"),
            BotCommand(command="bank_show", description="Показать реквизиты"),
            BotCommand(command="rate_show", description="Показать курсы"),
            BotCommand(command="admin_show", description="Показать список админов"),
            BotCommand(command="admin_add", description="Добавить админа"),
            BotCommand(command="admin_remove", description="Удалить админа"),
            BotCommand(command="operator_add", description="Добавить оператора"),
            BotCommand(command="operator_remove", description="Удалить оператора"),
            BotCommand(command="operator_show", description="Показать список операторов"),
            BotCommand(command="rate_change", description="Изменить курс"),
            BotCommand(command="cancel", description="Отменить текущее действие"),
            BotCommand(command="report", description="Показать отчет"),
            BotCommand(command="status", description="Показать статус"),
            BotCommand(command="order_show", description="Показать заявку"),
            BotCommand(command="order_change", description="Изменить статус заявки"),
            BotCommand(command="transfer", description="Перевод средств"),
            BotCommand(command="restart", description="Перезапустить бота"),
            BotCommand(command="reset_control", description="Сбросить счетчик контроля для текущего чата"),
            BotCommand(command="set_media_mbt", description="Установить медиа для MBT (фото/видео)"),
            BotCommand(command="set_media_start", description="Установить медиа для начала смены (фото/видео)"),
            BotCommand(command="set_media_finish", description="Установить медиа для окончания смены (фото/видео)"),
            BotCommand(command="toggle_info_mbt", description="Включить/выключить информационное сообщение для MBT"),
            BotCommand(command="toggle_info_lgi", description="Включить/выключить информационное сообщение для LGI"),
            BotCommand(command="toggle_info_tct", description="Включить/выключить информационное сообщение для TCT"),
            BotCommand(command="zombie", description="Оживить заявку из архива"),
            BotCommand(command="joke", description="Получить случайный анекдот"),
            BotCommand(command="dice", description="Бросить кубик"),
            BotCommand(command="coin", description="Подбросить монетку"),
            BotCommand(command="meme", description="Получить случайный мем")
        ]
    elif status == "admin":
        return [
            BotCommand(command="start", description="Начало работы с ботом"),
            BotCommand(command="help", description="Показать справку по командам"),
            BotCommand(command="check", description="Проверить статус заявки"),
            BotCommand(command="sos", description="Отправить SOS в админскую группу"),
            BotCommand(command="accept", description="Подтвердить оплату"),
            BotCommand(command="control", description="Запросить контроль оплаты"),
            BotCommand(command="bank_show", description="Показать реквизиты"),
            BotCommand(command="rate_show", description="Показать курсы"),
            BotCommand(command="operator_add", description="Добавить оператора"),
            BotCommand(command="operator_remove", description="Удалить оператора"),
            BotCommand(command="operator_show", description="Показать список операторов"),
            BotCommand(command="rate_change", description="Изменить курс"),
            BotCommand(command="report", description="Показать отчет"),
            BotCommand(command="status", description="Показать статус"),
            BotCommand(command="order_show", description="Показать заявку"),
            BotCommand(command="order_change", description="Изменить статус заявки"),
            BotCommand(command="transfer", description="Перевод средств"),
            BotCommand(command="zombie", description="Оживить заявку из архива"),
            BotCommand(command="joke", description="Получить случайный анекдот"),
            BotCommand(command="dice", description="Бросить кубик"),
            BotCommand(command="coin", description="Подбросить монетку"),
            BotCommand(command="meme", description="Получить случайный мем")
        ]
    elif status == "operator":
        return [
            BotCommand(command="start", description="Начало работы с ботом"),
            BotCommand(command="help", description="Показать справку по командам"),
            BotCommand(command="check", description="Проверить статус заявки"),
            BotCommand(command="sos", description="Отправить SOS в админскую группу"),
            BotCommand(command="accept", description="Подтвердить оплату"),
            BotCommand(command="control", description="Запросить контроль оплаты"),
            BotCommand(command="bank_show", description="Показать реквизиты"),
            BotCommand(command="rate_show", description="Показать курсы"),
            BotCommand(command="report", description="Показать отчет"),
            BotCommand(command="status", description="Показать статус"),
            BotCommand(command="order_show", description="Показать заявку"),
            BotCommand(command="order_change", description="Изменить статус заявки"),
            BotCommand(command="transfer", description="Перевод средств"),
            BotCommand(command="zombie", description="Оживить заявку из архива"),
            BotCommand(command="joke", description="Получить случайный анекдот"),
            BotCommand(command="dice", description="Бросить кубик"),
            BotCommand(command="coin", description="Подбросить монетку"),
            BotCommand(command="meme", description="Получить случайный мем")
        ]
    else:  # user
        return [
            BotCommand(command="start", description="Начало работы с ботом"),
            BotCommand(command="help", description="Показать справку по командам"),
            BotCommand(command="sos", description="Отправить SOS в админскую группу"),
            BotCommand(command="control", description="Запросить контроль оплаты"),
            BotCommand(command="joke", description="Получить случайный анекдот"),
            BotCommand(command="dice", description="Бросить кубик"),
            BotCommand(command="coin", description="Подбросить монетку"),
            BotCommand(command="meme", description="Получить случайный мем")
        ]

def build_pretty_help_text(status):
    """Сформировать красивый help-текст с разделами по статусу пользователя"""
    sections = [
        ("user", "<u><b>🙋‍♂️ для менеджера Клиента:</b></u>\n"
                 "✦ <code>/СУММА</code> - запрос суммы для обмена\n"
                 "<blockquote>примеры:\n"
                 "<code>/1000000</code> - нужно 1 млн IDR - дать расчет и реквизиты для перевода RUB\n"
                 "<code>/-500000</code> - нужно вернуть 500000 IDR - дать расчет возврата</blockquote>\n"
                 "✦ <code>/sos</code> - срочный вызов представителя сервиса\n"
                 "✦ <code>/control [комментарий при необходимости]</code> - запрос контроля оплаты (с вложением)\n"
                 "✦ <code>/joke</code> ✦ <code>/meme</code> ✦ <code>/dice</code> ✦ <code>/coin</code> - если будет скучно 😄\n\n"
                 "✦ <code>/status</code> - просмотр активных запросов\n"
                 "✦ <code>/report</code> - отчет по всем группам запросов\n"
                 "✦ <code>/order_show</code> - просмотр информации по отдельной заявке\n"),
        ("operator", "<u><b>👨‍💻 + для оператора Сервиса:</b></u>\n"
                     #  "✦ <code>/accept & order_number</code> - отметка о принятии платежа\n"
                     "✦ <code>/bank_new</code> - добавить новые реквизиты на обмен\n"
                     "✦ <code>/bank_show</code> - показать все действующие реквизиты\n"
                     "✦ <code>/bank_change</code> - сменить текущие или спец реквизиты\n\n"
                     "✦ <code>/check_control</code> - отчет по количеству запросов на контроле\n"
                     "✦ <code>/zombie [order_number]</code> - оживить заявку из архива (timeout → created)\n"),
        ("admin", "<u><b>👨🏻‍💼 + для админа Cервиса:</b></u>\n"
                  "✦ <code>/transfer [сумма]</code> - подтверждение оплаты ордеров из отчета (с вложением)\n\n"
                  "✦ <code>/bank_remove</code> - удалить реквизиты навсегда\n"
                  "✦ <code>/operator_show</code> - показать всех операторов\n"
                  "✦ <code>/operator_add</code> - назначить оператора сервиса\n"
                  "✦ <code>/operator_remove</code> - снять права оператора\n\n"
                  "✦ <code>/rate_show</code> - показать текущие курсы обмена\n"
                  "✦ <code>/rate_change</code> - сменить текущий основной курс\n"
                  "⁴⁰⁴<code>/rate_zone_change</code> - cменить зоны (интервалы) обмена\n"
                  "⁴⁰⁴<code>/rate_coef_change</code> - сменить текущие коэффициенты курсов\n"
                  "!!! предельная аккуратность при следующей команде:\n"
                  "✦ <code>/order_change [order_number]</code> - изменить статус заявки\n"),
        ("superadmin", "<u><b>👮 + для супер админа:</b></u>\n"
                       "✦ <code>/admin_show</code> - показать всех админов сервиса\n"
                       "✦ <code>/admin_add</code> - добавить админа в сервис\n"
                       "✦ <code>/admin_remove</code> - удалить админа из сервиса\n"
                       "✦ <code>/check</code> - информация о чате\n"
                       "✦ <code>/restart</code> - перезапустить бота\n"
                       "✦ <code>/worktime</code> - изменить рабочее время смены\n"
                       "✦ <code>/work_open</code> — принудительно открыть смену\n"
                       "✦ <code>/work_close</code> — принудительно закрыть смену\n"
                       "✦ <code>/reset_control</code> — сбросить счетчик контроля для текущего чата\n"
                       "✦ <code>/set_media_mbt</code> — установить медиа для MBT (фото/видео)\n"
                       "✦ <code>/set_media_start</code> — установить медиа для начала смены (фото/видео)\n"
                       "✦ <code>/set_media_finish</code> — установить медиа для окончания смены (фото/видео)\n"
                       "✦ <code>/toggle_info_mbt</code> — вкл/выкл инфо-скрипт для MBT\n"
                       "✦ <code>/toggle_info_lgi</code> — вкл/выкл инфо-скрипт для LGI\n"
                       "✦ <code>/toggle_info_tct</code> — вкл/выкл инфо-скрипт для TCT\n")
    ]
    status_order = ["user", "operator", "admin", "superadmin"]
    text = "(｡•̀ ᵕ •́｡) Команды, доступные вам:\n\n"
    for s, section in sections:
        text += section + "\n"
        if s == status:
            break
    return text

help_text = '''
<b>Доступные команды для управления чатами:</b>

• <code>/add_chat</code> — проверить, есть ли чат в базе и получить подсказки по добавлению
• <code>/add_chat_tct ИМЯ</code> — добавить чат типа TCT (пример: <code>/add_chat_tct VSEP_Admin</code>)
• <code>/add_chat_mbt ИМЯ</code> — добавить чат типа MBT
• <code>/add_chat_lgi ИМЯ</code> — добавить чат типа LGI
• <code>/update_chat TCT ИМЯ</code> — обновить тип и имя чата (пример: <code>/update_chat TCT VSEP_Admin</code>)
• <code>/checkchat</code> — проверить, как чат виден в базе и какой тип медиа будет использоваться

... (остальные команды и справка) ...
''' 