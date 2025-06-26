#!/usr/bin/env python3
"""
Тест календаря выбора месяца/года
"""
from datetime import datetime
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Кастомный календарь для выбора месяца/года
class MonthYearCalendar:
    """Календарь для выбора только месяца и года"""
    
    def __init__(self, locale='ru_RU'):
        self.locale = locale
        self.months = {
            'ru_RU': [
                'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
            ],
            'en_US': [
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ]
        }
        self.months_short = {
            'ru_RU': [
                'янв.', 'фев.', 'мар.', 'апр.', 'май', 'июн.',
                'июл.', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.'
            ],
            'en_US': [
                'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
            ]
        }
    
    def create_month_year_keyboard(self, year: int, month: int = None):
        """Создает клавиатуру для выбора месяца/года"""
        builder = InlineKeyboardBuilder()
        
        # Если месяц не выбран, показываем месяцы
        if month is None:
            # Заголовок с годом
            builder.row(InlineKeyboardButton(
                text=f"📅 {year}",
                callback_data=f"my_year_{year}"
            ))
            
            # Кнопки навигации по годам
            nav_row = []
            nav_row.append(InlineKeyboardButton(
                text="◀️",
                callback_data=f"my_year_{year-1}"
            ))
            nav_row.append(InlineKeyboardButton(
                text="▶️",
                callback_data=f"my_year_{year+1}"
            ))
            builder.row(*nav_row)
            
            # Месяцы (3 в ряд)
            months = self.months.get(self.locale, self.months['en_US'])
            for i in range(0, 12, 3):
                row = []
                for j in range(3):
                    if i + j < 12:
                        month_num = i + j + 1
                        row.append(InlineKeyboardButton(
                            text=months[i + j],
                            callback_data=f"my_month_{year}_{month_num}"
                        ))
                builder.row(*row)
            
            # Кнопка отмены
            builder.row(InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="my_cancel"
            ))
        
        return builder.as_markup()
    
    def process_selection(self, callback_data: str):
        """Обрабатывает выбор в календаре"""
        if callback_data == "my_cancel":
            return True, {"action": "cancel"}
        
        if callback_data.startswith("my_year_"):
            year = int(callback_data.split("_")[2])
            return False, {"year": year, "month": None}
        
        if callback_data.startswith("my_month_"):
            parts = callback_data.split("_")
            year = int(parts[2])
            month = int(parts[3])
            return True, {"year": year, "month": month}
        
        return False, {}

def test_calendar():
    """Тестируем календарь"""
    print("🧪 Тестирование календаря выбора месяца/года")
    
    calendar = MonthYearCalendar()
    current_year = datetime.now().year
    
    print(f"📅 Текущий год: {current_year}")
    
    # Создаем клавиатуру
    keyboard = calendar.create_month_year_keyboard(current_year)
    print(f"✅ Клавиатура создана: {len(keyboard.inline_keyboard)} рядов")
    
    # Тестируем обработку callback'ов
    test_cases = [
        "my_cancel",
        f"my_year_{current_year-1}",
        f"my_month_{current_year}_6"
    ]
    
    for callback_data in test_cases:
        selected, data = calendar.process_selection(callback_data)
        print(f"📝 {callback_data} -> selected={selected}, data={data}")
    
    print("✅ Тест календаря завершен успешно!")

if __name__ == "__main__":
    test_calendar() 