from __future__ import annotations
from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from bot.states import UserStates
from services.bot_logic import SimpleBotLogic
from bot.keyboards import BotKeyboards
from data.database import Database
from dataclasses import dataclass, asdict
from services.google_calendar_service import GoogleCalendarService
from datetime import datetime, timedelta
import logging
from typing import Any, Dict
from services.reminder_service import tz

logger = logging.getLogger(__name__)
router = Router()

@dataclass
class Slot:
    start: datetime
    end: datetime
    date_str: str
    time_str: str
    weekday: str
    display: str

    def serialize(self)-> Dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "date_str": self.date_str,
            "time_str": self.time_str,
            "weekday": self.weekday,
            "display": self.display,
        }

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> Slot:
        start = data["start"]
        end = data["end"]
        if isinstance(start, str):
            start = datetime.fromisoformat(start)
        if isinstance(end, str):
            end = datetime.fromisoformat(end)
        # Присваиваем часовой пояс
        if start.tzinfo is None:
            start = tz.localize(start)
        if end.tzinfo is None:
            end = tz.localize(end)
        return Slot(
            start=start,
            end=end,
            date_str=data["date_str"],
            time_str=data["time_str"],
            weekday=data["weekday"],
            display=data["display"],
    )

@router.callback_query(F.data.startswith("book_"))
async def booking_start_handler(callback: types.CallbackQuery, state: FSMContext, bot_logic: SimpleBotLogic):
    """Начало записи на процедуру - Шаг 1: Показываем информацию и просим подтверждение"""
    await callback.answer()
    procedure = callback.data.replace("book_", "")

    # Формируем запрос для получения информации о процедуре
    procedure_queries = {
        "cleaning": "основная информация о чистке лица, длительность, виды, стоимость, показания, противопоказания",
        "carboxy": "что такое карбокситерапия, длительность и стоимость, эффекты, показания, курс",
        "microneedling": "что такое микронидлинг, длительность и стоимость, курс, противопоказания",
        "massage": "информация о массаже лица, длительность и стоимость, виды, эффекты",
        "mesopeel": "информация о мезопилинге, длительность и стоимость, показания, курс",
        "consultation": "информация о консультации косметолога"
}
    query = procedure_queries.get(procedure, f"информация о процедуре {procedure}")


    info_response, _ = await bot_logic.process_message(callback.from_user.id, query)

    # Получаем информацию из базы знаний
    procedure_names = {
        "consultation": "Консультация косметолога",
        "cleaning": "Чистка лица",
        "carboxy": "Карбокситерапия",
        "mesopeel": "Мезопилинг",
        "microneedling": "Микронидлинг",
        "massage": "Массаж лица"
}

    # Сохраняем данные процедуры
    procedure_name = procedure_names.get(procedure, "Процедура")
    await state.update_data(procedure=procedure, procedure_name=procedure_name)

    # Формируем сообщение с информацией о процедуре
    confirmation_text = f"Вы выбрали запись на: <b>{procedure_name}</b>\n\n"
    confirmation_text += "🔍 <b>Краткая информация о процедуре:</b>\n"
    confirmation_text += f"{info_response}\n\n"
    confirmation_text += "Пожалуйста, подтвердите ваш выбор, чтобы перейти к вводу контактных данных."

    await callback.message.answer(
        confirmation_text,
        reply_markup=BotKeyboards.booking_confirmation_menu()
    )
    await state.set_state(UserStates.booking_procedure_confirmation)

