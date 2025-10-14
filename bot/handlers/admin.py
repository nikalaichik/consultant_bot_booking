import logging
import asyncio
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from bot.keyboards import BotKeyboards
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from data.database import Database
from config import Config
from services.bot_logic import SimpleBotLogic
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

router = Router()

class BroadcastState(StatesGroup):
    waiting_for_message = State()
    waiting_for_confirmation = State()

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast")]
    ])
# Административные команды
@router.message(Command("admin"))
async def admin_panel(message: types.Message, bot_logic: SimpleBotLogic, database: Database ):
    """Административная панель"""
    if message.from_user.id != bot_logic.config.ADMIN_USER_ID:
        await message.answer("❌ Доступ запрещен")
        return

    # Получаем статистику
    analytics = await database.get_analytics_data(days=7)

    admin_text = f"""👨‍💼 АДМИНИСТРАТИВНАЯ ПАНЕЛЬ

📊 СТАТИСТИКА ЗА 7 ДНЕЙ:
• Новых пользователей: {analytics.get('new_users', 0)}
• Диалогов: {analytics.get('conversations', 0)}

📋 ОЖИДАЮЩИЕ ЗАПИСИ:"""

    # Получаем ожидающие записи
    pending_bookings = await database.get_pending_bookings()

    if pending_bookings:
        for booking in pending_bookings[:5]:
            admin_text += f"""

🆔 Заявка {booking['id']}
👤 {booking['first_name']} {booking['last_name']}
🎯 {booking['procedure']}
📅 {booking['created_at'][:16]}"""
        if len(pending_bookings) > 5:
            admin_text += "\n\n…и ещё заявки. Нажмите кнопку ниже, чтобы посмотреть все."
    else:
        admin_text += "\n\n✅ Новых заявок нет"

    admin_keyboard = BotKeyboards.admin_menu(show_all_bookings=bool(pending_bookings))
    await message.answer(admin_text, reply_markup=admin_keyboard)

@router.callback_query(F.data == "admin_all_bookings")
async def admin_all_bookings_handler(callback: types.CallbackQuery, database: Database, bot_logic: SimpleBotLogic):
    """Показать все заявки в админке"""
    if callback.from_user.id != bot_logic.config.ADMIN_USER_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    bookings = await database.get_pending_bookings()
    if not bookings:
        await callback.message.edit_text("✅ Новых заявок нет", reply_markup=BotKeyboards.admin_menu())
        return

    text = "📋 ВСЕ ОЖИДАЮЩИЕ ЗАПИСИ:\n"
    for booking in bookings:
        text += f"""

🆔 {booking['id']}
👤 {booking['first_name']} {booking['last_name']}
🎯 {booking['procedure']}
📅 {booking['created_at'][:16]}"""

    await callback.message.edit_text(text, reply_markup=BotKeyboards.admin_menu())
    await callback.answer()

@router.callback_query(F.data == "start_broadcast")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != Config.ADMIN_USER_ID:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    await callback.message.edit_text(
        "Пришлите сообщение, которое хотите разослать пользователям. Это может быть текст или фото с подписью.",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.answer()

# --- Отмена на любом этапе ---
@router.callback_query(F.data == "cancel_broadcast")
async def cancel_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Рассылка отменена.")
    await callback.answer()

# --- Получение сообщения для рассылки ---
@router.message(StateFilter(BroadcastState.waiting_for_message))
async def get_broadcast_message(message: types.Message, state: FSMContext, database: Database):
    if not (message.text or message.photo):
        await message.answer("Пожалуйста, отправьте текст или фото.", reply_markup=cancel_keyboard())
        return

    # Сохраняем сообщение в FSM
    await state.update_data(
        text=message.text or message.caption,
        photo_id=message.photo[-1].file_id if message.photo else None
    )

    # Получаем количество пользователей для подтверждения
    users_count = len(await database.get_all_users())

    await message.answer(
        f"Ваше сообщение готово к отправке.\n\n"
        f"Получателей: <b>{users_count}</b>\n\n"
        f"Отправляем?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_broadcast")],
            [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="cancel_broadcast")]
        ])
    )
    await state.set_state(BroadcastState.waiting_for_confirmation)

# --- Подтверждение и запуск рассылки ---
@router.callback_query(StateFilter(BroadcastState.waiting_for_confirmation), F.data == "confirm_broadcast")
async def confirm_and_start_broadcast(callback: types.CallbackQuery, state: FSMContext, bot: Bot, database: Database):
    await callback.message.edit_text("✅ Начинаю рассылку...")

    data = await state.get_data()
    users = await database.get_all_users()

    # Запускаем отправку в фоновой задаче, чтобы не блокировать бота
    asyncio.create_task(broadcast_sender(bot, users, data, callback.from_user.id))

    await state.clear()
    await callback.answer()

# --- САМА ФУНКЦИЯ РАССЫЛКИ ---
async def broadcast_sender(bot: Bot, users: list[int], data: dict, admin_id: int):
    """
    Асинхронно отправляет сообщение всем пользователям с обработкой ошибок и задержкой.
    """
    success_count = 0
    fail_count = 0
    start_time = asyncio.get_event_loop().time()

    for user_id in users:
        try:
            if data.get("photo_id"):
                await bot.send_photo(user_id, data["photo_id"], caption=data.get("text"))
            else:
                await bot.send_message(user_id, data["text"])

            success_count += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            fail_count += 1

        # Задержка 0.1 секунды (10 сообщений в секунду) - безопасно для лимитов Telegram
        await asyncio.sleep(0.1)

    end_time = asyncio.get_event_loop().time()
    total_time = round(end_time - start_time, 2)

    # Отправляем отчет администратору
    await bot.send_message(
        admin_id,
        f"📢 Рассылка завершена за {total_time} сек.\n\n"
        f"✅ Успешно отправлено: {success_count}\n"
        f"❌ Не удалось отправить: {fail_count}"
    )