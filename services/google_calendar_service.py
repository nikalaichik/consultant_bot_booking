import logging
import pytz
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import asyncio

logger = logging.getLogger(__name__)

class GoogleCalendarService:
    """Сервис для работы с Google Calendar API"""

    def __init__(self,  credentials_path: str, calendar_id: str, timezone: str = 'Europe/Minsk'):
        self.credentials_path = credentials_path
        self.calendar_id = calendar_id
        self.timezone = pytz.timezone(timezone)
        self.service = None
        self._initialize_service()

    def _initialize_service(self):
        """Инициализация Google Calendar API"""
        try:
            # Области доступа для календаря
            SCOPES = ['https://www.googleapis.com/auth/calendar']

            # Загружаем credentials из JSON файла
            credentials = Credentials.from_service_account_file(
                self.credentials_path,
                scopes=SCOPES
            )

            # Создаем сервис
            self.service = build('calendar', 'v3', credentials=credentials)
            logger.info("Google Calendar API успешно инициализирован")

        except Exception as e:
            logger.error(f"Ошибка инициализации Google Calendar API: {e}")
            raise

    def _localize_datetime(self, dt: datetime) -> datetime:
        """Приводит datetime к локальному часовому поясу"""
        if dt.tzinfo is None:
            return self.timezone.localize(dt)
        return dt.astimezone(self.timezone)

    def _to_utc_isoformat(self, dt: datetime) -> str:
        """Конвертирует datetime в UTC ISO формат для Google Calendar API"""
        if dt.tzinfo is None:
            dt = self.timezone.localize(dt)
        return dt.astimezone(pytz.UTC).isoformat().replace('+00:00', 'Z')

    async def get_available_slots(self, days_ahead: int = 14, slot_duration_minutes: int = 60) -> List[Dict]:
        """
        Получает доступные временные слоты на указанное количество дней вперед

        Args:
            days_ahead: количество дней для поиска
            slot_duration_minutes: длительность слота в минутах

        Returns:
            List[Dict]: список доступных слотов
        """
        try:
            # Определяем временные границы
            now = datetime.now(self.timezone)
            # Начинаем с завтрашнего дня если уже поздно
            if now.hour >= 18:
                start_time = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            else:
                # Начинаем с текущего дня, но не раньше чем через 2 часа
                min_start = now + timedelta(hours=2)
                start_time = max(
                    min_start,
                    now.replace(hour=9, minute=0, second=0, microsecond=0)
                )

            end_time = start_time + timedelta(days=days_ahead)
            logger.info(f"Поиск слотов с {start_time} по {end_time}")
            # Выполняем запрос к календарю в отдельном потоке
            busy_slots = await asyncio.to_thread(
                self._get_busy_slots,
                start_time,
                end_time
            )

            # Генерируем доступные слоты
            available_slots = self._generate_available_slots(
                start_time,
                end_time,
                busy_slots,
                slot_duration_minutes
            )

            logger.info(f"Найдено {len(available_slots)} доступных слотов")
            return available_slots

        except Exception as e:
            logger.error(f"Ошибка получения доступных слотов: {e}")
            return []

    def _get_busy_slots(self, start_time: datetime, end_time: datetime) -> List[Tuple[datetime, datetime]]:
        """Получает занятые временные слоты из календаря"""
        try:
            # Конвертируем в UTC для API запроса
            start_utc = self._to_utc_isoformat(start_time)
            end_utc = self._to_utc_isoformat(end_time)

            logger.debug(f"Запрос событий: {start_utc} - {end_utc}")
            # Запрос к Calendar API
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_utc,
                timeMax=end_utc,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            busy_slots = []

            for event in events:
                try:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    end = event['end'].get('dateTime', event['end'].get('date'))

                    if not start or not end:
                        continue

                    # Парсим даты и приводим к локальному времени
                    if 'T' in start:  # datetime
                        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    # Приводим к локальному часовому поясу
                        start_dt = start_dt.astimezone(self.timezone)
                        end_dt = end_dt.astimezone(self.timezone)

                        busy_slots.append((start_dt, end_dt))
                        logger.debug(f"Занят слот: {start_dt} - {end_dt}")
                        # События на весь день пропускаем

                except Exception as e:
                    logger.warning(f"Ошибка парсинга события: {e}")
                    continue

            logger.info(f"Найдено {len(busy_slots)} занятых слотов")
            return busy_slots

        except HttpError as error:
            logger.error(f"Ошибка API при получении событий: {error}")
            return []

    def _generate_available_slots(self, start_time: datetime, end_time: datetime,
                                busy_slots: List[Tuple[datetime, datetime]],
                                slot_duration_minutes: int) -> List[Dict]:
        """Генерирует доступные временные слоты"""
        available_slots = []

        slot_duration = timedelta(minutes=slot_duration_minutes)

        # Рабочие часы (можно вынести в конфиг)
        WORK_START = 9  # 9:00
        WORK_END = 18   # 20:00
        WORK_DAYS = [0, 1, 2, 3, 4, 5]  # Пн-Сб (0=понедельник)
        SLOT_INTERVAL = 60  # минут между слотами

        # Группируем по дням для лучшего отображения
        current_date = start_time.date()
        end_date = end_time.date()

        while current_date < end_date:
            # Проверяем рабочий день
            if current_date.weekday() not in WORK_DAYS:
                current_date += timedelta(days=1)
                continue

            # Генерируем слоты для текущего дня
            day_slots = self._generate_day_slots(
                current_date,
                busy_slots,
                slot_duration,
                WORK_START,
                WORK_END,
                SLOT_INTERVAL
            )
            available_slots.extend(day_slots)
            current_date += timedelta(days=1)

        # Ограничиваем количество слотов
        return available_slots[:50]

    def _generate_day_slots(self, date, busy_slots, slot_duration, work_start, work_end, interval):
        """Генерирует слоты для конкретного дня"""
        day_slots = []

        # Начальное время для дня
        current_time = self.timezone.localize(
            datetime.combine(date, datetime.min.time().replace(hour=work_start))
        )

        # Если это сегодня, начинаем не раньше чем через 2 часа
        now = datetime.now(self.timezone)
        if date == now.date():
            min_time = now + timedelta(hours=2)
            current_time = max(current_time, min_time.replace(minute=0, second=0, microsecond=0))

        # Конечное время для дня
        end_time = current_time.replace(hour=work_end)

        while current_time + slot_duration <= end_time:
            slot_end = current_time + slot_duration

            # Проверяем, не пересекается ли с занятыми слотами
            is_available = True
            for busy_start, busy_end in busy_slots:
                if (current_time < busy_end and slot_end > busy_start):
                    is_available = False
                    break

            if is_available:
                day_slots.append({
                    'start': current_time,
                    'end': slot_end,
                    'date_str': current_time.strftime('%d.%m.%Y'),
                    'time_str': current_time.strftime('%H:%M'),
                    'weekday': self._get_weekday_name(current_time.weekday()),
                    'display': f"{current_time.strftime('%d.%m.%Y')} ({self._get_weekday_name(current_time.weekday())}) {current_time.strftime('%H:%M')}"
                })

            # Переходим к следующему слоту
            current_time += timedelta(minutes=interval)

        return day_slots

    def _get_weekday_name(self, weekday: int) -> str:
        """Возвращает название дня недели на русском"""
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        return days[weekday]

    async def create_booking(self, start_time: datetime, end_time: datetime,
                           client_name: str, client_phone: str, procedure: str, notes: str = "") -> Optional[str]:
        """
        Создает запись в календаре (требует разрешений на запись)

        Returns:
            str: ID созданного события или None при ошибке
        """
        try:
            # Приводим время к локальному часовому поясу
            start_local = self._localize_datetime(start_time)
            end_local = self._localize_datetime(end_time)

            event = {
                'summary': f'💅 {procedure}',
                'description': f"""👤 Клиент: {client_name}
📞 Телефон: {client_phone}
🎯 Процедура: {procedure}
📝 Заметки: {notes}

✨ Запись создана через Telegram бота""",
                'start': {
                    'dateTime': start_local.isoformat(),
                    'timeZone': str(self.timezone),
                },
                'end': {
                    'dateTime': end_local.isoformat(),
                    'timeZone': str(self.timezone),
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 60},   # За час
                        {'method': 'popup', 'minutes': 10},   # За 10 минут
                    ],
                },
                'colorId': '2',  # Зеленый цвет для записей из бота
                'source': {
                    'title': 'Telegram Bot',
                    'url': 'https://t.me/CosmetologNewBot'
                }
            }

            # Создаем событие в отдельном потоке
            created_event = await asyncio.to_thread(
                self._create_event_sync,
                event
            )

            if created_event:
                event_id = created_event['id']
                logger.info(f"Создана запись в календаре: {event_id} на {start_local}")
                return event_id

            return None

        except Exception as e:
            logger.error(f"Ошибка создания записи в календаре: {e}")
            return None

    def _create_event_sync(self, event: Dict) -> Optional[Dict]:
        """Синхронное создание события для выполнения в отдельном потоке"""
        try:
            result = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event
            ).execute()
            return result
        except Exception as e:
            logger.error(f"Ошибка создания события: {e}")
            return None

    async def update_booking(self, event_id: str, start_time: datetime,
                           end_time: datetime, client_name: str,
                           client_phone: str, procedure: str) -> bool:
        """Обновляет существующую запись"""
        try:
            start_local = self._localize_datetime(start_time)
            end_local = self._localize_datetime(end_time)

            event_update = {
                'summary': f'💅 {procedure}',
                'description': f"""👤 Клиент: {client_name}
📞 Телефон: {client_phone}
🎯 Процедура: {procedure}

✨ Обновлено через Telegram бота""",
                'start': {
                    'dateTime': start_local.isoformat(),
                    'timeZone': str(self.timezone),
                },
                'end': {
                    'dateTime': end_local.isoformat(),
                    'timeZone': str(self.timezone),
                },
            }

            updated_event = await asyncio.to_thread(
                self.service.events().update,
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event_update
            )

            result = updated_event.execute()
            logger.info(f"Обновлена запись в календаре: {event_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка обновления записи: {e}")
            return False

    async def cancel_booking(self, event_id: str) -> bool:
        """Отменяет запись в календаре"""
        try:
            await asyncio.to_thread(
                self.service.events().delete,
                calendarId=self.calendar_id,
                eventId=event_id
            )

            logger.info(f"Отменена запись в календаре: {event_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка отмены записи: {e}")
            return False

    async def check_calendar_access(self) -> bool:
        """Проверяет доступ к календарю"""
        try:
            # Простой запрос для проверки доступа
            calendar_info = await asyncio.to_thread(
                self.service.calendars().get,
                calendarId=self.calendar_id
            )
            result = calendar_info.execute()
            logger.info(f"Доступ к календарю подтвержден: {result.get('summary', 'Без названия')}")
            return True

        except Exception as e:
            logger.error(f"Нет доступа к календарю: {e}")
            return False

    async def get_upcoming_events(self, hours_ahead: int = 24) -> List[Dict]:
        """Получает ближайшие события для уведомлений"""
        try:
            now = datetime.now(self.timezone)
            end_time = now + timedelta(hours=hours_ahead)

            start_utc = self._to_utc_isoformat(now)
            end_utc = self._to_utc_isoformat(end_time)

            events_result = await asyncio.to_thread(
                self.service.events().list,
                calendarId=self.calendar_id,
                timeMin=start_utc,
                timeMax=end_utc,
                singleEvents=True,
                orderBy='startTime'
            )

            events = events_result.execute().get('items', [])

            upcoming = []
            for event in events:
                try:
                    start = event['start'].get('dateTime')
                    if start:
                        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                        start_local = start_dt.astimezone(self.timezone)

                        upcoming.append({
                            'id': event['id'],
                            'summary': event.get('summary', ''),
                            'start': start_local,
                            'description': event.get('description', '')
                        })
                except Exception:
                    continue

            return upcoming

        except Exception as e:
            logger.error(f"Ошибка получения ближайших событий: {e}")
            return []