@router.callback_query(StateFilter(UserStates.booking_procedure_confirmation), F.data == "cancel_booking")
async def booking_cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработка отмены записи"""
    await callback.answer("Запись отменена", show_alert=False)
    await state.clear()

    await callback.message.edit_text(
    "Запись отменена. Что вы хотели бы сделать дальше?",
    reply_markup=BotKeyboards.after_cancel_booking_menu()
    )

@router.callback_query(F.data == "restart_booking")
async def restart_booking_handler(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
    "Пожалуйста, выберите процедуру, на которую вы хотите записаться:",
    reply_markup=BotKeyboards.booking_selection_menu()
    )

@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_handler(callback: types.CallbackQuery):
    await callback.answer("Возвращаемся в главное меню...")
    await callback.message.delete()
    await callback.message.answer(
    "Вы вернулись в главное меню. Воспользуйтесь клавиатурой ниже для навигации.",
    reply_markup=BotKeyboards.main_menu()
    )

@router.callback_query(StateFilter(UserStates.booking_procedure_confirmation), F.data == "confirm_booking")
async def booking_confirmation_handler(callback: types.CallbackQuery, state: FSMContext, bot_logic: SimpleBotLogic):
    """Шаг 2: Пользователь подтвердил процедуру, показываем доступное время"""
    await callback.answer()
    await callback.message.edit_text("🕐 Загружаем доступное время... Пожалуйста, подождите.")

    user_data = await state.get_data()
    procedure_name = user_data.get("procedure_name", "выбранную процедуру")

    try:
        # Проверяем наличие Google Calendar настроек
        if not hasattr(bot_logic.config, 'GOOGLE_CREDENTIALS_PATH'):
        # Fallback к ручной записи
            await callback.message.edit_text(
                f"📅 Для записи на {procedure_name} свяжитесь с администратором:\n\n"
                f"📞 Телефон: {bot_logic.config.CLINIC_PHONE}\n"
                f"🕐 Режим работы: {bot_logic.config.WORKING_HOURS}\n\n"
                f"Администратор подберет удобное время и проконсультирует по процедуре.",
                reply_markup=BotKeyboards.contact_menu()
        )
            await state.clear()
            return
        # Инициализируем Google Calendar сервис
        calendar_service = GoogleCalendarService(
            credentials_path=bot_logic.config.GOOGLE_CREDENTIALS_PATH,
            calendar_id=bot_logic.config.GOOGLE_CALENDAR_ID,
            timezone='Europe/Minsk'
        )

        # Получаем доступные слоты
        slots = await calendar_service.get_available_slots(days_ahead=14)

        if not slots:
            await callback.message.edit_text(
                f"😔 К сожалению, на ближайшие 2 недели нет свободного времени для записи на {procedure_name}.\n\n"
                f"📞 Пожалуйста, свяжитесь с администратором для записи на более поздние даты:\n"
                f"{bot_logic.config.CLINIC_PHONE}",
                reply_markup=BotKeyboards.contact_menu()
            )
            await state.clear()
            return

        # Сохраняем слоты в кэш и состояние (сериализуем для FSM)
        user_id = callback.from_user.id
        available_slots = [Slot.deserialize(s) for s in slots]
        #_available_slots_cache[user_id] = available_slots
        serialized_slots = [s.serialize() for s in available_slots]
        await state.update_data(available_slots=serialized_slots)

        # Группируем слоты по датам для лучшего отображения
        grouped_slots = group_slots_by_date(available_slots)
        dates_count = len(grouped_slots)

        text = f"📅 <b>Выберите удобное время для записи на {procedure_name}:</b>\n\n"
        text += f"📊 Найдено времени: {len(available_slots)} слотов на {dates_count} дней\n"
        text += "⏰ Выберите дату и время:"


        await callback.message.edit_text(
            text,
            reply_markup=create_time_slots_keyboard(available_slots, page=0)
        )
        await state.set_state(UserStates.booking_time_selection)

    except Exception as e:
        logger.error(f"Ошибка при получении доступного времени: {e}")
        await callback.message.edit_text(
            f"😔 Произошла ошибка при загрузке расписания.\n\n"
            f"📞 Пожалуйста, свяжитесь с администратором для записи:\n"
            f"{bot_logic.config.CLINIC_PHONE}",
            reply_markup=BotKeyboards.contact_menu()
)
        await state.clear()

def group_slots_by_date(slots):
    """Группирует слоты по датам"""
    grouped = {}
    for slot in slots:
        date = slot.date_str
        if date not in grouped:
            grouped[date] = []
        grouped[date].append(slot)
    return grouped

@router.callback_query(StateFilter(UserStates.booking_time_selection), F.data.startswith("time_page_"))
async def time_pagination_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработка пагинации по страницам времени"""
    await callback.answer()
    page = int(callback.data.split("_")[-1])
    user_data = await state.get_data()
    serialized_slots = user_data.get("available_slots", [])

    if not serialized_slots:
        await callback.message.edit_text("Ошибка загрузки времени. Попробуйте снова.")
        await state.clear()
        return

    available_slots = [Slot.deserialize(s) for s in serialized_slots]
    procedure_name = user_data.get("procedure_name", "процедуру")
    text = f"📅 <b>Выберите удобное время для записи на {procedure_name}:</b>\n\n⏰ Доступные дата и время:"

    await callback.message.edit_text(
        text,
        reply_markup=create_time_slots_keyboard(available_slots, page=page)
)

