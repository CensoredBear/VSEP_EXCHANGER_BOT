"""
Асинхронная запись заявок в Google Sheets для VSEPExchangerBot через gspread (официальный).
- Асинхронность через run_in_executor
- Подробное логирование в logs/google_sheets.log
- Все параметры и правила см. в README и RULES.md
"""
import gspread_asyncio
from google.oauth2.service_account import Credentials
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe
import asyncio
from typing import List, Dict, Any, Optional, Tuple
import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from config import system_settings, config
from logger import logger, log_system, log_func, log_db, log_warning, log_error
from db import db
from aiogram import Bot
from config import config
from collections import defaultdict

# Настройка отдельного логгера для Google Sheets
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
gs_logger = logging.getLogger("google_sheets")
gs_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(os.path.join(log_dir, "google_sheets.log"), encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
gs_logger.addHandler(file_handler)

def get_chat_table_map():
    """Получение маппинга чатов на таблицы из системных настроек"""
    try:
        if not system_settings.google_sheets_chat_table_map:
            gs_logger.error("Не настроен маппинг чатов на таблицы")
            return {}
        return json.loads(system_settings.google_sheets_chat_table_map)
    except Exception as e:
        gs_logger.error(f"Ошибка при загрузке маппинга чатов: {e}")
        return {}

async def get_worksheet_name_by_chat_id(chat_id: str) -> str:
    """Асинхронно получить имя worksheet по chat_id через nickneim пользователя с rang='group'"""
    user = None
    try:
        async with db.pool.acquire() as conn:
            user = await conn.fetchrow('''
                SELECT nickneim FROM "VSEPExchanger"."user" WHERE id = $1 AND rang = 'group'
            ''', int(chat_id))
    except Exception as e:
        gs_logger.error(f"[GSheets] Ошибка при поиске пользователя по chat_id {chat_id}: {e}")
        logger.error(f"[GSheets] Ошибка при поиске пользователя по chat_id {chat_id}: {e}")
        print(f"[GSheets] Ошибка при поиске пользователя по chat_id {chat_id}: {e}")
        return None
    if not user or not user['nickneim']:
        gs_logger.error(f"[GSheets] Не найден пользователь с chat_id {chat_id} и rang='group'")
        logger.error(f"[GSheets] Не найден пользователь с chat_id {chat_id} и rang='group'")
        print(f"[GSheets] Не найден пользователь с chat_id {chat_id} и rang='group'")
        return None
    prefix = user['nickneim'].split('_')[0]
    worksheet = f"VSEP_{prefix}"
    return worksheet

class GSheetWriteResult:
    def __init__(self):
        self.success_count = 0
        self.error_count = 0
        self.errors = []

    def add_success(self):
        self.success_count += 1

    def add_error(self, error_msg: str):
        self.error_count += 1
        self.errors.append(error_msg)

    def get_summary_message(self) -> str:
        if self.success_count == 0 and self.error_count == 0:
            return "❌ Не удалось определить лист таблицы для записи"
        
        message = []
        message.append(f"🟤 Заявки с произведённым расчётом добавлены в таблицу партнера")
        if self.success_count > 0:
            message.append(f"✅ Успешно записано заявок: {self.success_count}")
        if self.error_count > 0:
            message.append(f"❌ Ошибок при записи: {self.error_count}")
            if self.errors:
                message.append("\nПоследняя ошибка:")
                message.append(self.errors[-1])
        return "\n".join(message)

async def send_gsheet_summary(chat_id: str, result: GSheetWriteResult):
    """
    Отправляет итоговое уведомление в чат о результате записи всех заявок в Google Sheets
    """
    try:
        gs_logger.info(f"[GSheets] Попытка отправить итоговое сообщение в чат {chat_id}: {result.get_summary_message()}")
        bot = Bot(token=config.BOT_TOKEN)
        message = result.get_summary_message()
        await bot.send_message(chat_id=chat_id, text=message)
        await bot.session.close()
        gs_logger.info(f"[GSheets] Итоговое сообщение успешно отправлено в чат {chat_id}")
    except Exception as e:
        gs_logger.error(f"[GSheets] Ошибка при отправке итогового уведомления в чат {chat_id}: {e}")
        logger.error(f"[GSheets] Ошибка при отправке итогового уведомления в чат {chat_id}: {e}")

async def write_to_google_sheet_async(
    chat_id: str,
    row_data: list,
    worksheet_name: str = None,
    write_result: GSheetWriteResult = None
):
    """
    Асинхронно добавляет строку в Google Sheet на лист, определяемый по chat_id через nickneim.
    """
    if worksheet_name is None:
        worksheet_name = await get_worksheet_name_by_chat_id(chat_id)
    if not worksheet_name:
        gs_logger.error(f"[GSheets] Не удалось определить worksheet для chat_id {chat_id}")
        logger.error(f"[GSheets] Не удалось определить worksheet для chat_id {chat_id}")
        print(f"[GSheets] Не удалось определить worksheet для chat_id {chat_id}")
        if write_result:
            write_result.add_error("Не удалось определить лист таблицы")
        return
    
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            write_to_google_sheet_sync,
            chat_id,
            row_data,
            worksheet_name
        )
        if write_result:
            write_result.add_success()
        gs_logger.info(f"[GSheets] Успешно записана строка в таблицу")
    except Exception as e:
        error_msg = str(e)
        gs_logger.error(f"[GSheets] Ошибка при записи в Google Sheets: {error_msg}")
        logger.error(f"[GSheets] Ошибка при записи в Google Sheets: {error_msg}")
        print(f"[GSheets] Ошибка при записи в Google Sheets: {error_msg}")
        if write_result:
            write_result.add_error(error_msg)
        raise

