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
from utils import safe_send_photo_with_caption
# from globals import config_Pads, ChatDataPad, MessagePad

""" Команда /число или /-число"""
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
Переводы на сумму менее 600 000 IDR через Объединенный Сервис Обмена временно недоступны.
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
    """🔵 Проверка ночного времени: если ночь, сразу обрабатываем ночную заявку и return"""
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
        # Удаляем локальные импорты
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
        """🔵 Формирование сообщения о сумме (ночная смена)"""
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
        await send_message(
            bot=message.bot,
            chat_id=message.chat.id,
            text=msg,
            reply_to_message_id=message.message_id,
            parse_mode="HTML"
        )
        log_func("Пользователю отправлено сообщение о сумме (ночная смена)")
        return
    """🔵 Получаем курсы и лимиты"""
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
            used_rate = rates_list[5]  # rate_back
            cat = 0
            rub_amount = round(abs(idr_amount) / used_rate)
            accounts = [acc for acc in await db.get_active_bank_accounts() if acc.get('is_actual')]
            acc_text = "\n".join([
                f"{a['bank']} {a['card_number']} {a['recipient_name']} {a['sbp_phone']}" for a in accounts
            ])
            """🔵 Генерация номера заявки"""
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
            await safe_send_photo_with_caption(message, system_settings.media_mbt, msg.replace(",", " "), "HTML")
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
        if speclimit and rub_amount >= speclimit:
            accounts = [acc for acc in await db.get_active_bank_accounts() if acc.get('is_special')]
            star = "★"
            spec_text = "Использованы специальные реквизиты"
        else:
            accounts = [acc for acc in await db.get_active_bank_accounts() if acc.get('is_actual')]
            star = ""
            spec_text = ""
        acc_text = "\n".join([
            f"{star}{a['bank']} {a['card_number']} {a['recipient_name']} {a['sbp_phone']}" for a in accounts
        ])
        # --- Генерация номера заявки ---
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
        # Формируем первую запись в history
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        user_nick = f"@{user.username}" if user.username else user.full_name
        # Формируем ссылку на сообщение
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
        msg += "🚨 При оплате по неправильным реквизитами, на другой банк или с карты третьего лица, деньги могут быть утеряны и не подлежат возврату!\n"
        msg += "<blockquote>При оплате заказов с использованием иностранной валюты нам помогают партнеры из Программы Верифицированных Сервисов БалиФорума (https://t.me/balichatexchange/55612) - безопасность при обмене валют и оплате услуг на Бали и в Тайланде.</blockquote>\n"
        msg += "────⋆⋅☆⋅⋆────\n"
        msg += f"❮❮❮ <b><code>{transaction_number}</code></b> {times[3]} (Bali)"
        await safe_send_photo_with_caption(message, system_settings.media_mbt, msg.replace(",", " "), "HTML")
        logger.info(f"[BOT_MSG] chat_id={message.chat.id}; to_user={message.from_user.id}; action=bot_send; text={msg[:200]}")
        # Сразу после этого отправляем информационное сообщение
        # Получаем название компании из nickneim по chat_id среди rang='group'
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
        await message.answer(info_msg, parse_mode="HTML")
        logger.info(f"[BOT_MSG] chat_id={message.chat.id}; to_user={message.from_user.id}; action=bot_send; text={info_msg[:200]}")
        # В админский чат отправляем обычное сообщение (без фото) (для прямого обмена)
        admin_msg = (
            f"🙋‍♂️ Запрос от {username} из чата {chat_title}\n\n"
            f"Категория: {cat} Курс: {used_rate:.2f}\n"
            f"Сумма: {idr_amount:,} IDR = {rub_amount:,} RUB\n"
            f"Реквизиты: {acc_text} {spec_text}\n"
            f"🟡 ЗАЯВКА №{transaction_number} занесена в базу в {times[3]} (Bali)"
        )
        admin_msg = admin_msg.replace(",", " ")
        await message.bot.send_message(config.ADMIN_GROUP, admin_msg)
        logger.info(f"[BOT_MSG] chat_id={config.ADMIN_GROUP}; to_user=ADMIN_GROUP; action=bot_send; text={admin_msg[:200]}")
    else:
        idr_amount = abs(value)  # Keep the absolute value for display
        used_rate = float(rate['rate_back'])
        rub_amount = round(idr_amount / used_rate)
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
        # Получаем актуальные реквизиты для возврата
        accounts = [acc for acc in await db.get_active_bank_accounts() if acc.get('is_actual')]
        acc_text = "\n".join([
            f"{a['bank']} {a['card_number']} {a['recipient_name']} {a['sbp_phone']}" for a in accounts
        ])
        acc_info = "обратный перевод"
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
        history = f"{now_str}-{user_nick}-создан-{link}"
        source_chat = str(chat_id)
        await db.add_transaction(
            transaction_number=transaction_number,
            user_id=user.id,
            created_at=created_at,
            idr_amount=-idr_amount,  # Store negative value in database
            rate_used=used_rate,
            rub_amount=-rub_amount,  # Store negative value in database
            note=note,
            account_info=acc_info,
            status=status,
            status_changed_at=status_changed_at,
            log=log,
            history=history,
            source_chat=source_chat
        )
        msg = f"Возврат суммы:\n"
        msg += f"                    🇮🇩 <b>{idr_amount:,} IDR</b>\n"
        msg += f"Будет осуществлен в размере:\n"
        msg += f"                    🇷🇺 <b>{rub_amount:,} RUB</b>\n\n"
        msg += f"Пожалуйста, отправьте следующие данные для осуществления возврата:\n"
        msg += f"<blockquote>\n➤ Банк Получателя\n"
        msg += "➤ ФИО Получателя\n"
        msg += "➤ Номер карты Получателя (*опционально)\n"
        msg += "➤ Номер телефона для СБП\n"
        msg += "    ❗️не перепутайте банк при СБП ❗️</blockquote>\n\n"
        msg += "⚠️Денежные средства поступят в сроки, установленные банками Отправителя и Получателя.\n\n"
        msg += "🚨Если Вы указали неправильные реквизиты или реквизиты третьего лица, деньги могут быть утеряны и не подлежат возврату!\n"
        msg += "❗️ЭТО ВАЖНО*❗️(◕‿◕)\n\n"
        msg += "<blockquote>При оплате заказов с использованием иностранной валюты нам помогают партнеры из Программы Верифицированных Сервисов БалиФорума (https://t.me/balichatexchange/55612) - безопасность при обмене валют и оплате услуг на Бали и в Тайланде.</blockquote>"
        msg += f"❮❮❮ <b><code>{transaction_number}</code></b> {times[3]} (Bali) \n\n"
        await safe_send_photo_with_caption(message, system_settings.media_mbt, msg.replace(",", " "), "HTML")
        logger.info(f"[BOT_MSG] chat_id={message.chat.id}; to_user={message.from_user.id}; action=bot_send; text={msg[:200]}")
        admin_msg = (
            f"Запрос на возврат от {username} из чата {chat_title} (id: {chat.id}):\n"
            f"Курс возврата: {used_rate:.2f}\n"
            f"Сумма: {idr_amount:,} IDR = {rub_amount:,} RUB\n"
            f"Реквизиты: {acc_info}\n"
            f"🟡 ЗАЯВКА №{transaction_number} занесена в базу в {times[3]} (Bali)"
        )
        admin_msg = admin_msg.replace(",", " ")
        await message.bot.send_message(config.ADMIN_GROUP, admin_msg)
        logger.info(f"[BOT_MSG] chat_id={config.ADMIN_GROUP}; to_user=ADMIN_GROUP; action=bot_send; text={admin_msg[:200]}") 

    # --- Ночная смена: заявка пишется в базу со статусом night и реквизитами 'ночной запрос' ---
    if is_night_shift():
        idr_amount = value
        used_rate = float(rate['main_rate']) if value > 0 else float(rate['rate_back'])
        rub_amount = round(abs(idr_amount) / used_rate)
        times = get_bali_and_msk_time_list()
        # --- Генерация номера заявки ---
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
        history = f"{now_str}-{user_nick}-ночной запрос-{link}"
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
        msg = f"Для оплаты заказа на:\n"
        msg += f"                        🇮🇩 <b>{abs(idr_amount):,} IDR</b>\n"
        msg += f"Необходимо отправить:\n"
        msg += f"                        🇷🇺 <b>{rub_amount:,} RUB</b>\n"
        msg += "<blockquote>➤ Перевод на —\n"
        msg += "➤ На карту: —\n"
        msg += "➤ Получатель: —\n"
        msg += "➤ СБП: —</blockquote>\n"
        msg += "⚠️ Реквизиты выдаются с 09:00 до 23:00 по балийскому времени.\n"
        msg += "Сейчас заявки информационные, оплата невозможна."
        await message.reply(msg, parse_mode="HTML")
        return

