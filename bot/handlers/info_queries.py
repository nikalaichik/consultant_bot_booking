from aiogram import Router, F, types
from services.bot_logic import SimpleBotLogic
from bot.keyboards import BotKeyboards
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()

    # Обработчики процедур
@router.callback_query(F.data.startswith("proc_"))
async def procedure_info_handler(callback: types.CallbackQuery, bot_logic: SimpleBotLogic):
    """Информация о процедурах"""
    procedure = callback.data.replace("proc_", "")

    procedure_queries = {
        "cleaning": "чистка лица виды стоимость показания противопоказания",
        "carboxy": "карбокситерапия стоимость эффекты показания курс",
        "microneedling": "микронидлинг dermapen цена курс противопоказания",
        "massage": "массаж лица виды стоимость эффекты",
        "mesopeel": "мезопилинг стоимость показания курс"
    }

    query = procedure_queries.get(procedure, f"процедура {procedure}")
    response, _ = await bot_logic.process_message(callback.from_user.id, query)

    # Добавляем кнопку записи
    booking_keyboard = BotKeyboards.procedure_booking_menu(procedure)
    await callback.message.edit_text(response, reply_markup=booking_keyboard)

@router.callback_query(F.data.startswith("ask_"))
async def ask_procedure_handler(callback: types.CallbackQuery, bot_logic: SimpleBotLogic):
    """Обработка кнопки 'Задать вопрос' для процедуры"""
    procedure = callback.data.replace("ask_", "")
    await callback.answer()

    await callback.message.answer(
        f"✍️ Напишите ваш вопрос по процедуре «{procedure}», и я отвечу."
    )
    # сохранять процедуру в сессии можно, если нужно уточнение


@router.callback_query(F.data == "back_to_procedures")
async def back_to_procedures_handler(callback: types.CallbackQuery):
    """Возврат к списку процедур"""
    await callback.answer()
    await callback.message.edit_text(
        "📋 Доступные процедуры:",
        reply_markup=BotKeyboards.procedures_menu()
    )

# Экстренные ситуации
@router.callback_query(F.data.startswith("emergency_"))
async def emergency_handler(callback: types.CallbackQuery, bot_logic: SimpleBotLogic):
    """Обработка экстренных ситуаций"""
    emergency_type = callback.data.replace("emergency_", "")

    # Поиск в базе знаний по экстренным ситуациям
    emergency_query = f"экстренная помощь {emergency_type} первая помощь"
    response, _ = await bot_logic.process_message(callback.from_user.id, emergency_query)

    # Добавляем контакты экстренной связи
    emergency_contacts = f"""

📞 ЭКСТРЕННЫЕ КОНТАКТЫ:
Косметолог: {bot_logic.config.CLINIC_PHONE}
Скорая помощь: 103
WhatsApp: {bot_logic.config.CLINIC_PHONE}"""

    full_response = response + emergency_contacts

    await callback.message.edit_text(full_response)

    # Уведомляем администратора об экстренной ситуации
    if bot_logic.config.ADMIN_USER_ID:
        admin_alert = f"""🚨 ЭКСТРЕННАЯ СИТУАЦИЯ

👤 Пользователь: {callback.from_user.full_name}
📱 @{callback.from_user.username}
⚠️ Тип: {emergency_type}
⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}

Клиент обратился за экстренной помощью!"""

        try:
            await callback.bot.send_message(bot_logic.config.ADMIN_USER_ID, admin_alert)
        except:
            logger.error("Не удалось уведомить администратора об экстренной ситуации")