from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from config import Config
from datetime import datetime
import re
import pytz

tz = pytz.timezone(Config.TIMEZONE)

class BotKeyboards:
    @staticmethod
    def main_menu() -> ReplyKeyboardMarkup:
        """Главное меню"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="💬 Консультация"), KeyboardButton(text="📅 Записаться")],
                [KeyboardButton(text="💰 Цены"), KeyboardButton(text="🏥 О клинике")],
                [KeyboardButton(text="📞 Контакты"), KeyboardButton(text="❓ Помощь")],
                [KeyboardButton(text="🔔 Мои напоминания"), KeyboardButton(text="Мои записи")]

            ],
            resize_keyboard=True
        )

    @staticmethod
    def skin_type_menu() -> InlineKeyboardMarkup:
        """Выбор типа кожи"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌿 Нормальная", callback_data="skin_normal")],
            [InlineKeyboardButton(text="💧 Сухая", callback_data="skin_dry")],
            [InlineKeyboardButton(text="✨ Жирная", callback_data="skin_oily")],
            [InlineKeyboardButton(text="🔄 Комбинированная", callback_data="skin_combination")],
            [InlineKeyboardButton(text="🌸 Чувствительная", callback_data="skin_sensitive")]
        ])

    @staticmethod
    def age_group_menu() -> InlineKeyboardMarkup:
        """Выбор возраста"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👧 До 18", callback_data="age_teen")],
            [InlineKeyboardButton(text="👩 18-30", callback_data="age_young")],
            [InlineKeyboardButton(text="👩‍💼 30-45", callback_data="age_adult")],
            [InlineKeyboardButton(text="👩‍🦳 45+", callback_data="age_mature")]
        ])

    @staticmethod
    def procedures_menu() -> InlineKeyboardMarkup:
        """Меню процедур"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧼 Чистка лица", callback_data="proc_cleaning")],
            [InlineKeyboardButton(text="💨 Карбокситерапия", callback_data="proc_carboxy")],
            [InlineKeyboardButton(text="🎯 Микронидлинг", callback_data="proc_microneedling")],
            [InlineKeyboardButton(text="👐 Массажи", callback_data="proc_massage")],
            [InlineKeyboardButton(text="🔄 Мезопилинг", callback_data="proc_mesopeel")],
            [InlineKeyboardButton(text="💬 Консультация", callback_data="proc_consultation")]
        ])

    @staticmethod
    def consultation_next_steps() -> InlineKeyboardMarkup:
        """Следующие шаги после консультации"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Записаться", callback_data="book_consultation")],
            [InlineKeyboardButton(text="💰 Узнать цены", callback_data="get_prices")]
        ])

    @staticmethod
    def procedure_booking_menu(procedure: str) -> InlineKeyboardMarkup:
        """Меню записи на процедуру"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Записаться", callback_data=f"book_{procedure}")],
            [InlineKeyboardButton(text="❓ Задать вопрос", callback_data=f"ask_{procedure}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_procedures")]
        ])

    @staticmethod
    def emergency_menu() -> InlineKeyboardMarkup:
        """Меню экстренных ситуаций"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Воспаление", callback_data="emergency_inflammation")],
            [InlineKeyboardButton(text="😰 Аллергия", callback_data="emergency_allergy")],
            [InlineKeyboardButton(text="😨 Боль", callback_data="emergency_pain")],
            [InlineKeyboardButton(text="📞 Связаться с врачом", callback_data="emergency_doctor")]
        ])

    @staticmethod
    def contact_menu() -> InlineKeyboardMarkup:
        raw_phone = Config.CLINIC_PHONE
        clean_phone = re.sub(r'[^\d+]', '', raw_phone)
        if clean_phone.count('+') > 1:
            clean_phone = '+' + clean_phone.replace('+', '')
        # Если нет плюса, добавляем (опционально)
        if not clean_phone.startswith('+'):
            clean_phone = '+' + clean_phone

        """Контактное меню"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 WhatsApp", url=f"https://wa.me/{clean_phone}")],
            [InlineKeyboardButton(text="📍 Адрес", callback_data="show_address")]
        ])

    @staticmethod
    def admin_menu(show_all_bookings: bool = False) -> InlineKeyboardMarkup:
        """Административное меню"""
        buttons = [
            [InlineKeyboardButton(text="📋 Все заявки", callback_data="admin_all_bookings")] if show_all_bookings else [],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🔄 Перезагрузить БЗ", callback_data="admin_reload_kb")]
        ]
        # убираем пустые
        buttons = [row for row in buttons if row]
        return InlineKeyboardMarkup(inline_keyboard=buttons)


    @staticmethod
    def booking_menu() -> InlineKeyboardMarkup:
        """Универсальное меню Да/Нет"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Записаться", callback_data="booking"),
            ]
        ])

    @staticmethod
    def prices_menu() -> InlineKeyboardMarkup:
        """Меню категорий цен"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧼 Чистка лица", callback_data="price_cleaning")],
            [InlineKeyboardButton(text="💨 Карбокситерапия", callback_data="price_carboxy")],
            [InlineKeyboardButton(text="🎯 Микронидлинг", callback_data="price_microneedling")],
            [InlineKeyboardButton(text="🔄 Мезопилинг", callback_data="price_mesopeel")],
            [InlineKeyboardButton(text="👐 Массажи", callback_data="price_massage")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])

    @staticmethod
    def create_dynamic_booking_keyboard(recommendation_text: str) -> InlineKeyboardMarkup:
        """
        Создает клавиатуру на основе текста рекомендации от бота.
        Находит в тексте упоминания процедур и делает для них кнопки.
        """
        recommendation_text = recommendation_text.lower()
        buttons = []

        # Словарь: что ищем в тексте -> какой callback_data ставим
        procedure_map = {
            "чистка лица": "book_cleaning",
            "карбокситерапия": "book_carboxy",
            "микронидлинг": "book_microneedling",
            "массаж": "book_massage",
            "мезопилинг": "book_mesopeel"
        }

        # Ищем упоминания процедур в тексте
        for keyword, callback_data in procedure_map.items():
            if keyword in recommendation_text:
                # Название для кнопки берем из словаря procedure_names в fsm_booking
                # Или можно завести свой словарь здесь
                procedure_name = {
                    "book_cleaning": "🧼 Чистка лица",
                    "book_carboxy": "💨 Карбокситерапия",
                    "book_microneedling": "🎯 Микронидлинг",
                    "book_massage": "👐 Массаж",
                    "book_mesopeel": "🔄 Мезопилинг"
                }.get(callback_data, "Процедура")

                buttons.append([InlineKeyboardButton(text=f"Записаться на {procedure_name}", callback_data=callback_data)])

        # Всегда добавляем кнопку для общей консультации
        buttons.append([InlineKeyboardButton(text="📅 Записаться на консультацию", callback_data="book_consultation")])

        if not buttons:
            # Если вдруг ничего не нашли, возвращаем стандартное меню
            return BotKeyboards.consultation_next_steps()

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def booking_selection_menu() -> InlineKeyboardMarkup:
        """Клавиатура для выбора процедуры для записи."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧼 Чистка лица", callback_data="book_cleaning")],
            [InlineKeyboardButton(text="💨 Карбокситерапия", callback_data="book_carboxy")],
            [InlineKeyboardButton(text="🎯 Микронидлинг", callback_data="book_microneedling")],
            [InlineKeyboardButton(text="👐 Массаж", callback_data="book_massage")],
            [InlineKeyboardButton(text="🔄 Мезопилинг", callback_data="book_mesopeel")],
            [InlineKeyboardButton(text="💬 Консультация", callback_data="book_consultation")],
        ])

    @staticmethod
    def booking_confirmation_menu() -> InlineKeyboardMarkup:
        """Клавиатура для подтверждения записи на процедуру."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить и записаться", callback_data="confirm_booking"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_booking")
            ]
        ])

    @staticmethod
    def after_cancel_booking_menu() -> InlineKeyboardMarkup:
        """
        Клавиатура, предлагающая действия после отмены записи.
        """
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                # Эта кнопка покажет список процедур для новой записи
                InlineKeyboardButton(text="📅 Выбрать другую процедуру", callback_data="restart_booking"),
            ],
            [
                # Эта кнопка просто закроет текущее сообщение (для чистоты)
                InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="back_to_main_menu"),
            ]
        ])

    @staticmethod
    def reminders_menu() -> InlineKeyboardMarkup:
        """Меню управления напоминаниями"""
        return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои напоминания", callback_data="my_reminders")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])

    @staticmethod
    def build_bookings_keyboard(events: list) -> InlineKeyboardMarkup:
        """Создаёт клавиатуру с записями пользователя."""
        buttons = []
        for e in events:
            start_str = e["start"].get("dateTime", e["start"].get("date"))
            # Используем fromisoformat и указываем часовой пояс UTC
            # Преобразуем строку из UTC в объект datetime
            utc_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
             # Конвертируем в локальный часовой пояс
            local_dt = utc_dt.astimezone(tz)

            # Форматируем уже локальное время
            dt_str = local_dt.strftime("%d.%m %H:%M")

            title = e.get("summary", "Без названия")
            buttons.append(
                [InlineKeyboardButton(text=f"{dt_str} — {title}", callback_data=f"choose_cancel:{e['id']}")]
            )
        if not buttons:
            buttons = [[InlineKeyboardButton(text="Нет записей", callback_data="noop")]]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def confirm_keyboard(event_id: str) -> InlineKeyboardMarkup:
        """Клавиатура подтверждения отмены."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"confirm_cancel:{event_id}"),
                InlineKeyboardButton(text="❌ Нет", callback_data="cancel_back")
            ]
        ])