async def write_multiple_to_google_sheet(
    chat_id: str,
    rows_data: list,
    worksheet_name: str = None
):
    """
    Записывает несколько строк в Google Sheet и отправляет одно итоговое уведомление
    """
    write_result = GSheetWriteResult()
    for row_data in rows_data:
        try:
            await write_to_google_sheet_async(chat_id, row_data, worksheet_name, write_result)
        except Exception as e:
            continue
    # Отправляем итоговое уведомление
    await send_gsheet_summary(chat_id, write_result)
    # Если были успешные записи — отправляем финальное сообщение
    if write_result.success_count > 0:
        bot = Bot(token=config.BOT_TOKEN)
        await bot.send_message(
            chat_id=chat_id,
            text="Оплаченные Сервисом заявки перенесены в отчетную таблицу Партнера"
        )
        await bot.session.close()

def format_value_for_gsheet(value):
    """
    Форматирует значение для записи в Google Sheets.
    Преобразует datetime в строку, Decimal в float, оставляет другие значения как есть.
    """
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, Decimal):
        return float(value)
    return value

def prepare_row_for_gsheet(row_data):
    """
    Формирует строку для Google Sheets по новому ТЗ:
    A: дата время (формат DD.MM.YYYY)
    B: Сумма в IDR
    C: Сумма в RUB
    D: Note
    E: чекбокс (пусто)
    F: пропущено
    G: пропущено
    H: Курс обмена
    I: Статус
    J: Номер транзакции (всегда строка)
    K: Реквизиты
    L: История изменений
    M: чат id
    N: дата и время выполнения /transfer (строка)
    """
    # row_data: [transaction_number, user_nick, idr_amount, rub_amount, used_rate, status, note, acc_info, history, source_chat, now_str]
    # Индексы:      0               1         2          3         4         5      6     7        8        9         10
    
    # Форматируем дату
    date_value = row_data[10]
    if isinstance(date_value, datetime):
        date_fmt = date_value.strftime("%d.%m.%Y")
    else:
        try:
            # Пробуем распарсить строку в формате YYYY-MM-DD HH:MM:SS
            date_obj = datetime.strptime(date_value.split(' ')[0], "%Y-%m-%d")
            date_fmt = date_obj.strftime("%d.%m.%Y")
        except Exception:
            date_fmt = str(date_value)  # fallback, если формат не тот

    # Форматируем дату для столбца N (дата и время выполнения /transfer)
    transfer_dt_value = row_data[11]
    if isinstance(transfer_dt_value, datetime):
        transfer_dt_fmt = transfer_dt_value.strftime("%d.%m.%Y")
    else:
        try:
            transfer_dt_fmt = datetime.strptime(transfer_dt_value.split(' ')[0], "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            transfer_dt_fmt = str(transfer_dt_value)

    # Форматируем все значения
    formatted_row = [
        date_fmt,           # A: дата время (DD.MM.YYYY)
        format_value_for_gsheet(row_data[2]),  # B: Сумма в IDR
        format_value_for_gsheet(row_data[3]),  # C: Сумма в RUB
        row_data[6],        # D: Note
        False,              # E: чекбокс (пусто)
        None,               # F: пропущено
        None,               # G: пропущено
        format_value_for_gsheet(row_data[4]),  # H: Курс обмена
        row_data[5],        # I: Статус
        f"'{str(row_data[0]).zfill(6)}'",  # J: Номер транзакции (строка с ведущими нулями, в кавычках)
        row_data[7],        # K: Реквизиты
        row_data[8],        # L: История изменений
        row_data[9],        # M: чат id
        transfer_dt_fmt,    # N: дата и время выполнения /transfer (DD.MM.YYYY)
    ]
    return formatted_row

def write_to_google_sheet_sync(
    chat_id: str,
    row_data: list,
    worksheet_name: str = None
):
    """
    Синхронно добавляет строку в Google Sheet на лист worksheet_name.
    :param chat_id: id чата (строкой)
    :param row_data: список значений для записи
    :param worksheet_name: имя листа (обязательно)
    """
    try:
        creds_json = os.getenv("GOOGLE_TABLE_CREDS")
        if not creds_json:
            raise ValueError("GOOGLE_TABLE_CREDS не задана в env!")
        creds_dict = json.loads(creds_json)
        gs_logger.info(f"[GSheets] Авторизация через from_service_account_info (без файлов)")
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/drive.file"
            ]
        )
        gc = gspread.authorize(creds)
        spreadsheet_name = "VSEP_EXCHANGER_PARTNERS"
        gs_logger.info(f"[GSheets] Открываю таблицу по имени: {spreadsheet_name}")
        sh = gc.open(spreadsheet_name)
        gs_logger.info(f"[GSheets] Открываю лист: {worksheet_name}")
        ws = sh.worksheet(worksheet_name)
        # Преобразуем все Decimal в float перед записью
        row_data = [format_value_for_gsheet(item) for item in row_data]
        # Формируем строку для Google Sheets по ТЗ
        gsheet_row = prepare_row_for_gsheet(row_data)
        gs_logger.info(f"[GSheets] Пытаюсь записать строку: {gsheet_row}")
        ws.append_row(gsheet_row, value_input_option="USER_ENTERED")
        gs_logger.info(f"[GSheets] Успешно записано: {gsheet_row}")
    except Exception as e:
        gs_logger.error(f"[GSheets] Ошибка при записи в Google Sheets: {e}")
        logger.error(f"[GSheets] Ошибка при записи в Google Sheets: {e}")
        print(f"[GSheets] Ошибка при записи в Google Sheets: {e}")
        raise 