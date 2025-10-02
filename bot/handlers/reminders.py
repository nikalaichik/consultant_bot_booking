from aiogram import Router, F, types
from data.database import Database
from datetime import datetime

router = Router()

@router.callback_query(F.data == "my_reminders")
async def show_user_reminders(callback: types.CallbackQuery, database: Database):
    """Показывает напоминания пользователя"""
    await callback.answer()

    try:
        reminders = await database.get_user_reminders(callback.from_user.id)

        if not reminders:
            await callback.message.edit_text(
                "📭 У вас пока нет активных напоминаний.",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
                    types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
                ]])
            )
            return

        text = "📋 **ВАШИ НАПОМИНАНИЯ:**\n\n"

        for reminder in reminders[:10]:  # Показываем последние 10
            status_emoji = {
                'pending': '⏳',
                'sent': '✅',
                'failed': '❌',
                'cancelled': '🚫'
            }.get(reminder['status'], '❓')

            scheduled_time = datetime.fromisoformat(reminder['scheduled_time'])
            text += f"{status_emoji} **{reminder['reminder_type']}**\n"
            text += f"📅 {scheduled_time.strftime('%d.%m.%Y %H:%M')}\n"
            if reminder['procedure']:
                text += f"🎯 {reminder['procedure']}\n"
            text += f"📊 Статус: {reminder['status']}\n\n"

        await callback.message.edit_text(
            text,
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
            ]])
        )

    except Exception as e:
        await callback.message.edit_text(
            "😔 Произошла ошибка при загрузке напоминаний.",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
            ]])
        )