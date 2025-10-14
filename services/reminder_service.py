import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from data.database import Database
from aiogram import Bot

logger = logging.getLogger(__name__)

class ReminderService:
    """Сервис для управления напоминаниями"""

    def __init__(self, database: Database, bot: Bot):
        self.database = database
        self.bot = bot
        self.reminder_task = None
        self.is_running = False

    async def start(self):
        """Запускает сервис напоминаний"""
        if self.reminder_task is None:
            self.is_running = True
            self.reminder_task = asyncio.create_task(self._reminder_loop())
            logger.info("Сервис напоминаний запущен")

    async def stop(self):
        """Останавливает сервис напоминаний"""
        self.is_running = False
        if self.reminder_task:
            self.reminder_task.cancel()
            try:
                await self.reminder_task
            except asyncio.CancelledError:
                pass
            self.reminder_task = None
            logger.info("Сервис напоминаний остановлен")

    async def _reminder_loop(self):
        """Основной цикл проверки и отправки напоминаний"""
        while self.is_running:
            try:
                # Проверяем напоминания каждые 30 секунд
                await self._check_and_send_reminders()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле напоминаний: {e}", exc_info=True)
                await asyncio.sleep(60)  # Ждем минуту при ошибке

    async def _check_and_send_reminders(self):
        """Проверяет и отправляет готовые напоминания"""
        try:
            reminders = await self.database.get_pending_reminders()

            for reminder in reminders:
                try:
                    await self._send_reminder(reminder)
                    await self.database.mark_reminder_sent(reminder['id'])
                    logger.info(f"Отправлено напоминание {reminder['id']} пользователю {reminder['user_id']}")

                    # Небольшая задержка между отправками
                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"Ошибка отправки напоминания {reminder['id']}: {e}")
                    await self.database.mark_reminder_failed(reminder['id'])

        except Exception as e:
            logger.error(f"Ошибка при проверке напоминаний: {e}", exc_info=True)

    async def _send_reminder(self, reminder: Dict):
        """Отправляет конкретное напоминание"""
        try:
            await self.bot.send_message(
                chat_id=reminder['user_id'],
                text=reminder['message_text'],
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Не удалось отправить напоминание пользователю {reminder['user_id']}: {e}")
            raise

    async def create_booking_reminders(self, user_id: int, booking_id: int,
                                     appointment_time: datetime, procedure_name: str):
        """Создает стандартные напоминания для записи"""
        try:
            # Напоминание за день
            # Конвертируем его в UTC.
            appointment_time_utc = appointment_time.astimezone(timezone.utc)
            # Напоминание за день
            day_before = appointment_time_utc - timedelta(days=1)
            # Напоминание за день
            if day_before > datetime.now(timezone.utc):
                day_message = f"""📅 **НАПОМИНАНИЕ О ЗАПИСИ**

Завтра у вас запись на процедуру:
🎯 **{procedure_name}**
⏰ **{appointment_time.strftime('%d.%m.%Y в %H:%M')}**

📍 Не забудьте прийти за 10 минут до начала!

🔸 Если нужно перенести - звоните заранее

_Ждем вас!_"""

                await self.database.create_reminder(
                    user_id=user_id,
                    booking_id=booking_id,
                    reminder_type='day_before',
                    scheduled_time=day_before,
                    message_text=day_message
                )

            # Напоминание за 2 часа
            two_hours_before = appointment_time_utc - timedelta(hours=2)
            if two_hours_before > datetime.now(timezone.utc):
                hour_message = f"""⏰ **НАПОМИНАНИЕ**

Через 2 часа у вас запись:
🎯 **{procedure_name}**
⏰ **{appointment_time.strftime('%H:%M')}**

📍 Не забудьте выехать вовремя!
🚗 Учтите время на дорогу и парковку

_До встречи!_"""

                await self.database.create_reminder(
                    user_id=user_id,
                    booking_id=booking_id,
                    reminder_type='hour_before',
                    scheduled_time=two_hours_before,
                    message_text=hour_message
                )

            logger.info(f"Созданы напоминания для записи {booking_id} пользователя {user_id}")

        except Exception as e:
            logger.error(f"Ошибка создания напоминаний: {e}", exc_info=True)

    async def cancel_booking_reminders(self, booking_id: int):
        """Отменяет напоминания для конкретной записи"""
        try:
            async with self.database.get_connection() as conn:
                await conn.execute("""
                    UPDATE reminders
                    SET status = 'cancelled'
                    WHERE booking_id = ? AND status = 'pending'
                """, (booking_id,))
                await conn.commit()

            logger.info(f"Отменены напоминания для записи {booking_id}")
        except Exception as e:
            logger.error(f"Ошибка отмены напоминаний для записи {booking_id}: {e}")