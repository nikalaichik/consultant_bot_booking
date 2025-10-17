from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,

)
from datetime import datetime
import logging
from config import Config
from bot.keyboards import BotKeyboards
import asyncio

logger = logging.getLogger(__name__)
router = Router()

# === handlers ===

@router.message(F.text.lower() == "мои записи")
async def show_my_bookings(message: Message, bot_logic):
    """Показывает пользователю его записи из календаря."""
    user_id = message.from_user.id
    events = await bot_logic.get_user_bookings(user_id)

    if not events:
        await message.answer("У вас пока нет активных записей 😊")
        return

    await message.answer("Ваши предстоящие записи:", reply_markup=BotKeyboards.build_bookings_keyboard(events))


@router.callback_query(F.data.startswith("choose_cancel:"))
async def ask_cancel_confirmation(callback: CallbackQuery, bot_logic):
    """Показывает подтверждение отмены."""
    event_id = callback.data.split(":", 1)[1]
    await callback.message.edit_text(
        "Вы уверены, что хотите отменить эту запись?",
        reply_markup=BotKeyboards.confirm_keyboard(event_id)
    )


@router.callback_query(F.data.startswith("confirm_cancel:"))
async def confirm_cancel(callback: CallbackQuery, bot_logic, bot):
    """Удаляет запись из календаря и уведомляет админа."""
    event_id = callback.data.split(":", 1)[1]
    # Сначала показываем пользователю, что мы работаем
    await callback.message.edit_text("🔄 Отменяем запись...")

    ok = await bot_logic.cancel_booking(event_id)

    if ok:
        # Даем Google API секунду на обновление
        await asyncio.sleep(1)

        # Уведомляем администратора
        admin_id = getattr(Config, "ADMIN_CHAT_ID", None)
        if admin_id:
            user = callback.from_user
            username = f"@{user.username}" if user.username else f"id:{user.id}"
            try:
                await bot.send_message(admin_id, f"🚫 Клиент {username} отменил запись.")
            except Exception as e:
                logger.error(f"Не удалось уведомить администратора: {e}")
        await callback.message.edit_text("✅ Запись успешно отменена.")

        # Сразу запрашиваем обновленный список записей
        user_id = callback.from_user.id
        events = await bot_logic.get_user_bookings(user_id)
        if events:
            # Если записи еще есть, показываем их
            await callback.message.edit_text(
                "✅ Запись успешно отменена. Вот ваши оставшиеся записи:",
                reply_markup=BotKeyboards.build_bookings_keyboard(events)
            )
        else:
            # Если это была последняя запись
            await callback.message.edit_text("✅ Запись успешно отменена. У вас больше нет активных записей.")

    else:
        await callback.message.edit_text("❌ Не удалось отменить запись. Попробуйте позже.")


@router.callback_query(F.data == "cancel_back")
async def cancel_back(callback: CallbackQuery, bot_logic):
    """Возврат к списку записей без отмены."""
    user_id = callback.from_user.id
    events = await bot_logic.get_user_bookings(user_id)

    if not events:
        await callback.message.edit_text("У вас пока нет активных записей 😊")
        return

    await callback.message.edit_text("Ваши предстоящие записи: \n При необхоимости вы можете отменить запись, нажав на кнопку с информацией о записи.", reply_markup=BotKeyboards.build_bookings_keyboard(events))