def create_time_slots_keyboard(available_slots, page=0, slots_per_page=8):
    """Создает клавиатуру с временными слотами"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    # Группируем по датам
    grouped_slots = group_slots_by_date(available_slots)
    dates = list(grouped_slots.keys())

    # Пагинация по датам
    dates_per_page = 3
    start_date_idx = page * dates_per_page
    end_date_idx = start_date_idx + dates_per_page
    page_dates = dates[start_date_idx:end_date_idx]

    buttons = []
    slot_index = 0

    # Находим индекс первого слота на этой странице
    for date in dates[:start_date_idx]:
        slot_index += len(grouped_slots[date])

    for date in page_dates:
        day_slots = grouped_slots[date]

        # Заголовок дня
        first_slot = day_slots[0]
        buttons.append([
            InlineKeyboardButton(
                text=f"📅 {date} ({first_slot.weekday})",
                callback_data="date_header"
            )
        ])

        #Слоты времени для этого дня (группами по 3)
        for i in range(0, len(day_slots), 3):
            row_buttons = []
            for j in range(i, min(i + 3, len(day_slots))):
                slot = day_slots[j]
                row_buttons.append(
                    InlineKeyboardButton(
                        text=f"⏰ {slot.time_str}",
                        callback_data=f"time_{slot_index + j}"
                    )
                )
            buttons.append(row_buttons)

        slot_index += len(day_slots)

        # Разделитель между датами
        if date != page_dates[-1]:
            buttons.append([InlineKeyboardButton(text="─────────", callback_data="separator")])

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Пред. даты", callback_data=f"time_page_{page-1}")
        )

    if end_date_idx < len(dates):
        nav_buttons.append(
            InlineKeyboardButton(text="След. даты ➡️", callback_data=f"time_page_{page+1}")
        )

    if nav_buttons:
        buttons.append(nav_buttons)
    # Кнопка отмены
    buttons.append([
        InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel_booking")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(StateFilter(UserStates.booking_time_selection), F.data.startswith("time_"))
async def time_slot_selected_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора конкретного времени"""
    await callback.answer()

    try:
        slot_index = int(callback.data.split("_")[1])
        user_data = await state.get_data()
        serialized_slots = user_data.get("available_slots", [])


        if slot_index >= len(serialized_slots):
            await callback.message.edit_text("Ошибка выбора времени. Попробуйте снова.")
            return

        # Десериализуем слот
        selected_slot = Slot.deserialize(serialized_slots[slot_index])

        procedure_name = user_data.get("procedure_name")
        # Сохраняем выбранное время (сериализованное)
        await state.update_data(selected_slot=selected_slot.serialize())

        # Запрашиваем контактные данные
        contact_text = f"""✅ <b>Выбрано время:</b> {selected_slot.display}
    🎯 <b>Процедура:</b> {procedure_name}

    📝 <b>Теперь укажите ваши контактные данные:</b>

        Напишите одним сообщением:
        1. Ваше имя и фамилия
        2. Номер телефона
        3. Дополнительные пожелания (по желанию)


        <b>Пример:</b>
        Анна Петрова
        +7 912 345-67-89
        Предпочитаю утром, есть аллергия на йод"""


        await callback.message.edit_text(contact_text)
        await state.set_state(UserStates.booking_contact_info)


    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка обработки выбора времени: {e}")
        await callback.message.edit_text("Ошибка выбора времени. Попробуйте снова.")


