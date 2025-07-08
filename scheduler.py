import asyncio
from datetime import datetime, timedelta, time
import pytz
from aiogram import Bot
from config import config, system_settings
from logger import log_system, log_info, log_error, log_warning
from messages import get_bali_and_msk_time_list
from db import db
import logging
import os
from aiogram.types import FSInputFile
from utils import safe_send_media_with_caption

night_shift = False  # Глобальный флаг ночной смены

class Scheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.is_running = False
        self.shift_start = None
        self.shift_end = None
        self.sent_start_today = False
        self.sent_end_today = False

    async def send_status_message(self):
        """Отправка сообщения о статусе бота"""
        try:
            times = get_bali_and_msk_time_list()
            message = f"🕐 {times[6]} (Bali) / {times[5]} (MSK)\nконтроль - ок✅, работает штатно"
            
            # Отправка сообщения в админскую группу
            await self.bot.send_message(
                chat_id=config.ADMIN_GROUP,
                text=message
            )
            log_system("Отправлено сообщение о статусе бота")
            
        except Exception as e:
            log_system(f"Ошибка при отправке статусного сообщения: {e}", level=logging.ERROR)

    async def send_shift_end(self):
        global night_shift
        night_shift = True
        try:
            groups = await db.get_group_chats()
            admin_group = config.ADMIN_GROUP
            
            # Получаем список администраторов
            admins = await db.get_admins()
            admin_mentions = " ".join([f"@{admin['nickneim']}" for admin in admins if admin['rang'] in ['admin', 'админ']])
            
            text = f'''🔴 <b>СМЕНА ЗАКРЫТА!</b> 🚫

<blockquote>📋 В соответствии с регламентом смены Объединённого Сервиса Обмена с {self.shift_start} до {self.shift_end} по балийскому времени.

  📌 В период с {self.shift_end} до {self.shift_start} ответы на заявки — информационные: бот не выдаёт реквизиты, заявки не попадают в базу и не могут быть оплачены.</blockquote>

  Спасибо всем за работу! 🎉
  Спокойной ночи и приятного отдыха! 🌙'''

            admin_text = f'''{text}

  ПРОШУ АДМИНИСТРАТОРОВ СЕРВИСА провести взаиморасчёты с Партнёрами.

  Для этого в каждом чате партнера совершите следующие действия:

  1️⃣ командой <code>/report</code> запросите отчёт по подтверждённым заявкам, ожидающим выплаты
  2️⃣ нажмите кнопку "Сформировать счёт" под сформированным отчётом.
  3️⃣ произведите оплату по предоставленным реквизитам и отправьте скрин оплаты и команду <code>/transfer [сумма платежа]</code> (ЧЕК И КОМАНДА должны быть в едином или ответном сообщении)
  4️⃣ бот сверит суммы и зачтёт платежи, переведя все оплаченные заказы в статус "оплачено"'''

            log_system(f"[SHIFT_END] admin_group: {admin_group} (type: {type(admin_group)})")
            log_system(f"[SHIFT_END] admin_text length: {len(admin_text)}")

            # Проверяем наличие медиа для конца смены
            if not system_settings.media_finish:
                warning_text = "MEDIA не найдено - сообщите разработчику!\n\n"
                text = warning_text + text
                admin_text = warning_text + admin_text
                
                log_warning(f"[MEDIA_MISSING] Не установлено медиа для конца смены (media_finish). shift_end: {self.shift_end}")
                
                admin_notification = f"⚠️ ВНИМАНИЕ: Не установлено медиа для конца смены (media_finish)."
                try:
                    await self.bot.send_message(config.ADMIN_GROUP, admin_notification)
                    log_system(f"[ADMIN_NOTIFICATION] Отправлено уведомление об отсутствующем медиа для конца смены")
                except Exception as e:
                    log_error(f"Не удалось отправить уведомление об отсутствующем медиа в админ-чат: {e}")
            else:
                log_system(f"[MEDIA_FOUND] Найдено медиа для конца смены: {system_settings.media_finish}")

            # Отправляем в группы партнёров
            for group in groups:
                try:
                    log_system(f"[SHIFT_END] Пробую отправить сообщение о закрытии смены в {group['id']}")
                    await safe_send_media_with_caption(self.bot, group['id'], system_settings.media_finish, text)
                except Exception as e:
                    log_system(f"[SHIFT_END] Ошибка при отправке в группу {group['id']}: {e}", level=logging.ERROR)

            try:
                log_system(f"[SHIFT_END] Пробую отправить сообщение о закрытии смены в админский чат {admin_group}")
                await safe_send_media_with_caption(self.bot, admin_group, system_settings.media_finish, admin_text, parse_mode="HTML")
            except Exception as e:
                log_system(f"[SHIFT_END] Ошибка при отправке в админский чат {admin_group}: {e}", level=logging.ERROR)

            log_system("[SHIFT_END] Рассылка об окончании смены отправлена")
        except Exception as e:
            log_system(f"[SHIFT_END] Ошибка при рассылке об окончании смены: {e}", level=logging.ERROR)

    async def send_shift_start(self):
        """Отправка сообщения о начале смены"""
        try:
            # Обновляем системные настройки при начале смены
            await system_settings.load()
            log_system("[SHIFT_START] Системные настройки обновлены")
            
            # Переводим все заказы со статусом created в timeout и получаем информацию
            timeout_count, timeout_time = await self.timeout_all_created_orders()
            
            # Получаем список групп
            groups = await db.get_group_chats()
            if not groups:
                log_system("Нет подключенных групп для рассылки")
                return
            
            global night_shift
            night_shift = False
            try:
                # --- Обнуляем все заказы со статусом created во всех чатах ---
                admin_group = config.ADMIN_GROUP
                times = get_bali_and_msk_time_list()
                today = times[6]  # дата и время по Бали

                # Формируем информацию о переведенных заявках
                timeout_info = ""
                if timeout_count > 0:
                    timeout_info = f"\n\n📋 <b>АРХИВАЦИЯ ЗАЯВОК:</b>\nПереведено {timeout_count} заявок в статус timeout (созданных до {timeout_time})"
                elif timeout_count == 0:
                    timeout_info = f"\n\n📋 <b>АРХИВАЦИЯ ЗАЯВОК:</b>\nНет заявок для перевода в timeout (созданных до {timeout_time})"

                text = (
                    f"🟢 <b>СМЕНА ОТКРЫТА!</b> ✅\n"
                    f"Объединённый Сервис Обмена начинает свою работу.\n\n"
                    f"Балийское время: {today}\n"
                    f"Сегодня работаем до {self.shift_end}.\n\n"
                    f"Желаю вам спокойной, продуктивной смены.{timeout_info}"
                )
                admin_text = f'''{text}

ПРЕДСТАВИТЕЛИ СЕРВИСА: не забудьте установить актуальные РЕКВИЗИТЫ И КУРСЫ'''

                # Проверяем наличие медиа для начала смены
                if not system_settings.media_start:
                    warning_text = "MEDIA не найдено - сообщите разработчику!\n\n"
                    text = warning_text + text
                    admin_text = warning_text + admin_text
                    
                    log_warning(f"[MEDIA_MISSING] Не установлено медиа для начала смены (media_start). shift_start: {self.shift_start}")
                    
                    admin_notification = f"⚠️ ВНИМАНИЕ: Не установлено медиа для начала смены (media_start)."
                    try:
                        await self.bot.send_message(config.ADMIN_GROUP, admin_notification)
                        log_system(f"[ADMIN_NOTIFICATION] Отправлено уведомление об отсутствующем медиа для начала смены")
                    except Exception as e:
                        log_error(f"Не удалось отправить уведомление об отсутствующем медиа в админ-чат: {e}")
                else:
                    log_system(f"[MEDIA_FOUND] Найдено медиа для начала смены: {system_settings.media_start}")

                for group in groups:
                    try:
                        log_system(f"[SHIFT_START] Пробую отправить сообщение о начале смены в {group['id']}")
                        await safe_send_media_with_caption(self.bot, group['id'], system_settings.media_start, text)
                    except Exception as e:
                        log_system(f"[SHIFT_START] Ошибка при отправке в группу {group['id']}: {e}", level=logging.ERROR)

                try:
                    log_system(f"[SHIFT_START] Пробую отправить сообщение о начале смены в админский чат {admin_group}")
                    await safe_send_media_with_caption(self.bot, admin_group, system_settings.media_start, admin_text, parse_mode="HTML")
                except Exception as e:
                    log_system(f"[SHIFT_START] Ошибка при отправке в админский чат {admin_group}: {e}", level=logging.ERROR)

                log_system("[SHIFT_START] Рассылка об открытии смены отправлена")
            except Exception as e:
                log_system(f"[SHIFT_START] Ошибка при рассылке об открытии смены: {e}", level=logging.ERROR)
        except Exception as e:
            log_system(f"Ошибка при отправке сообщения о начале смены: {e}", level=logging.ERROR)

    async def timeout_all_created_orders(self):
        """Переводит все заказы со статусом created в timeout, созданные за 12 часов до начала смены"""
        try:
            # Вычисляем время "12 часов назад от начала смены"
            now = datetime.now()
            shift_start_datetime = datetime.combine(now.date(), self.shift_start)
            timeout_threshold = shift_start_datetime - timedelta(hours=12)
            
            # Получаем все заказы со статусом created, созданные до порога времени
            orders = await db.pool.fetch(
                'SELECT transaction_number FROM "VSEPExchanger"."transactions" WHERE status = $1 AND created_at < $2',
                'created', timeout_threshold
            )
            
            if orders:
                # Обновляем статус на timeout
                await db.pool.execute(
                    'UPDATE "VSEPExchanger"."transactions" SET status = $1, status_changed_at = $2 WHERE status = $3 AND created_at < $4',
                    'timeout', datetime.now(), 'created', timeout_threshold
                )
                log_system(f"[TIMEOUT] Переведено {len(orders)} заказов в статус timeout (созданных до {timeout_threshold.strftime('%d.%m.%Y %H:%M')})")
                return len(orders), timeout_threshold.strftime('%d.%m.%Y %H:%M')
            else:
                log_system(f"[TIMEOUT] Нет заказов для перевода в timeout (созданных до {timeout_threshold.strftime('%d.%m.%Y %H:%M')})")
                return 0, timeout_threshold.strftime('%d.%m.%Y %H:%M')
                
        except Exception as e:
            log_system(f"[TIMEOUT] Ошибка при переводе заказов в timeout: {e}", level=logging.ERROR)
            return 0, "ошибка"

    async def update_shift_times(self):
        """Обновление времени начала и конца смены из базы"""
        try:
            # Получаем значения по отдельности
            shift_start_str = await db.get_system_setting('shift_start_time')
            shift_end_str = await db.get_system_setting('shift_end_time')
            
            if not shift_start_str or not shift_end_str:
                log_system("Не удалось получить время начала/конца смены из базы", level=logging.ERROR)
                return False
                
            # Парсим время из строки в объекты time
            try:
                # Пробуем сначала формат с секундами
                self.shift_start = datetime.strptime(shift_start_str, '%H:%M:%S').time()
                self.shift_end = datetime.strptime(shift_end_str, '%H:%M:%S').time()
            except ValueError:
                # Если не получилось, пробуем формат без секунд
                self.shift_start = datetime.strptime(shift_start_str, '%H:%M').time()
                self.shift_end = datetime.strptime(shift_end_str, '%H:%M').time()
                
            log_system(f"Время смены установлено: начало {self.shift_start}, конец {self.shift_end}")
            return True
        except Exception as e:
            log_system(f"Ошибка при обновлении времени смены: {e}", level=logging.ERROR)
            return False

    def is_night_shift(self, current_time: datetime) -> bool:
        """Проверяет, является ли текущее время ночной сменой"""
        if not self.shift_start or not self.shift_end:
            return False
            
        # Теперь shift_start и shift_end - это объекты time
        start_time = self.shift_start
        end_time = self.shift_end
        current_time_only = current_time.time()
        
        # Проверяем, находится ли текущее время в пределах смены
        if start_time <= end_time:
            return not (start_time <= current_time_only <= end_time)
        else:
            return end_time <= current_time_only <= start_time

    async def scheduler_loop(self):
        global night_shift
        tz = pytz.timezone("Asia/Makassar")
        while self.is_running:
            try:
                now = datetime.now(tz)
                # log_system(f"[DEBUG] Текущее время: {now.strftime('%H:%M:%S')}")
                
                # Проверяем и обновляем статус ночной смены
                is_night = self.is_night_shift(now)
                if is_night != night_shift:
                    night_shift = is_night
                    log_system(f"Статус ночной смены изменен: {night_shift}")
                
                # Открытие смены
                # Теперь shift_start и shift_end - это объекты time
                start_hour = self.shift_start.hour
                start_minute = self.shift_start.minute
                # log_system(f"[DEBUG] Проверка начала смены: текущее время {now.hour}:{now.minute}, время начала {start_hour}:{start_minute}")
                if now.hour == start_hour and now.minute == start_minute and not self.sent_start_today:
                    log_system(f"[DEBUG] Условия для отправки сообщения о начале смены выполнены")
                    try:
                        await self.send_shift_start()
                        self.sent_start_today = True
                        self.sent_end_today = False
                        log_system("Сообщение о начале смены успешно отправлено")
                    except Exception as e:
                        log_system(f"Ошибка при отправке сообщения о начале смены: {e}", level=logging.ERROR)
                
                # Закрытие смены
                end_hour = self.shift_end.hour
                end_minute = self.shift_end.minute
                # log_system(f"[DEBUG] Проверка конца смены: текущее время {now.hour}:{now.minute}, время конца {end_hour}:{end_minute}")
                if now.hour == end_hour and now.minute == end_minute and not self.sent_end_today:
                    log_system(f"[DEBUG] Условия для отправки сообщения о конце смены выполнены")
                    try:
                        await self.send_shift_end()
                        self.sent_end_today = True
                        log_system("Сообщение о конце смены успешно отправлено")
                    except Exception as e:
                        log_system(f"Ошибка при отправке сообщения о конце смены: {e}", level=logging.ERROR)
                
                # Сброс флагов в полночь
                if now.hour == 0 and now.minute == 0:
                    self.sent_start_today = False
                    self.sent_end_today = False
                    log_system("Сброс флагов отправки сообщений")
                
                # Ждем до следующей минуты
                await asyncio.sleep(60 - now.second)
                
            except Exception as e:
                log_system(f"Ошибка в scheduler_loop: {e}", level=logging.ERROR)
                await asyncio.sleep(60)  # В случае ошибки ждем минуту

    async def start(self):
        """Запуск планировщика"""
        if not self.is_running:
            self.is_running = True
            # Инициализируем время смены
            await self.update_shift_times()
            # Запускаем основной цикл
            asyncio.create_task(self.scheduler_loop())
            log_system("Планировщик запущен")

    def stop(self):
        """Остановка планировщика"""
        self.is_running = False
        log_system("Планировщик остановлен")

    def reset_flags_and_night_shift(self):
        self.sent_start_today = False
        self.sent_end_today = False
        tz = pytz.timezone("Asia/Makassar")
        now = datetime.now(tz)
        global night_shift
        old_night_shift = night_shift
        night_shift = self.is_night_shift(now)
        log_system(f"[SCHEDULER] Флаги сброшены, night_shift={night_shift}")
        if night_shift != old_night_shift:
            log_system(f"Статус ночной смены изменен: {night_shift}")

# Создаем глобальный экземпляр планировщика
scheduler = None

def init_scheduler(bot: Bot):
    """Инициализация планировщика"""
    global scheduler
    scheduler = Scheduler(bot)
    return scheduler 