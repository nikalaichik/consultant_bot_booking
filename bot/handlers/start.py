from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from bot.keyboards import BotKeyboards
from bot.states import UserStates
from data.database import Database
from config import Config
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import logging

router = Router()
logger = logging.getLogger(__name__)

@router.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext, database: Database):
    await state.clear()
    user_data = {
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "last_name": message.from_user.last_name
    }
    await database.get_or_create_user(message.from_user.id, user_data)
    welcome_text = """👋 Добро пожаловать в косметологическую клинику E-clinic!

Я - ваш AI-ассистент. Помогу с:
💬 Консультациями по процедурам
📅 Записью на прием
💰 Информацией о ценах
🆘 Экстренными вопросами

Просто напишите ваш вопрос или выберите в меню 👇"""
    await message.answer(welcome_text, reply_markup=BotKeyboards.main_menu())

@router.message(Command("menu"))
async def menu_handler(message: types.Message):
    """
    Обработчик команды /menu. Показывает главное меню.
    """
    await message.answer(
        "Вы в главном меню. Воспользуйтесь кнопками ниже 👇",
        reply_markup=BotKeyboards.main_menu()
    )

@router.message(F.text == "💬 Консультация")
async def consultation_start(message: types.Message, state: FSMContext):
    text = "🔍 ПЕРСОНАЛЬНАЯ КОНСУЛЬТАЦИЯ...\nВыберите ваш тип кожи"
    await message.answer(text, reply_markup=BotKeyboards.skin_type_menu())
    await state.set_state(UserStates.waiting_for_skin_type)

# Обработка кнопки "💰 Цены" в главном меню
# Общая логика
async def _send_prices_menu(target):
    await target.answer(
        "Выберите категорию процедур, чтобы узнать цены:",
        reply_markup=BotKeyboards.prices_menu()
    )

# Обработка кнопки "💰 Цены" из ReplyKeyboard
@router.message(F.text == "💰 Цены")
async def show_prices_menu_message(message: types.Message):
    await _send_prices_menu(message)

# Обработка кнопки "💰 Узнать цены" из InlineKeyboard
@router.callback_query(F.data == "get_prices")
async def show_prices_menu_callback(callback: types.CallbackQuery):
    await _send_prices_menu(callback.message)
    await callback.answer()  # чтобы убрать "часики"