@router.callback_query(StateFilter(UserStates.booking_time_selection), F.data == "date_header")
async def date_header_handler(callback: types.CallbackQuery):
    """Обработка нажатия на заголовок даты (ничего не делаем)"""
    await callback.answer("Выберите время ниже")


@router.message(StateFilter(UserStates.booking_contact_info))
async def contact_info_handler(message: types.Message, state: FSMContext):
    """Обработка нажатия на заголовок даты (ничего не делаем)"""
    user_data = await state.get_data()
    selected_slot_data = user_data.get("selected_slot")
    procedure_name = user_data.get("procedure_name")

    # Сохраняем контактные данные
    await state.update_data(contact_info=message.text)

    # Формируем сообщение для финального подтверждения
    confirmation_text = f"""📋 <b>ПРОВЕРЬТЕ ДАННЫЕ ЗАПИСИ:</b>

    🎯 <b>Процедура:</b> {procedure_name}
    📅 <b>Дата и время:</b> {selected_slot_data['display']}
    👤 <b>Контактные данные:</b>
    {message.text}

    ⚠️ <b>Внимание:</b> После подтверждения время будет забронировано в календаре косметолога.

    Все данные верны?"""

    await message.answer(
        confirmation_text,
        reply_markup=create_final_confirmation_keyboard()
        )
    await state.set_state(UserStates.booking_final_confirmation)

def create_final_confirmation_keyboard():
    """Создает клавиатуру финального подтверждения"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить запись", callback_data="final_confirm_booking"),
            InlineKeyboardButton(text="🔄 Изменить время", callback_data="change_time")
        ],
        [
            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_booking")
        ]
    ])

@router.callback_query(StateFilter(UserStates.booking_final_confirmation), F.data == "final_confirm_booking")
async def final_booking_confirmation_handler(callback: types.CallbackQuery, state: FSMContext,
                                           bot_logic: SimpleBotLogic, database: Database):
    """Финальное подтверждение записи - создание записи в календаре и БД"""
    await callback.answer()
    await callback.message.edit_text("⏳ Создаем запись в календаре... Пожалуйста, подождите.")
    try:
        user_data = await state.get_data()
        selected_slot_data = user_data.get("selected_slot")
        procedure_name = user_data.get("procedure_name")
        procedure = user_data.get("procedure")
        contact_info = user_data.get("contact_info")

        # Восстанавливаем Slot
        selected_slot = Slot.deserialize(selected_slot_data)

        # Парсим контактные данные
        contact_lines = contact_info.strip().split('\n')
        client_name = contact_lines[0] if contact_lines else "Клиент"
        client_phone = contact_lines[1] if len(contact_lines) > 1 else "Не указан"

        # Создаем запись в базе данных
        booking_id = await database.create_booking(
            user_id=callback.from_user.id,
            booking_data={
                "procedure": procedure_name,
                "contact_info": contact_info,
                "preferred_time": selected_slot.display,
                "notes": f"Запись через бота. Telegram: @{callback.from_user.username}",
                "calendar_slot": selected_slot.start.isoformat()
            }
        )

        # Пытаемся создать запись в Google Calendar
        calendar_event_id = None
        if hasattr(bot_logic.config, 'GOOGLE_CREDENTIALS_PATH'):
            try:
                calendar_service = GoogleCalendarService(
                credentials_path=bot_logic.config.GOOGLE_CREDENTIALS_PATH,
                calendar_id=bot_logic.config.GOOGLE_CALENDAR_ID
            )

                calendar_event_id = await calendar_service.create_booking(
                    start_time=selected_slot.start,
                    end_time=selected_slot.end,
                    client_name=client_name,
                    client_phone=client_phone,
                    procedure=procedure_name
                )
            except Exception as e:
                logger.error(f"Ошибка создания события в календаре: {e}")

        # Формируем сообщение об успешной записи
        calendar_status = "🗓️ <b>Запись добавлена в календарь косметолога!</b>" if calendar_event_id else "📞 <b>Администратор подтвердит время записи.<b>"
        success_text = f"""✅ <b>ЗАПИСЬ УСПЕШНО СОЗДАНА!</b>

