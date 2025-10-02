import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from bot.keyboards import BotKeyboards
from data.database import Database
from services.bot_logic import SimpleBotLogic

logger = logging.getLogger(__name__)

router = Router()
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

🆔 Заявка #{booking['id']}
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

🆔 #{booking['id']}
👤 {booking['first_name']} {booking['last_name']}
🎯 {booking['procedure']}
📅 {booking['created_at'][:16]}"""

    await callback.message.edit_text(text, reply_markup=BotKeyboards.admin_menu())
    await callback.answer()