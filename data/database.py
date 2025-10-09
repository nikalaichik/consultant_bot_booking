import aiosqlite
import asyncio
import logging
import datetime
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class Database:
    """Улучшенная база данных на SQLite с пулом соединений (connection pooling)"""

    def __init__(self, db_path: str, max_connections: int = 10):
        self.db_path = db_path
        self.max_connections = max_connections
        self._connection_pool: Optional[asyncio.Queue] = None
        self._initialization_lock = asyncio.Lock()

    async def _initialize_pool(self):
        """Ленивая инициализация пула соединений при первом запросе."""
        # Используем блокировку, чтобы избежать гонки состояний при одновременной инициализации
        async with self._initialization_lock:
            if self._connection_pool is not None:
                return

            logger.info(f"Инициализация пула соединений к БД ({self.max_connections} соединений)...")
            self._connection_pool = asyncio.Queue(maxsize=self.max_connections)

            try:
                for _ in range(self.max_connections):
                    # `check_same_thread=False` важно для некоторых асинхронных сред
                    conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
                    conn.row_factory = aiosqlite.Row # Устанавливаем row_factory для удобства

                    # Включаем WAL режим для лучшей производительности (кроме :memory:)
                    if self.db_path != ":memory:":
                        await conn.execute("PRAGMA journal_mode=WAL")
                        await conn.execute("PRAGMA busy_timeout = 5000") # Ждать 5с при блокировке
                        await conn.execute("PRAGMA synchronous=NORMAL")

                    await self._connection_pool.put(conn)

                logger.info("Пул соединений успешно инициализирован.")
            except Exception as e:
                logger.critical(f"Не удалось инициализировать пул соединений: {e}", exc_info=True)
                # Сбрасываем пул, чтобы следующая попытка могла его пересоздать
                self._connection_pool = None
                raise

    @asynccontextmanager
    async def get_connection(self):
        """Контекстный менеджер для безопасного получения соединения из пула."""
        if self._connection_pool is None:
            await self._initialize_pool()

        conn = await self._connection_pool.get()
        try:
            yield conn
        finally:
            # Возвращаем соединение в пул после использования
            await self._connection_pool.put(conn)

    async def close_pool(self):
        """Закрывает все соединения в пуле. Вызывать при остановке приложения."""
        async with self._initialization_lock:
            if self._connection_pool:
                logger.info("Закрытие пула соединений БД...")
                while not self._connection_pool.empty():
                    conn = await self._connection_pool.get()
                    await conn.close()
                self._connection_pool = None
                logger.info("Пул соединений успешно закрыт.")

    async def init_tables(self):
        """Создает таблицы и индексы, если они не существуют."""

        async with self.get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    skin_type TEXT,
                    age_group TEXT,
                    phone TEXT,
                    email TEXT,
                    vip_status INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    response TEXT,
                    intent TEXT,
                    search_results_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    procedure TEXT NOT NULL,
                    contact_info TEXT,
                    preferred_time TEXT,
                    status TEXT DEFAULT 'pending' NOT NULL
                        CHECK (status IN ('pending', 'confirmed', 'cancelled')),
                    notes TEXT,
                    calendar_event_id TEXT,
                    calendar_slot TEXT,
                    created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')) NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY,
                    conversation_id INTEGER,
                    user_id INTEGER NOT NULL,
                    rating INTEGER,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id),
                    FOREIGN KEY (conversation_id) REFERENCES conversations (id)
                )
            """)

            #ТАБЛИЦА ДЛЯ НАПОМИНАНИЙ
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    booking_id INTEGER,
                    reminder_type TEXT NOT NULL,
                    scheduled_time TIMESTAMP NOT NULL,
                    message_text TEXT NOT NULL,
                    status TEXT DEFAULT 'pending' NOT NULL,
                    attempts INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    sent_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id),
                    FOREIGN KEY (booking_id) REFERENCES bookings (id)
                )
            """)

            # Индексы для ускорения поиска
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status)")

            # НОВЫЕ ИНДЕКСЫ
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_scheduled_time ON reminders(scheduled_time)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_booking ON reminders(user_id, booking_id)")


            await conn.commit()
            logger.info("Таблицы и индексы БД успешно инициализированы.")

    # --- МЕТОДЫ ДЛЯ РАБОТЫ С ДАННЫМИ ---

    async def get_or_create_user(self, telegram_id: int, user_data: Dict) -> Dict:
        """
        Получает или создает пользователя одним атомарным запросом (UPSERT).
        Возвращает данные пользователя в виде словаря.
        """
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    updated_at=CURRENT_TIMESTAMP;
            """, (
                telegram_id,
                user_data.get('username'),
                user_data.get('first_name'),
                user_data.get('last_name')
            ))
            await conn.commit()

            # Получаем актуальные данные пользователя после операции
            user = await self.get_user_by_telegram_id(telegram_id, conn)
            return user

    async def update_user_profile(self, telegram_id: int, profile_data: Dict):
        """Обновляет профиль пользователя."""
        async with self.get_connection() as conn:
            await conn.execute("""
                UPDATE users SET
                    skin_type = ?, age_group = ?, phone = ?, email = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            """, (
                profile_data.get('skin_type'),
                profile_data.get('age_group'),
                profile_data.get('phone'),
                profile_data.get('email'),
                telegram_id
            ))
            await conn.commit()

    async def get_user_by_telegram_id(self, telegram_id: int, conn: Optional[aiosqlite.Connection] = None) -> Optional[Dict]:
        """
        Получает пользователя по Telegram ID.
        Может использовать существующее соединение для транзакций.
        """
        if conn:
            cursor = await conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
        else:
            async with self.get_connection() as new_conn:
                cursor = await new_conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def save_conversation(self, user_id: int, message: str, response: str, intent: str, search_results_count: int) -> int:
        """Сохраняет диалог."""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                INSERT INTO conversations (user_id, message, response, intent, search_results_count)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, message, response, intent, search_results_count))
            await conn.commit()
            return cursor.lastrowid

    async def create_booking(self, user_id: int, booking_data: Dict) -> int:
        """Создает запись на процедуру."""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                INSERT INTO bookings (user_id, procedure, contact_info, preferred_time, notes, status, calendar_event_id, calendar_slot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                booking_data.get('procedure'),
                booking_data.get('contact_info'),
                booking_data.get('preferred_time'),
                booking_data.get('notes'),
                booking_data.get('status', 'pending'), # Статус по умолчанию 'pending'
                booking_data.get('calendar_event_id'),
                booking_data.get('calendar_slot')
            ))
            await conn.commit()
            return cursor.lastrowid

    async def get_pending_bookings(self) -> List[Dict]:
        """Получает ожидающие записи для администратора"""
        async with self.get_connection() as db:
            cursor = await db.execute("""
                SELECT b.*, u.username, u.first_name, u.last_name
                FROM bookings b
                JOIN users u ON b.user_id = u.telegram_id
                WHERE b.status = 'pending'
                ORDER BY b.created_at DESC
            """)

            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

    # ОБРАТНАЯ СВЯЗЬ
    async def save_feedback(self, user_id: int, conversation_id: int, rating: int, comment: Optional[str] = None):
        """Сохраняет обратную связь от пользователя."""
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT INTO feedback (user_id, conversation_id, rating, comment)
                VALUES (?, ?, ?, ?)
            """, (user_id, conversation_id, rating, comment))
            await conn.commit()
            logger.info(f"Сохранена обратная связь от пользователя {user_id} с оценкой {rating}.")

    async def get_analytics_data(self, days: int = 30) -> Dict:
        """
        Собирает и возвращает аналитические данные за указанный период.
        """
        async with self.get_connection() as conn:
            stats = {}

            # --- Новые пользователи ---
            users_cursor = await conn.execute(
                "SELECT COUNT(id) FROM users WHERE created_at >= date('now', '-' || ? || ' days')",
                (days,)
            )
            new_users_count = await users_cursor.fetchone()
            stats['new_users'] = new_users_count[0] if new_users_count else 0
            await users_cursor.close()

            # --- Количество диалогов ---
            conv_cursor = await conn.execute(
                "SELECT COUNT(id) FROM conversations WHERE created_at >= date('now', '-' || ? || ' days')",
                (days,)
            )
            conversations_count = await conv_cursor.fetchone()
            stats['total_conversations'] = conversations_count[0] if conversations_count else 0
            await conv_cursor.close()

            # --- Среднее количество найденных результатов ---
            avg_res_cursor = await conn.execute(
                "SELECT AVG(search_results_count) FROM conversations WHERE created_at >= date('now', '-' || ? || ' days')",
                (days,)
            )
            avg_results = await avg_res_cursor.fetchone()
            # Округляем до 2 знаков после запятой, обрабатываем случай, если нет данных (None)
            stats['avg_search_results'] = round(avg_results[0], 2) if avg_results and avg_results[0] is not None else 0
            await avg_res_cursor.close()

            # --- Популярные намерения (интенты) ---
            intents_cursor = await conn.execute("""
                SELECT intent, COUNT(id) as count
                FROM conversations
                WHERE created_at >= date('now', '-' || ? || ' days') AND intent IS NOT NULL
                GROUP BY intent
                ORDER BY count DESC
                LIMIT 5
            """, (days,))
            popular_intents_rows = await intents_cursor.fetchall()
            # Преобразуем в более удобный формат [ {'intent': 'consultation', 'count': 120}, ... ]
            stats['popular_intents'] = [dict(row) for row in popular_intents_rows]
            await intents_cursor.close()

            logger.info(f"Собрана аналитика за последние {days} дней.")
            return stats

    async def get_user_conversations(self, user_id: int, limit: int = 10) -> List[Dict]:
     """Получает историю диалогов пользователя."""
     async with self.get_connection() as conn:
         cursor = await conn.execute(
             "SELECT * FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
             (user_id, limit)
         )
         rows = await cursor.fetchall()
         return [dict(row) for row in rows]

    # MЕТОДЫ ДЛЯ РАБОТЫ С НАПОМИНАНИЯМИ

    async def create_reminder(self, user_id: int, booking_id: int, reminder_type: str,
                            scheduled_time: datetime, message_text: str) -> int:
        """Создает напоминание"""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                INSERT INTO reminders (user_id, booking_id, reminder_type, scheduled_time, message_text)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, booking_id, reminder_type, scheduled_time, message_text))
            await conn.commit()
            return cursor.lastrowid

    async def get_pending_reminders(self, limit: int = 50) -> List[Dict]:
        """Получает напоминания, готовые к отправке"""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT r.*, u.username, u.first_name, b.procedure, b.preferred_time
                FROM reminders r
                JOIN users u ON r.user_id = u.telegram_id
                LEFT JOIN bookings b ON r.booking_id = b.id
                WHERE r.status = 'pending'
                AND r.scheduled_time <= datetime('now')
                AND r.attempts < 3
                ORDER BY r.scheduled_time ASC
                LIMIT ?
            """, (limit,))

            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def mark_reminder_sent(self, reminder_id: int):
        """Отмечает напоминание как отправленное"""
        async with self.get_connection() as conn:
            await conn.execute("""
                UPDATE reminders
                SET status = 'sent', sent_at = datetime('now')
                WHERE id = ?
            """, (reminder_id,))
            await conn.commit()

    async def mark_reminder_failed(self, reminder_id: int):
        """Отмечает неудачную попытку отправки"""
        async with self.get_connection() as conn:
            await conn.execute("""
                UPDATE reminders
                SET attempts = attempts + 1,
                    status = CASE WHEN attempts >= 2 THEN 'failed' ELSE 'pending' END
                WHERE id = ?
            """, (reminder_id,))
            await conn.commit()

    async def get_user_reminders(self, user_id: int) -> List[Dict]:
        """Получает все напоминания пользователя"""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT r.*, b.procedure, b.preferred_time
                FROM reminders r
                LEFT JOIN bookings b ON r.booking_id = b.id
                WHERE r.user_id = ?
                ORDER BY r.scheduled_time DESC
            """, (user_id,))

            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_reminders_by_event_id(self, calendar_event_id: str):
        """Удаляет все напоминания, связанные с ID события в Google Calendar."""
        async with self.get_connection() as conn:
            # Находим локальный ID записи по ID из календаря
            logger.info(f"--- НАЧАЛО УДАЛЕНИЯ НАПОМИНАНИЙ для event_id: {calendar_event_id} ---")
            cursor = await conn.execute(
                "SELECT id FROM bookings WHERE calendar_event_id = ?",
                (calendar_event_id,)
            )
            booking_row = await cursor.fetchone()

            if booking_row:
                local_booking_id = booking_row['id']
                logger.info(f"Найден локальный booking_id: {local_booking_id}. Выполняю DELETE...")
                # Сначала посмотрим, сколько строк будет затронуто
                select_cursor = await conn.execute(
                "SELECT COUNT(*) FROM reminders WHERE booking_id = ?", (local_booking_id,)
            )
                count_to_delete = await select_cursor.fetchone()
                logger.info(f"Найдено {count_to_delete[0] if count_to_delete else 0} напоминаний для удаления с booking_id = {local_booking_id}.")

                # Удаляем все напоминания, связанные с этим локальным ID
                delete_cursor = await conn.execute(
                    "DELETE FROM reminders WHERE booking_id = ?",
                    (local_booking_id,)
                )
                await conn.commit()
                # Проверяем, сколько строк было реально удалено
                logger.info(f"ЗАПРОС DELETE ВЫПОЛНЕН. Затронуто строк: {delete_cursor.rowcount}")
                logger.info(f"Удалены напоминания для локальной записи #{local_booking_id} (event: {calendar_event_id})")
            else:
                logger.warning(f"Не найдена локальная запись для отмены напоминаний по event_id: {calendar_event_id}")

async def init_database(db_path: str):
    """Инициализирует базу данных"""
    db = Database(db_path)
    await db.init_tables()
    logger.info(f"База данных инициализирована: {db_path}")
    return db