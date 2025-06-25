"""
Модуль db.py
============

Асинхронная работа с PostgreSQL через asyncpg для VSEPExchangerBot.

TODO:
- [ ] Добавить методы для получения и обновления информации о пользователях
- [ ] Реализовать миграции для структуры БД
- [ ] Добавить обработку ошибок подключения
- [ ] Покрыть тестами методы работы с БД
"""
import asyncpg
from config import config
from logger import logger

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(dsn=config.CBCLUB_DB_URL, min_size=1, max_size=5)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def execute_query(self, query: str, *args):
        """Выполнение SQL запроса с параметрами"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def check_system_settings_table(self) -> bool:
        """Проверка существования таблицы system_settings в схеме VSEPExchanger"""
        async with self.pool.acquire() as conn:
            try:
                # Проверяем существование таблицы
                exists = await conn.fetchval('''
                    SELECT EXISTS (
                        SELECT 1 
                        FROM information_schema.tables 
                        WHERE table_schema = 'VSEPExchanger' 
                        AND table_name = 'system_settings'
                    );
                ''')
                return exists
            except Exception as e:
                logger.error(f"Ошибка при проверке таблицы system_settings: {e}")
                return False

    async def add_user_if_not_exists(self, user_id: int, nickname: str):
        async with self.pool.acquire() as conn:
            result = await conn.execute('''
                INSERT INTO "VSEPExchanger"."user" (id, nickneim, registration_date, rang)
                VALUES ($1, $2, NOW(), 'user')
                ON CONFLICT (id) DO NOTHING
            ''', user_id, nickname)

    async def set_user_rank(self, user_id: int, rank: str):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE "VSEPExchanger"."user"
                SET rang = $2
                WHERE id = $1
            ''', user_id, rank)

    async def get_user_rank(self, user_id: int) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT rang FROM "VSEPExchanger"."user" WHERE id = $1
            ''', user_id)
            return row['rang'] if row else None

    async def get_chat_nickneim(self, chat_id: int) -> str:
        """Получение nickneim чата по его id"""
        async with self.pool.acquire() as conn:
            nickneim = await conn.fetchval('''
                SELECT nickneim FROM "VSEPExchanger"."user" WHERE id = $1 AND rang = 'group'
            ''', chat_id)
            return nickneim

    async def get_admins(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT nickneim, id, rang FROM "VSEPExchanger"."user" WHERE rang IN ('admin', 'админ', 'superadmin', 'суперадмин')
            ''')
            return rows

    async def get_operators(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT nickneim, id, rang FROM "VSEPExchanger"."user" WHERE rang IN ('operator', 'оператор')
            ''')
            return rows

    async def add_bank_account(self, account_id, bank, card_number, recipient_name, sbp_phone, is_special, is_active, created_by):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO "VSEPExchanger"."bank_account" (
                    account_id, bank, card_number, recipient_name, sbp_phone, is_special, is_active, created_at, updated_at, created_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW(), $8)
            ''', account_id, bank, card_number, recipient_name, sbp_phone, is_special, is_active, created_by)
            logger.info(f"Добавлен новый реквизит: account_id={account_id}, bank={bank}, by user_id={created_by}")

    async def get_active_bank_accounts(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM "VSEPExchanger"."bank_account" WHERE is_active = TRUE ORDER BY account_number
            ''')
            return [dict(row) for row in rows]

    async def set_actual_bank_account(self, account_number):
        async with self.pool.acquire() as conn:
            # Снимаем статус у всех
            await conn.execute('''
                UPDATE "VSEPExchanger"."bank_account" SET is_actual = FALSE WHERE is_actual = TRUE
            ''')
            # Ставим статус выбранному
            await conn.execute('''
                UPDATE "VSEPExchanger"."bank_account" SET is_actual = TRUE WHERE account_number = $1
            ''', account_number)

    async def set_special_bank_account(self, account_number):
        async with self.pool.acquire() as conn:
            # Снимаем статус у всех
            await conn.execute('''
                UPDATE "VSEPExchanger"."bank_account" SET is_special = FALSE WHERE is_special = TRUE
            ''')
            # Ставим статус выбранному
            await conn.execute('''
                UPDATE "VSEPExchanger"."bank_account" SET is_special = TRUE WHERE account_number = $1
            ''', account_number)

    async def get_bank_account_by_number(self, account_number):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM "VSEPExchanger"."bank_account" WHERE account_number = $1
            ''', account_number)
            return dict(row) if row else None

    async def remove_bank_account(self, account_number):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                DELETE FROM "VSEPExchanger"."bank_account" WHERE account_number = $1
            ''', account_number)

    async def deactivate_bank_account(self, account_number):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE "VSEPExchanger"."bank_account" SET is_active = FALSE WHERE account_number = $1
            ''', account_number)

    async def get_actual_rate(self):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM "VSEPExchanger"."rate" WHERE is_actual = TRUE LIMIT 1
            ''')
            return dict(row) if row else None

    async def get_rate_coefficients(self):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM "VSEPExchanger"."rate" WHERE id = 1
            ''')
            return dict(row) if row else None

    async def get_rate_limits(self):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM "VSEPExchanger"."rate" WHERE id = 2
            ''')
            return dict(row) if row else None

    async def add_transaction(self, transaction_number, user_id, created_at, idr_amount, rate_used, rub_amount, note, account_info, status, status_changed_at, log, history=None, source_chat=None, crm_number=None):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO "VSEPExchanger"."transactions" (transaction_number, user_id, created_at, idr_amount, rate_used, rub_amount, note, account_info, status, status_changed_at, log, history, source_chat, crm_number)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ''', transaction_number, user_id, created_at, idr_amount, rate_used, rub_amount, note, account_info, status, status_changed_at, log, history, source_chat, crm_number)

    async def get_transaction_by_number(self, transaction_number: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM "VSEPExchanger"."transactions" WHERE transaction_number = $1
            ''', transaction_number)
            return dict(row) if row else None

    async def update_transaction_status(self, transaction_number: str, new_status: str, status_changed_at):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE "VSEPExchanger"."transactions"
                SET status = $2, status_changed_at = $3
                WHERE transaction_number = $1
            ''', transaction_number, new_status, status_changed_at)

    async def update_transaction_history(self, transaction_number, history):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE "VSEPExchanger"."transactions" SET history = $2 WHERE transaction_number = $1
            ''', transaction_number, history)

    async def update_transaction_crm_number(self, transaction_number, crm_number):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE "VSEPExchanger"."transactions" SET crm_number = $2 WHERE transaction_number = $1
            ''', transaction_number, crm_number)

    async def update_transaction_note(self, transaction_number, note):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE "VSEPExchanger"."transactions" SET note = $2 WHERE transaction_number = $1
            ''', transaction_number, note)

    async def get_group_chats(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT id, nickneim FROM "VSEPExchanger"."user" WHERE rang = 'group'
            ''')
            return [dict(row) for row in rows]

    async def set_system_setting(self, key: str, value: str):
        """Установка значения системной настройки"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO "VSEPExchanger".system_settings (key, value)
                VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = $2
            ''', key, value)
            logger.info(f"SYSTEM | Обновлена системная настройка: {key}={value}")

    async def get_system_setting(self, key: str) -> str:
        """Получение значения системной настройки"""
        async with self.pool.acquire() as conn:
            value = await conn.fetchval('''
                SELECT value FROM "VSEPExchanger".system_settings
                WHERE key = $1
            ''', key)
            logger.info(f"SYSTEM | Получена системная настройка: {key}={value}")
            return value

    async def toggle_system_setting(self, key: str) -> bool:
        """Переключение булевой системной настройки (true/false)"""
        async with self.pool.acquire() as conn:
            # Получаем текущее значение
            current_value = await conn.fetchval('''
                SELECT value FROM "VSEPExchanger".system_settings
                WHERE key = $1
            ''', key)
            
            # Определяем новое значение (переключаем true/false)
            if current_value is None:
                new_value = "true"
            elif current_value.lower() in ['true', '1', 'yes', 'on']:
                new_value = "false"
            else:
                new_value = "true"
            
            # Обновляем значение
            await conn.execute('''
                INSERT INTO "VSEPExchanger".system_settings (key, value)
                VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = $2
            ''', key, new_value)
            
            logger.info(f"SYSTEM | Переключена системная настройка: {key}={new_value}")
            return new_value.lower() == "true"

    async def get_all_system_settings(self) -> dict:
        """Получение всех системных настроек"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT key, value FROM "VSEPExchanger".system_settings;
            ''')
            return {row['key']: row['value'] for row in rows}

    async def migrate_photo_to_video_ids(self):
        """Миграция ключей photo_id на video_id"""
        async with self.pool.acquire() as conn:
            # Получаем текущие значения
            photo_start = await conn.fetchval('''
                SELECT value FROM "VSEPExchanger".system_settings
                WHERE key = 'photo_id_start'
            ''')
            photo_end = await conn.fetchval('''
                SELECT value FROM "VSEPExchanger".system_settings
                WHERE key = 'photo_id_end'
            ''')
            
            # Если есть значения, создаем новые записи
            if photo_start:
                await conn.execute('''
                    INSERT INTO "VSEPExchanger".system_settings (key, value)
                    VALUES ('video_id_start', $1)
                    ON CONFLICT (key) DO UPDATE SET value = $1
                ''', photo_start)
            
            if photo_end:
                await conn.execute('''
                    INSERT INTO "VSEPExchanger".system_settings (key, value)
                    VALUES ('video_id_end', $1)
                    ON CONFLICT (key) DO UPDATE SET value = $1
                ''', photo_end)
            
            # Удаляем старые записи
            await conn.execute('''
                DELETE FROM "VSEPExchanger".system_settings
                WHERE key IN ('photo_id_start', 'photo_id_end')
            ''')
            
            logger.info("Миграция ключей photo_id на video_id завершена")

    async def ensure_system_settings(self):
        """Проверка и установка значений по умолчанию для системных настроек"""
        default_settings = {
            'shift_start_time': '09:00',
            'shift_end_time': '23:00',
            'video_id_start': None,
            'video_id_end': None,
            'google_sheets_credentials_path': None,
            'google_sheets_spreadsheet_url': None,
            'google_sheets_chat_table_map': '{"ТСТ_TreningPartner": "VSEP_TCT", "MBT_MyBaliTrips.com": "VSEP_MBT", "LGI_Legal Indonesia": "VSEP_LGI"}',
            'send_info_mbt': 'true',
            'send_info_lgi': 'true',
            'send_info_tct': 'true'
        }
        
        async with self.pool.acquire() as conn:
            for key, default_value in default_settings.items():
                # Проверяем существование настройки
                exists = await conn.fetchval('''
                    SELECT EXISTS (
                        SELECT 1 
                        FROM "VSEPExchanger"."system_settings" 
                        WHERE key = $1
                    )
                ''', key)
                
                if not exists:
                    # Если настройка не существует, создаем её
                    await conn.execute('''
                        INSERT INTO "VSEPExchanger"."system_settings" (key, value)
                        VALUES ($1, $2)
                    ''', key, str(default_value))
                    logger.info(f"Создана системная настройка {key} со значением по умолчанию {default_value}")

    async def get_control_counter(self, chat_id: int) -> int:
        key = f"{chat_id}_control_counter"
        value = await self.get_system_setting(key)
        return int(value) if value is not None else 0

    async def set_control_counter(self, chat_id: int, value: int):
        key = f"{chat_id}_control_counter"
        await self.set_system_setting(key, str(value))

    async def get_all_control_counters(self):
        """Получить все счетчики контроля по всем чатам"""
        async with self.pool.acquire() as conn:
            # Получаем все ключи, которые заканчиваются на _control_counter
            rows = await conn.fetch('''
                SELECT key, value 
                FROM "VSEPExchanger".system_settings 
                WHERE key LIKE '%_control_counter'
            ''')
            
            counters = []
            for row in rows:
                key = row['key']
                value = int(row['value']) if row['value'] else 0
                
                # Извлекаем chat_id из ключа (убираем _control_counter)
                chat_id_str = key.replace('_control_counter', '')
                try:
                    chat_id = int(chat_id_str)
                    
                    # Получаем название чата (если есть в базе)
                    chat_title = await self.get_chat_title(chat_id)
                    
                    counters.append({
                        'chat_id': chat_id,
                        'chat_title': chat_title or f"Чат {chat_id}",
                        'counter': value
                    })
                except ValueError:
                    # Пропускаем некорректные ключи
                    continue
            
            # Сортируем по убыванию счетчика
            counters.sort(key=lambda x: x['counter'], reverse=True)
            return counters

    async def get_chat_title(self, chat_id: int) -> str:
        """Получить название чата по его ID"""
        async with self.pool.acquire() as conn:
            # Пытаемся найти чат в таблице user
            row = await conn.fetchrow('''
                SELECT nickneim 
                FROM "VSEPExchanger"."user" 
                WHERE id = $1
            ''', chat_id)
            
            if row and row['nickneim']:
                return row['nickneim']
            
            return None

db = Database() 