📋 <b>ДЕТАЛИ ЗАПИСИ:</b>
🆔 Номер заявки: {booking_id}
🎯 Процедура: {procedure_name}
📅 Дата и время: {selected_slot.display}
{calendar_status}
    ⏰ <b>ЧТО ДАЛЬШЕ:</b>
    1. За день до процедуры мы пришлем напоминание
    2. За час до визита - SMS с подтверждением
    3. Если нужно изменить время - звоните заранее

    📞 <b>КОНТАКТЫ:</b>
    {bot_logic.config.CLINIC_PHONE}
    🏥 {bot_logic.config.CLINIC_ADDRESS}

    ⚠️ <b>ВАЖНО:</b> Приходите за 10 минут до начала процедуры!"""

        # Уведомляем администратора
        if bot_logic.config.ADMIN_USER_ID:
            calendar_info = f"🗓️ ID события: {calendar_event_id}" if calendar_event_id else "📞 Требует подтверждения времени"
            admin_text = f"""📅 НОВАЯ ЗАПИСЬ ЧЕРЕЗ КАЛЕНДАРЬ

    👤 Клиент: {callback.from_user.full_name} (@{callback.from_user.username})
    🎯 Процедура: {procedure_name}
    📅 Время: {selected_slot.display}
    📞 Контакты: {contact_info}
    🆔 ID заявки: {booking_id}
    {calendar_info}"""

            try:
                await callback.bot.send_message(bot_logic.config.ADMIN_USER_ID, admin_text)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление администратору: {e}")

        await callback.message.answer(success_text, reply_markup=BotKeyboards.main_menu())
        await state.clear()

        # Создаем напоминания
        if hasattr(bot_logic, 'reminder_service') and bot_logic.reminder_service:
            try:
                await bot_logic.reminder_service.create_booking_reminders(
                    user_id=callback.from_user.id,
                    booking_id=booking_id,
                    appointment_time=selected_slot.start,
                    procedure_name=procedure_name
                )
            except Exception as e:
                logger.error(f"Ошибка создания напоминаний: {e}")

    except Exception as e:
        logger.error(f"Ошибка создания записи: {e}")


        error_text = f"""😔 <b>ОШИБКА ПРИ СОЗДАНИИ ЗАПИСИ</b>


    Произошла техническая ошибка. Ваша запись не была создана.


    📞 Пожалуйста, свяжитесь с администратором:
    {bot_logic.config.CLINIC_PHONE}


    Сообщите следующие данные:
    • Желаемое время: {selected_slot_data['display'] if 'selected_slot_data' in locals() else 'не определено'}
    • Процедура: {procedure_name if 'procedure_name' in locals() else 'не определена'}
    • Ваше имя: {callback.from_user.full_name}"""


        await callback.message.edit_text(error_text, reply_markup=BotKeyboards.contact_menu())
        await state.clear()

@router.callback_query(StateFilter(UserStates.booking_final_confirmation), F.data == "change_time")
async def change_time_handler(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору времени"""
    await callback.answer()


    user_data = await state.get_data()
    serialized_slots = user_data.get("available_slots", [])
    procedure_name = user_data.get("procedure_name", "процедуру")


    available_slots = [Slot.deserialize(s) for s in serialized_slots]


    text = f"📅 <b>Выберите другое время для записи на {procedure_name}:</b>\n\n⏰ Доступные дата и время:"


    await callback.message.edit_text(
        text,
        reply_markup=create_time_slots_keyboard(available_slots, page=0)
        )


    await state.set_state(UserStates.booking_time_selection)

# Обработчики отмены на всех этапах
@router.callback_query(F.data == "cancel_booking")
async def universal_cancel_booking_handler(callback: types.CallbackQuery, state: FSMContext):
    """Универсальный обработчик отмены записи на любом этапе"""
    await callback.answer()
    await state.clear()


    await callback.message.edit_text(
        "❌ Запись отменена.\n\nВы можете начать новую запись или вернуться в главное меню.",
        reply_markup=BotKeyboards.procedures_menu()
    )