# Обработка выбора категории в меню цен
@router.callback_query(F.data.startswith("price_"))
async def show_category_prices(callback: types.CallbackQuery):
    prices = {
        "price_cleaning": (
            "🧼 Чистка лица:\n"
            "• Ультразвуковая — 4000–6000 ₽\n"
            "• Комбинированная — 5000–7000 ₽"
        ),
        "price_carboxy": (
            "💨 Карбокситерапия:\n"
            "• 1 процедура — 3000–5000 ₽\n"
            "• Курс (6–10 процедур)"
        ),
        "price_microneedling": (
            "🎯 Микронидлинг:\n"
            "• Одна процедура — 5000–9000 ₽"
        ),
        "price_mesopeel": (
            "🔄 Мезопилинг:\n"
            "• Одна процедура — 4000–8000 ₽"
        ),
        "price_massage": (
            "👐 Массажи лица:\n"
            "• Кобидо — 5000–7500 ₽\n"
            "• Буккальный — 4500–7000 ₽\n"
            "• 3D массаж — 4000–6000 ₽"
        ),
    }

    answer = prices.get(callback.data, "❌ Цены не найдены")
    await callback.message.edit_text(
        text=answer,
        reply_markup=BotKeyboards.prices_menu()
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    '''await callback.message.answer(
        "Главное меню:",
        reply_markup=BotKeyboards.main_menu()
    )'''
    await callback.message.delete()  # чтобы старое сообщение с inline убрать
    await callback.answer()

# Обработка кнопки "Контакты" в главном меню
@router.message(F.text == "📞 Контакты")
async def show_contacts(message: types.Message):
    await message.answer(
    f"""Здравствуйте! Вот наши контактные данные:
    КОНТАКТЫ КЛИНИКИ:

    📞 Телефон:{Config.CLINIC_PHONE}

    📍 Адрес: {Config.CLINIC_ADDRESS}

    🕐 Режим: {Config.WORKING_HOURS}

Если у вас есть вопросы о процедурах или вы хотите записаться на консультацию, я буду рада помочь!""",
reply_markup=BotKeyboards.main_menu())

# Обработка кнопки "О клинике" в главном меню
@router.message(F.text == "🏥 О клинике")
async def show_about(message: types.Message):
    await message.answer(
    "Здравствуйте! Вот информация о нашей клинике: \n\n\n Если у вас есть вопросы о процедурах или вы хотите записаться на консультацию, я буду рад помочь!",
reply_markup=BotKeyboards.main_menu())

# Обработка кнопки "Помощь" в главном меню
@router.message(F.text == "❓ Помощь")
async def show_help(message: types.Message):
    await message.answer(
    f"Здравствуйте! Если вам нужна помощь, свяжитесь с админом: {Config.ADMIN_USERNAME}",
reply_markup=BotKeyboards.main_menu())

@router.callback_query(F.data == "booking")
async def booking(callback: types.CallbackQuery, state: FSMContext):
  await callback.message.answer(
        "Отлично! Пожалуйста, выберите процедуру, на которую вы хотите записаться:",
        reply_markup=BotKeyboards.booking_selection_menu()
    )
@router.message(F.text == "📅 Записаться")
async def booking_entrypoint(message: types.Message):
    """
    Отвечает на кнопку 'Записаться' из главного меню,
    предлагая выбрать процедуру.
    """
    await message.answer(
        "Отлично! Пожалуйста, выберите процедуру, на которую вы хотите записаться:",
        reply_markup=BotKeyboards.booking_selection_menu()
    )

@router.message(F.text == "🔔 Мои напоминания")
async def my_reminders_handler(message: types.Message, database: Database):
    """Обработчик кнопки 'Мои напоминания'"""
    try:
        reminders = await database.get_user_reminders(message.from_user.id)
        logger.info(f"Найдено напоминаний: {len(reminders)}")
        if not reminders:
            await message.answer(
                "📭 У вас пока нет напоминаний.",
                reply_markup=BotKeyboards.main_menu()
            )
            return
        local_tz = ZoneInfo("Europe/Minsk")  # локальная таймзона

        text = "📋 <b>ВАШИ НАПОМИНАНИЯ:</b>\n\n"

        for reminder in reminders[:5]:  # Показываем последние 5
            status_emoji = {
                'pending': '⏳ Ожидает',
                'sent': '✅ Отправлено',
                'failed': '❌ Ошибка',
                'cancelled': '🚫 Отменено'
            }.get(reminder['status'], '❓ Неизвестно')

            # Парсим время
            try:
                if isinstance(reminder['scheduled_time'], str):
                    scheduled_time = datetime.fromisoformat(reminder['scheduled_time'])
                else:
                    scheduled_time = reminder['scheduled_time']

                if scheduled_time.tzinfo:
                    scheduled_time = scheduled_time.astimezone(local_tz)
                else:
                    scheduled_time = scheduled_time.replace(tzinfo=timezone.utc).astimezone(local_tz)

                time_str = scheduled_time.strftime('%d.%m.%Y %H:%M')
            except:
                time_str = str(reminder['scheduled_time'])

            # Определяем тип напоминания
            reminder_type_text = {
                'day_before': 'За день до визита',
                'hour_before': 'За 2 часа до визита',
                'custom': 'Пользовательское'
            }.get(reminder['reminder_type'], reminder['reminder_type'])

            text += f"📅 <b>{time_str}</b>\n"
            text += f"🔔 {reminder_type_text}\n"
            if reminder.get('procedure'):
                text += f"🎯 {reminder['procedure']}\n"
            text += f"📊 {status_emoji}\n\n"

        if len(reminders) > 5:
            text += f"... и еще {len(reminders) - 5} напоминаний"

        await message.answer(text, reply_markup=BotKeyboards.main_menu())

    except Exception as e:
        logger.error(f"Ошибка при получении напоминаний: {e}")
        await message.answer(
            "😔 Произошла ошибка при загрузке напоминаний.",
            reply_markup=BotKeyboards.main_menu()
        )