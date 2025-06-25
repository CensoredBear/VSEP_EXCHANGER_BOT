import logging
from datetime import datetime, timezone, time
import pytz
from aiogram.types import Message as TgMessage
from aiogram import Bot
from config import config, system_settings
from messages import send_message, get_bali_and_msk_time_list
from db import db
from logger import logger, log_system, log_user, log_func, log_db, log_warning, log_error
from google_sync import write_to_google_sheet_async
from utils import safe_send_media_with_caption

def should_send_info_message(chat_type: str | None) -> bool:
    """Проверяет, нужно ли отправлять инфо-сообщение для данного типа чата."""
    logger.info(f"[INFO_FLAG_CHECK] chat_type='{chat_type}', send_info_mbt={system_settings.send_info_mbt}, send_info_lgi={system_settings.send_info_lgi}, send_info_tct={system_settings.send_info_tct}")
    
    # Функция для проверки булевого значения (поддерживает строки и булевы значения)
    def is_true(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ['true', '1', 'yes', 'on']
        return False
    
    if chat_type == "MBT" and is_true(system_settings.send_info_mbt):
        logger.info(f"[INFO_FLAG_CHECK] MBT: флаг включен, отправляем сообщение")
        return True
    if chat_type == "LGI" and is_true(system_settings.send_info_lgi):
        logger.info(f"[INFO_FLAG_CHECK] LGI: флаг включен, отправляем сообщение")
        return True
    if chat_type == "TCT" and is_true(system_settings.send_info_tct):
        logger.info(f"[INFO_FLAG_CHECK] TCT: флаг включен, отправляем сообщение")
        return True
    
    logger.info(f"[INFO_FLAG_CHECK] {chat_type}: флаг выключен или чат не поддерживается, НЕ отправляем сообщение")
    return False

async def handle_input_sum(message: TgMessage):
    log_func(f"Вызвана handle_input_sum пользователем {message.from_user.id} (@{message.from_user.username}) в чате {message.chat.id}")
    text = message.text.strip()
    if not text.startswith("/"):
        log_user(f"Пользователь {message.from_user.id} отправил некомандное сообщение: {text}")
        return
    num_part = text[1:]
    if not (num_part.isdigit() or (num_part.startswith("-") and num_part[1:].isdigit())):
        return
    value = int(num_part)
    user = message.from_user
    username = user.username or user.full_name or f"id{user.id}"
    chat = message.chat
    chat_title = chat.title or chat.full_name or str(chat.id)

    # --- Определение медиа для чата ---
    selected_media = None
    chat_type_for_media = None
    
    # --- Получаем nickneim из базы данных ---
    nickneim = await db.get_chat_nickneim(chat.id)
    if nickneim:
        nickneim_upper = nickneim.upper()
        if nickneim_upper.startswith("MBT"):
            selected_media = system_settings.media_mbt
            chat_type_for_media = "MBT"
        elif nickneim_upper.startswith("LGI"):
            selected_media = system_settings.media_lgi
            chat_type_for_media = "LGI"
        elif nickneim_upper.startswith("TCT"):
            selected_media = system_settings.media_tct
            chat_type_for_media = "TCT"
    # ---
    
    log_system(f"[MEDIA_CHECK] Проверка медиа для чата '{chat_title}' (id: {chat.id}). nickneim: '{nickneim}', chat_type_for_media: '{chat_type_for_media}'")

    MAX_ALLOWED = 999_999_999
    MIN_ALLOWED = -999_999_999
    if value > MAX_ALLOWED or value < MIN_ALLOWED:
        await message.reply(f"❗️Ошибка: превышено максимально допустимое значение суммы для расчета (допустимо от {MIN_ALLOWED} до {MAX_ALLOWED}).")
        return
    
    # Проверка минимальной суммы
    if value > 0 and value < 600_000:
        await message.reply(
            """
⚠️⚠️⚠️ <b>ВНИМАНИЕ</b> 
Переводы на сумму менее 600 000 IDR через Объединенный Сервис Обмена временно недоступны.
◻◻◻

<u>МЕНЕДЖЕРУ:</u> 
Предложите Клиенту 
◻ увеличить сумму платежа (за счет полной оплаты или продажи доп услуги / сертификата) 
или 
◻ оплатить текущую сумму, обратившись к Сервисам обмена напрямую - скрипт ниже.

<u>для КЛИЕНТА:</u>
<blockquote>Уважаемые Клиенты! 
В связи с ограничениями на минимальную сумму международного перевода, для осуществления небольших переводов обратитесь напрямую к Сервису обмена: например <b>@cash_friends</b>

Сервис поможет выполнить обмен в индивидуальном порядке. 
При обращении укажите, что вам необходимо оплатить услугу у Партнёра и предоставьте реквизиты аккаунта Партнера (для перевода в IDR).

<u>После выполнения обмена, <b>ОБЯЗАТЕЛЬНО отправьте Менеджеру чек транзакции</b>, который предоставит вам Сервис.</u>

*Правила перевода и курс устанавливаются Сервисом и будут вам обозначены при обращении.</blockquote>

<u>МЕНЕДЖЕРУ:</u>
Не забудьте выдать Клиенту обозначенные реквизиты""",
            parse_mode="HTML"
        )
        return

    # --- Проверка ночного времени: если ночь, сразу обрабатываем ночную заявку и return ---
    if is_night_shift():
        rate = await db.get_actual_rate()
        if not rate:
            await message.reply("Курсы не заданы. Обратитесь к оператору.")
            return
        idr_amount = value
        used_rate = float(rate['main_rate']) if value > 0 else float(rate['rate_back'])
        rub_amount = round(abs(idr_amount) / used_rate)
        times = get_bali_and_msk_time_list()
        bali_time = times[6]  # Полная дата и время по Бали
        
        now = datetime.now(pytz.timezone("Asia/Makassar"))
        naive_now = now.replace(tzinfo=None)
        day = now.strftime('%d')
        month = now.strftime('%m')
        hour = now.strftime('%H')
        minute = now.strftime('%M')
        ms = f"{now.microsecond // 1000:03d}"
        user_id_str = str(user.id)[-3:].zfill(3)
        msg_id_last2 = str(message.message_id)[-2:].zfill(2)
        transaction_number = f"{day}{month}{user_id_str}{hour}{minute}{ms}{msg_id_last2}"
        created_at = naive_now
        status = "night"
        status_changed_at = naive_now
        note = ""
        acc_info = "ночной запрос"
        log = ""
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        user_nick = f"@{user.username}" if user.username else user.full_name
        chat_id = message.chat.id
        msg_id = message.message_id
        if message.chat.username:
            link = f"https://t.me/{message.chat.username}/{msg_id}"
        else:
            chat_id_num = str(chat_id)
            if chat_id_num.startswith('-100'):
                chat_id_num = chat_id_num[4:]
            elif chat_id_num.startswith('-'):
                chat_id_num = chat_id_num[1:]
            link = f"https://t.me/c/{chat_id_num}/{msg_id}"
        history = f"{now_str}&{user_nick}&night&{link}"
        source_chat = str(chat_id)
        await db.add_transaction(
            transaction_number=transaction_number,
            user_id=user.id,
            created_at=created_at,
            idr_amount=idr_amount,
            rate_used=used_rate,
            rub_amount=rub_amount if value > 0 else -rub_amount,
            note=note,
            account_info=acc_info,
            status=status,
            status_changed_at=status_changed_at,
            log=log,
            history=history,
            source_chat=source_chat
        )
        
        # --- Формирование сообщения о сумме (ночная смена) ---
        if value < 0:
            msg = await get_night_shift_message(bali_time)
        else:
            msg = f"""
Для оплаты заказа на:
                        🇮🇩 <b>{abs(idr_amount):,} IDR</b>
Необходимо отправить:
                        🇷🇺 <b>{rub_amount:,} RUB</b>
<blockquote>➤ Перевод в — банк
➤ Карта: —
➤ Получатель: —
➤ СБП: —</blockquote>
⚠️ Реквизиты выдаются с 09:00 до 23:00 по балийскому времени. Сейчас на Бали: {bali_time}
Расчет информационный, оплата невозможна."""
        
        # --- Проверка медиа для ночной смены ---
        final_media_night = selected_media
        final_msg_night = msg

        if chat_type_for_media and not final_media_night:
            warning_text = "MEDIA не найдено - сообщите разработчику!\n\n"
            final_msg_night = warning_text + final_msg_night
            
            log_warning(f"[MEDIA_MISSING] Не установлено медиа для чата типа '{chat_type_for_media}' ({chat_title}). Ночной запрос от {username}. chat_id: {message.chat.id}")
            
            admin_notification = f"⚠️ ВНИМАНИЕ: Не установлено медиа для чата типа '{chat_type_for_media}' ({chat_title}). Ночной запрос от {username}."
            try:
                await message.bot.send_message(config.ADMIN_GROUP, admin_notification)
                log_system(f"[ADMIN_NOTIFICATION] Отправлено уведомление об отсутствующем медиа для чата {chat_title}")
            except Exception as e:
                log_error(f"Не удалось отправить уведомление об отсутствующем медиа в админ-чат: {e}")
        elif chat_type_for_media and final_media_night:
            log_system(f"[MEDIA_FOUND] Найдено медиа для чата типа '{chat_type_for_media}' ({chat_title}): {final_media_night}")
        else:
            log_system(f"[MEDIA_SKIP] Пропущена проверка медиа для чата '{chat_title}' (не относится к MBT/LGI/TCT)")

        await safe_send_media_with_caption(
            bot=message.bot,
            chat_id=message.chat.id,
            file_id=final_media_night,
            caption=final_msg_night,
            reply_to_message_id=message.message_id
        )
        log_func("Пользователю отправлено сообщение о сумме (ночная смена)")
        return

    # --- Получаем курсы и лимиты ---
    rate = await db.get_actual_rate()
    limits = await db.get_rate_limits()
    if not rate or not limits:
        await message.reply("Курсы или лимиты не заданы. Обратитесь к оператору.")
        return
    
    try:
        speclimit = float(rate['rate_special']) if rate['rate_special'] else None
    except Exception:
        speclimit = None
    
    if value > 0 or value < 0:
        user_rank = await db.get_user_rank(message.from_user.id)
        logger.info(f"[MSG] chat_id={message.chat.id}; user_id={message.from_user.id}; username={message.from_user.username}; rank={user_rank}; action=received; text={message.text}")
        idr_amount = value
        limits_list = [float(limits['main_rate']), float(limits['rate1']), float(limits['rate2']), float(limits['rate3'])]
        rates_list = [float(rate['main_rate']), float(rate['rate1']), float(rate['rate2']), float(rate['rate3']), float(rate['rate4']), float(rate['rate_back'])]
        logger.info(f"[SUMMA_CALC] idr_amount={idr_amount}, limits_list={limits_list}, rates_list={rates_list}")
        
        # Пересчёт лимитов из RUB в IDR по курсу каждой категории
        limits_idr = [limits_list[i] * rates_list[i] for i in range(len(limits_list))]
        logger.info(f"[SUMMA_CALC] limits_idr={limits_idr}")
        
        if idr_amount < 0:
            # --- Обработка запроса на возврат ---
            used_rate = rates_list[5]  # rate_back
            cat = 0
            rub_amount = round(abs(idr_amount) / used_rate)
            # Для возврата всегда используются актуальные реквизиты
            accounts = [acc for acc in await db.get_active_bank_accounts() if acc.get('is_actual')]
            acc_text = "\n".join([
                f"▪️ {a['bank']} {a['card_number']} {a['recipient_name']} {a['sbp_phone']}" for a in accounts
            ])
            spec_text = "" # Для возврата нет спец. реквизитов
            
            # --- Генерация номера заявки (возврат) ---
            times = get_bali_and_msk_time_list()
            now = datetime.now(pytz.timezone("Asia/Makassar"))
            naive_now = now.replace(tzinfo=None)
            day = now.strftime('%d')
            month = now.strftime('%m')
            hour = now.strftime('%H')
            minute = now.strftime('%M')
            ms = f"{now.microsecond // 1000:03d}"
            user_id_str = str(user.id)[-3:].zfill(3)
            msg_id_last2 = str(message.message_id)[-2:].zfill(2)
            transaction_number = f"{day}{month}{user_id_str}{hour}{minute}{ms}{msg_id_last2}"
            created_at = naive_now
            status = "created"
            status_changed_at = naive_now
            note = ""
            acc_info = "обратный перевод"
            log = ""
            now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            user_nick = f"@{user.username}" if user.username else user.full_name
            chat_id = message.chat.id
            msg_id = message.message_id
            if message.chat.username:
                link = f"https://t.me/{message.chat.username}/{msg_id}"
            else:
                chat_id_num = str(chat_id)
                if chat_id_num.startswith('-100'):
                    chat_id_num = chat_id_num[4:]
                elif chat_id_num.startswith('-'):
                    chat_id_num = chat_id_num[1:]
                link = f"https://t.me/c/{chat_id_num}/{msg_id}"
            history = f"{now_str}-{user_nick}-создан-{link}"
            source_chat = str(chat_id)
            await db.add_transaction(
                transaction_number=transaction_number,
                user_id=user.id,
                created_at=created_at,
                idr_amount=idr_amount,
                rate_used=used_rate,
                rub_amount=-rub_amount,
                note=note,
                account_info=acc_info,
                status=status,
                status_changed_at=status_changed_at,
                log=log,
                history=history,
                source_chat=source_chat
            )
            
            msg = f"Возврат суммы:\n"
            msg += f"                    🇮🇩 <b>{abs(idr_amount):,} IDR</b>\n"
            msg += f"Будет осуществлен в размере:\n"
            msg += f"                    🇷🇺 <b>{rub_amount:,} RUB</b>\n\n"
            msg += f"Пожалуйста, отправьте следующие данные для осуществления возврата:\n"
            msg += f"<blockquote>➤ Банк Получателя\n"
            msg += "➤ ФИО Получателя\n"
            msg += "➤ Номер карты Получателя\n"
            msg += "➤ Номер телефона для СБП\n"
            msg += "    ❗️не перепутайте банк при СБП ❗️</blockquote>\n\n"
            msg += "⚠️Денежные средства поступят в сроки, установленные банками Отправителя и Получателя.\n\n"
            msg += "🚨Если Вы указали неправильные реквизиты или реквизиты третьего лица, деньги могут быть утеряны и не подлежат возврату!\n"
            msg += "❗️ЭТО ВАЖНО*❗️(◕‿◕)\n\n"
            msg += "<blockquote>При оплате заказов с использованием иностранной валюты нам помогают партнеры из Программы Верифицированных Сервисов БалиФорума (https://t.me/balichatexchange/55612) - безопасность при обмене валют и оплате услуг на Бали и в Тайланде.</blockquote>\n"
            msg += "────⋆⋅☆⋅⋆────\n"
            msg += f"❮❮❮ <b><code>{transaction_number}</code></b> {times[3]} (Bali)"

            # --- Проверка медиа для возврата ---
            final_media_return = selected_media
            final_msg_return = msg

            if chat_type_for_media and not final_media_return:
                warning_text = "MEDIA не найдено - сообщите разработчику!\n\n"
                final_msg_return = warning_text + final_msg_return
                
                log_warning(f"[MEDIA_MISSING] Не установлено медиа для чата типа '{chat_type_for_media}' ({chat_title}). Запрос на возврат от {username}. chat_id: {message.chat.id}")
                
                admin_notification = f"⚠️ ВНИМАНИЕ: Не установлено медиа для чата типа '{chat_type_for_media}' ({chat_title}). Запрос на возврат от {username}."
                try:
                    await message.bot.send_message(config.ADMIN_GROUP, admin_notification)
                    log_system(f"[ADMIN_NOTIFICATION] Отправлено уведомление об отсутствующем медиа для чата {chat_title}")
                except Exception as e:
                    log_error(f"Не удалось отправить уведомление об отсутствующем медиа в админ-чат: {e}")
            elif chat_type_for_media and final_media_return:
                log_system(f"[MEDIA_FOUND] Найдено медиа для чата типа '{chat_type_for_media}' ({chat_title}): {final_media_return}")
            else:
                log_system(f"[MEDIA_SKIP] Пропущена проверка медиа для чата '{chat_title}' (не относится к MBT/LGI/TCT)")

            await safe_send_media_with_caption(
                bot=message.bot,
                chat_id=message.chat.id,
                file_id=final_media_return,
                caption=final_msg_return,
                reply_to_message_id=message.message_id
            )
            logger.info(f"[BOT_MSG] chat_id={message.chat.id}; to_user={message.from_user.id}; action=bot_send; text={msg[:200]}")
            
            admin_msg = (
                f"Запрос на возврат от {username} из чата {chat_title} (id: {chat.id}):\n"
                f"Курс возврата: {used_rate:.2f}\n"
                f"Сумма: {abs(idr_amount):,} IDR = {rub_amount:,} RUB\n"
                f"Реквизиты: {acc_info}\n"
                f"🟡 ЗАЯВКА №{transaction_number} занесена в базу в {times[3]} (Bali)"
            )
            admin_msg = admin_msg.replace(",", " ")
            await message.bot.send_message(config.ADMIN_GROUP, admin_msg)
            logger.info(f"[BOT_MSG] chat_id={config.ADMIN_GROUP}; to_user=ADMIN_GROUP; action=bot_send; text={admin_msg[:200]}")
            return
            
        elif idr_amount <= limits_idr[0]:
            used_rate = rates_list[0]
            cat = 1
        elif idr_amount <= limits_idr[1]:
            used_rate = rates_list[1]
            cat = 2
        elif idr_amount <= limits_idr[2]:
            used_rate = rates_list[2]
            cat = 3
        elif idr_amount <= limits_idr[3]:
            used_rate = rates_list[3]
            cat = 4
        else:
            used_rate = rates_list[4]
            cat = 5
            
        logger.info(f"[SUMMA_CALC] Выбрана категория cat={cat}, used_rate={used_rate}")
        rub_amount = round(idr_amount / used_rate)
        
        # --- Логика выбора реквизитов в зависимости от суммы ---
        if idr_amount > limits_idr[-1]: # Сумма выше последнего лимита
            accounts = [acc for acc in await db.get_active_bank_accounts() if acc.get('is_special')]
            spec_text = "<b>(спец. реквизиты)</b>"
            logger.info(f"[SUMMA_CALC] Сумма {idr_amount} выше последнего лимита, выбраны спец. реквизиты.")
        else: # Сумма в пределах лимитов
            accounts = [acc for acc in await db.get_active_bank_accounts() if acc.get('is_actual')]
            spec_text = ""
            logger.info(f"[SUMMA_CALC] Сумма {idr_amount} в пределах лимитов, выбраны актуальные реквизиты.")

        acc_text = "\n".join([
            f"▪️ {a['bank']} {a['card_number']} {a['recipient_name']} {a['sbp_phone']}" for a in accounts
        ])
        
        # --- Генерация номера заявки (прямой перевод) ---
        times = get_bali_and_msk_time_list()
        now = datetime.now(pytz.timezone("Asia/Makassar"))
        naive_now = now.replace(tzinfo=None)
        day = now.strftime('%d')
        month = now.strftime('%m')
        hour = now.strftime('%H')
        minute = now.strftime('%M')
        ms = f"{now.microsecond // 1000:03d}"
        user_id_str = str(user.id)[-3:].zfill(3)
        msg_id_last2 = str(message.message_id)[-2:].zfill(2)
        transaction_number = f"{day}{month}{user_id_str}{hour}{minute}{ms}{msg_id_last2}"
        created_at = naive_now
        status = "created"
        status_changed_at = naive_now
        note = ""
        
        # Формируем строку реквизитов для записи
        if accounts:
            acc_info = " | ".join([
                f"{a['bank']} - {a['card_number']} - {a['recipient_name']} - {a['sbp_phone']}" for a in accounts
            ])
        else:
            acc_info = "-"
        log = ""
        
        # --- Запись в базу ---
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        user_nick = f"@{user.username}" if user.username else user.full_name
        chat_id = message.chat.id
        msg_id = message.message_id
        if message.chat.username:
            link = f"https://t.me/{message.chat.username}/{msg_id}"
        else:
            chat_id_num = str(chat_id)
            if chat_id_num.startswith('-100'):
                chat_id_num = chat_id_num[4:]
            elif chat_id_num.startswith('-'):
                chat_id_num = chat_id_num[1:]
            link = f"https://t.me/c/{chat_id_num}/{msg_id}"
        history = f"{now_str}${user_nick}$создан${link}"
        source_chat = str(chat_id)
        await db.add_transaction(
            transaction_number=transaction_number,
            user_id=user.id,
            created_at=created_at,
            idr_amount=idr_amount,
            rate_used=used_rate,
            rub_amount=rub_amount,
            note=note,
            account_info=acc_info,
            status=status,
            status_changed_at=status_changed_at,
            log=log,
            history=history,
            source_chat=source_chat
        )
        
        # --- Формируем сообщения ---
        msg = f"Для оплаты заказа на:\n"
        msg += f"                        🇮🇩 <b>{idr_amount:,} IDR</b>\n"
        msg += f"Необходимо отправить:\n"
        msg += f"                        🇷🇺 <b>{rub_amount:,} RUB</b>\n"
        acc_lines = acc_text.split("\n")
        for (i, line) in enumerate(acc_lines, 1):
            (bank, card, rec, sbp) = (line.split(" ")[0], line.split(" ")[1], " ".join(line.split(" ")[2:-1]), line.split(" ")[-1])
            msg += f"<blockquote>➤ Перевод в {bank}\n"
            msg += f"➤ Карта: {card}\n"
            msg += f"➤ Получатель: {rec}\n"
            msg += f"➤ СБП СТРОГО в ✅{bank}✅: {sbp}</blockquote>\n"
        msg += "🙏 После оплаты ОБЯЗАТЕЛЬНО пришлите ЧЕК или СКРИН перевода с видимыми реквизитами получателя, отправителя и датой перевода.\n\n"
        msg += "⚠️ ВАЖНО:\n"
        msg += "- переводите деньги строго с личной карты\n"
        msg += "- не указывайте никаких комментариев\n"
        msg += "- сумма и реквизиты действительны в течении 𝟑х часов\n\n"
        msg += "🚨 При оплате по неправильным или просроченным реквизитами, на другой банк или с карты третьего лица, деньги могут быть утеряны и не подлежат возврату!\n"
        msg += "<blockquote>При оплате заказов с использованием иностранной валюты нам помогают партнеры из Программы Верифицированных Сервисов БалиФорума (https://t.me/balichatexchange/55612) - безопасность при обмене валют и оплате услуг на Бали и в Тайланде.</blockquote>\n"
        msg += "────⋆⋅☆⋅⋆────\n"
        msg += f"❮❮❮ <b><code>{transaction_number}</code></b> {times[3]} (Bali)"

        # --- Проверка медиа для основного сообщения ---
        final_media = selected_media
        final_msg = msg
        
        # --- Проверка медиа для дневной смены ---
        if chat_type_for_media and not final_media:
            warning_text = "MEDIA не найдено - сообщите разработчику!\n\n"
            final_msg = warning_text + final_msg
            log_warning(f"[MEDIA_MISSING] Не установлено медиа для чата типа '{chat_type_for_media}' ({chat_title}). Дневной запрос от {username}.")
            
            admin_notification = f"⚠️ ВНИМАНИЕ: Не установлено медиа для чата типа '{chat_type_for_media}' ({chat_title}). Запрос от {username}."
            try:
                await message.bot.send_message(config.ADMIN_GROUP, admin_notification)
                log_system(f"[ADMIN_NOTIFICATION] Отправлено уведомление об отсутствующем медиа для чата {chat_title}")
            except Exception as e:
                log_error(f"Не удалось отправить уведомление об отсутствующем медиа в админ-чат: {e}")
        elif chat_type_for_media and final_media:
            log_system(f"[MEDIA_FOUND] Найдено медиа для чата типа '{chat_type_for_media}' ({chat_title}): {final_media}")
        else:
            log_system(f"[MEDIA_SKIP] Пропущена проверка медиа для чата '{chat_title}' (не относится к MBT/LGI/TCT)")

        await safe_send_media_with_caption(
            bot=message.bot,
            chat_id=message.chat.id,
            file_id=final_media,
            caption=final_msg,
            reply_to_message_id=message.message_id
        )
        logger.info(f"[SUMMA_CALC_SUCCESS] idr_amount={idr_amount}, used_rate={used_rate}, rub_amount={rub_amount}, category={cat}, user_rank={user_rank}, source_chat='{chat_title}'")
        log_func("Пользователю отправлено сообщение о сумме")
        
        # --- Информационное сообщение ---
        company_name = ""
        try:
            group_row = await db.pool.fetchrow(
                'SELECT nickneim FROM "VSEPExchanger"."user" WHERE rang = $1 AND id = $2',
                'group', message.chat.id
            )
            if group_row and group_row['nickneim']:
                nick = group_row['nickneim']
                logger.info(f"[COMPANY_NAME] Original nick: {nick}")
                if '_' in nick:
                    parts = nick.split('_', 1)
                    company_name = parts[1].strip() if len(parts) > 1 else nick.strip()
                else:
                    company_name = nick.strip()
                    logger.info(f"[COMPANY_NAME] No dash, company_name: {company_name}")
        except Exception as e:
            logger.error(f"[COMPANY_NAME] Error getting company name: {e}")
            company_name = ""
            
        info_msg = (
            "<b>Уважаемые Клиенты !!!</b>\n\n"
            f"Компания <b>{company_name}</b> осуществляет продажи туров за <b>IDR</b> (индонезийская рупия).\n\n"
            "Для Вашего удобства при оплате в рублях мы сотрудничаем с партнерским <b>ОБМЕННЫМ СЕРВИСОМ</b> — Вы переводите RUB по указанным реквизитам, а Ваш тур оплачивает Сервис в IDR.\n\n"
            "<blockquote>Эту услугу оказывает сторонняя компания, обращаем Ваше внимание:\n"
            "1. Мы не регулируем курс конвертации, установленный ОБМЕННЫМ СЕРВИСОМ.\n\n"
            "2. Курс покупки и курс продажи валют всегда разный, поэтому если Вы вдруг оформляете возврат на российскую карту, то возврат будет осуществляться по курсу, установленным обменным сервисом на дату операции возврата.</blockquote>"
        )

        # --- Проверка флага для отправки инфо-сообщения ---
        logger.info(f"[INFO_MSG_CHECK] Проверяем флаг для чата типа '{chat_type_for_media}'")
        should_send = should_send_info_message(chat_type_for_media)
        logger.info(f"[INFO_MSG_CHECK] Результат проверки: {should_send}")
        
        if should_send:
            final_media_info = None  # Второе сообщение всегда без медиа
            final_msg_info = info_msg
            
            # Второе сообщение отправляем без медиа
            log_system(f"[INFO_MSG] Отправка информационного сообщения для чата типа '{chat_type_for_media}'")
            await safe_send_media_with_caption(
                bot=message.bot,
                chat_id=message.chat.id,
                file_id=final_media_info,
                caption=final_msg_info,
                reply_to_message_id=message.message_id
            )
            logger.info(f"[BOT_MSG] chat_id={message.chat.id}; to_user={message.from_user.id}; action=bot_send; text={info_msg[:200]}")
        else:
            log_system(f"[INFO_MSG_SKIP] Пропуск отправки информационного сообщения для чата типа '{chat_type_for_media}' (флаг отключен)")

    return

def is_night_shift() -> bool:
    """🔵 Проверка ночной смены"""
    tz = pytz.timezone("Asia/Makassar")
    now = datetime.now(tz).time()
    
    # Получаем время начала и конца смены из базы
    shift_start = system_settings.shift_start_time
    shift_end = system_settings.shift_end_time
    
    # Убеждаемся, что у нас объекты time
    if isinstance(shift_start, str):
        try:
            start_time = datetime.strptime(shift_start, '%H:%M:%S').time()
        except ValueError:
            start_time = datetime.strptime(shift_start, '%H:%M').time()
    else:
        start_time = shift_start
    
    if isinstance(shift_end, str):
        try:
            end_time = datetime.strptime(shift_end, '%H:%M:%S').time()
        except ValueError:
            end_time = datetime.strptime(shift_end, '%H:%M').time()
    else:
        end_time = shift_end
    
    # Проверяем, находится ли текущее время в пределах смены
    if start_time <= end_time:
        return not (start_time <= now <= end_time)
    else:
        return end_time <= now <= start_time

async def get_night_shift_message(bali_time: str) -> str:
    """🔵 Формирование сообщения о сумме (ночная смена)"""
    shift_start = system_settings.shift_start_time
    shift_end = system_settings.shift_end_time
    
    # Убеждаемся, что у нас объекты time
    if isinstance(shift_start, str):
        try:
            start_time = datetime.strptime(shift_start, '%H:%M:%S').time()
        except ValueError:
            start_time = datetime.strptime(shift_start, '%H:%M').time()
    else:
        start_time = shift_start
    
    if isinstance(shift_end, str):
        try:
            end_time = datetime.strptime(shift_end, '%H:%M:%S').time()
        except ValueError:
            end_time = datetime.strptime(shift_end, '%H:%M').time()
    else:
        end_time = shift_end
    
    # Преобразуем объекты time в строки для отображения
    shift_start_str = start_time.strftime('%H:%M')
    shift_end_str = end_time.strftime('%H:%M')
    msg = f"⚠️ Реквизиты для возврата принимаются с {shift_start_str} до {shift_end_str} по балийскому времени. Сейчас на Бали: {bali_time}\n"
    msg += f"⚠️ Реквизиты выдаются с {shift_start_str} до {shift_end_str} по балийскому времени. Сейчас на Бали: {bali_time}"
    return msg

async def get_night_shift_message_with_sum(bali_time: str, sum_str: str) -> str:
    """🔵 Формирование сообщения о сумме с реквизитами (ночная смена)"""
    shift_start = system_settings.shift_start_time
    shift_end = system_settings.shift_end_time
    
    # Убеждаемся, что у нас объекты time
    if isinstance(shift_start, str):
        try:
            start_time = datetime.strptime(shift_start, '%H:%M:%S').time()
        except ValueError:
            start_time = datetime.strptime(shift_start, '%H:%M').time()
    else:
        start_time = shift_start
    
    if isinstance(shift_end, str):
        try:
            end_time = datetime.strptime(shift_end, '%H:%M:%S').time()
        except ValueError:
            end_time = datetime.strptime(shift_end, '%H:%M').time()
    else:
        end_time = shift_end
    
    # Преобразуем объекты time в строки для отображения
    shift_start_str = start_time.strftime('%H:%M')
    shift_end_str = end_time.strftime('%H:%M')
    msg = f"⚠️ Реквизиты выдаются с {shift_start_str} до {shift_end_str} по балийскому времени.\n"
    msg += f"Сумма: {sum_str}"
    return msg 