def is_night_shift() -> bool:
    """🔵 Проверка ночной смены"""
    tz = pytz.timezone("Asia/Makassar")
    now = datetime.now(tz).time()
    
    # Получаем время начала и конца смены из базы
    shift_start = system_settings.shift_start_time
    shift_end = system_settings.shift_end_time
    
    # Парсим время из строки формата "HH:MM"
    start_hour, start_minute = map(int, shift_start.split(':'))
    end_hour, end_minute = map(int, shift_end.split(':'))
    
    # Создаем объекты time для сравнения
    start_time = time(start_hour, start_minute)
    end_time = time(end_hour, end_minute)
    
    # Проверяем, находится ли текущее время в пределах смены
    if start_time <= end_time:
        return not (start_time <= now <= end_time)
    else:
        return end_time <= now <= start_time

async def get_night_shift_message(bali_time: str) -> str:
    """🔵 Формирование сообщения о сумме (ночная смена)"""
    shift_start = system_settings.shift_start_time
    shift_end = system_settings.shift_end_time
    msg = f"⚠️ Реквизиты для возврата принимаются с {shift_start} до {shift_end} по балийскому времени. Сейчас на Бали: {bali_time}\n"
    msg += f"⚠️ Реквизиты выдаются с {shift_start} до {shift_end} по балийскому времени. Сейчас на Бали: {bali_time}"
    return msg

async def get_night_shift_message_with_sum(bali_time: str, sum_str: str) -> str:
    """🔵 Формирование сообщения о сумме с реквизитами (ночная смена)"""
    shift_start = system_settings.shift_start_time
    shift_end = system_settings.shift_end_time
    msg = f"⚠️ Реквизиты выдаются с {shift_start} до {shift_end} по балийскому времени.\n"
    msg += f"Сумма: {sum_str}"
    return msg

# Здесь будут вспомогательные функции, если они нужны 

