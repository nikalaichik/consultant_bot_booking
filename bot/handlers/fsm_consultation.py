from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

# Импортируем состояния, клавиатуры и нашу основную логику
from bot.states import UserStates
from bot.keyboards import BotKeyboards
from services.bot_logic import SimpleBotLogic
from data.database import Database
# Создаем новый роутер специально для этого сценария
router = Router()

# Этот обработчик ловит нажатие на кнопку выбора типа кожи,
# но ТОЛЬКО если бот находится в состоянии "ожидания типа кожи".
@router.callback_query(StateFilter(UserStates.waiting_for_skin_type), F.data.startswith("skin_"))
async def skin_type_selected(callback: types.CallbackQuery, state: FSMContext):
    """Шаг 1: Пользователь выбрал тип кожи."""
    skin_type = callback.data.replace("skin_", "")
    await state.update_data(skin_type=skin_type)

    # Редактируем сообщение, чтобы убрать старые кнопки и задать новый вопрос
    await callback.message.edit_text(
        "👤 Спасибо! Теперь выберите ваш возраст:",
        reply_markup=BotKeyboards.age_group_menu()
    )
    # Переводим пользователя на следующий шаг сценария
    await state.set_state(UserStates.waiting_for_age)
    await callback.answer() # Отвечаем на колбэк, чтобы убрать "часики"


# Этот обработчик ловит нажатие на кнопку выбора возраста,
# но ТОЛЬКО если бот находится в состоянии "ожидания возраста".
@router.callback_query(StateFilter(UserStates.waiting_for_age), F.data.startswith("age_"))
async def age_selected(callback: types.CallbackQuery, state: FSMContext):
    """Шаг 2: Пользователь выбрал возраст."""
    age_group = callback.data.replace("age_", "")
    await state.update_data(age_group=age_group)

    await callback.message.edit_text(
        """📝 Отлично! Теперь кратко опишите основные проблемы или то, что вас беспокоит.

Например: <i>"Появились мелкие морщинки вокруг глаз, тусклый цвет лица"</i>.
Или просто отправьте фото кожи 📸"""
    )
    # Переводим на следующий шаг
    await state.set_state(UserStates.waiting_for_problem_description)
    await callback.answer()

# Этот обработчик ловит текстовое сообщение,
# но ТОЛЬКО если бот находится в состоянии "ожидания описания проблемы".
@router.message(StateFilter(UserStates.waiting_for_problem_description))
async def problem_description_handler(message: types.Message, state: FSMContext, bot_logic: SimpleBotLogic, database: Database):
    """Шаг 3: Пользователь прислал описание проблемы. Финал сценария."""
    user_data = await state.get_data()

    # Обновляем профиль в сессии и базе данных (как в вашем коде)
    # Обновляем профиль в базе данных
    profile_data = {
        "skin_type": user_data.get("skin_type"),
        "age_group": user_data.get("age_group")
    }
    await database.update_user_profile(message.from_user.id, profile_data)

    # Обновляем сессию
    user_session = await bot_logic.session_manager.get_user_session(message.from_user.id)
    user_session["user_profile"] = {
        **user_session.get("user_profile", {}),
        **profile_data,
        "problems_description": message.text
    }
    await bot_logic.session_manager.update_user_session(message.from_user.id, user_session)

    # Формируем умный запрос для RAG
    enhanced_query = f"""
    Дай персональную рекомендацию по процедурам.
    Тип кожи клиента: {user_data.get('skin_type', 'не указан')}
    Возрастная группа: {user_data.get('age_group', 'не указана')}
    Описание проблемы от клиента: {message.text}
    """

    # Показываем, что бот "думает"
    await message.answer("🔍 Анализирую ваши данные и подбираю лучшие процедуры. Это может занять несколько секунд...")

    # Вызываем нашу основную логику
    response, _ = await bot_logic.process_message(message.from_user.id, enhanced_query)

    await message.bot.send_chat_action(message.chat.id, "typing")
    # Генерируем динамическую клавиатуру на основе ответа бота
    dynamic_keyboard = BotKeyboards.create_dynamic_booking_keyboard(response)

    # Отправляем результат
    await message.answer(
        f"✅ <b>Готово! Вот мои рекомендации на основе предоставленной информации:</b>\n\n{response}",
        reply_markup=dynamic_keyboard
    )

    # Обязательно очищаем состояние, завершая сценарий
    await state.clear()