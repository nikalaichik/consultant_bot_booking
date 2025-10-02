from aiogram import Router, F, types
from services.bot_logic import SimpleBotLogic
from bot.keyboards import BotKeyboards
from utils.security import sanitize_for_model
from utils.rate_limiter import rate_limit
import logging

logger = logging.getLogger(__name__)

router = Router()

# Этот хендлер ловит любые текстовые сообщения, не подошедшие под фильтры выше.
@router.message(F.text)
@rate_limit("text")
async def general_message_handler(message: types.Message, bot_logic: SimpleBotLogic):
    await message.bot.send_chat_action(message.chat.id, "typing")
    # очищаем ввод перед передачей в логику
    clean_text = sanitize_for_model(message.text)
    try:
        response, metadata = await bot_logic.process_message(
            user_id=message.from_user.id,
            message=clean_text
        )
        # Определяем нужна ли дополнительная клавиатура
        keyboard = None
        intent = metadata.get("intent")

        if intent == "booking":
            keyboard = BotKeyboards.procedures_menu()
        elif intent == "emergency":
            keyboard = BotKeyboards.emergency_menu()
        elif intent == "consultation":
            keyboard = BotKeyboards.booking_menu()

        await message.answer(response, reply_markup=keyboard)

    except Exception as e:
        logger.exception(f"Ошибка в general_message_handler: {e}")
        await message.answer(
            "😔 Произошла ошибка. Попробуйте позже или обратитесь по телефону.",
            reply_markup=BotKeyboards.contact_menu()
        )