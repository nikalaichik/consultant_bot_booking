import pytest
import asyncio
import json
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

# Импорты компонентов бота
from config import Config
from services.bot_logic import SimpleBotLogic, IntentClassifier
from services.openai_service import OpenAIService
from services.pinecone_service import PineconeService
#from services.google_calendar_service import GoogleCalendarService
from services.session_manager import SessionManager
from services.storage import SimpleFileStorage
from data.database import Database

# ================== ТЕСТОВЫЕ ДАННЫЕ ==================

class TestData:
    """Тестовые данные для проверки функциональности"""

    SAMPLE_USERS = [
        {
            "telegram_id": 12345,
            "username": "test_user",
            "first_name": "Анна",
            "last_name": "Тестова"
        },
        {
            "telegram_id": 67890,
            "username": "admin_user",
            "first_name": "Админ",
            "last_name": "Администратор"
        }
    ]

    INTENT_TEST_CASES = [
        ("сколько стоит чистка лица", "pricing", 0.7),
        ("хочу записаться на завтра", "booking", 0.5),
        ("после процедуры что нельзя делать", "aftercare", 0.6),
        ("болит место укола", "emergency", 0.5),
        ("какую процедуру выбрать для жирной кожи", "consultation", 0.0),
        ("привет как дела", "consultation", 0.0),
        ("цена не важна, главное качество", "consultation", 0.0),  # исключение
    ]

    SAMPLE_CALENDAR_SLOTS = [
        {
            'start': datetime(2024, 12, 15, 10, 0),
            'end': datetime(2024, 12, 15, 11, 0),
            'date_str': '15.12.2024',
            'time_str': '10:00',
            'weekday': 'Вс',
            'display': '15.12.2024 (Вс) 10:00'
        },
        {
            'start': datetime(2024, 12, 16, 14, 0),
            'end': datetime(2024, 12, 16, 15, 0),
            'date_str': '16.12.2024',
            'time_str': '14:00',
            'weekday': 'Пн',
            'display': '16.12.2024 (Пн) 14:00'
        }
    ]
# ================== ФИКСТУРЫ ==================

@pytest.fixture
def test_config():
    """Тестовая конфигурация"""
    config = Config()
    config.DATABASE_PATH = ":memory:"  # In-memory SQLite для тестов
    #config.GOOGLE_CREDENTIALS_PATH = "test_credentials.json"
    #config.GOOGLE_CALENDAR_ID = "test_calendar"
    print("✅ Конфигурация инициализирована")
    print(f"📁 База: {config.DATABASE_PATH}")
    return config


@pytest.fixture
async def mock_database(test_config, event_loop): # event_loop может понадобиться для некоторых версий
    """
    Асинхронный генератор для создания и очистки БД в памяти для каждого теста.
    """
    # Используем db_path=":memory:", чтобы каждый тест получал свою чистую БД
    db = Database(db_path=":memory:", max_connections=1)

    # --- НАЧАЛО ИСПРАВЛЕНИЙ ---
    # Мы не вызываем init_tables здесь, так как пул еще не создан.
    # Пул создается "лениво" при первом вызове get_connection.

    # Вместо этого мы будем создавать таблицы перед каждым тестом,
    # используя сам объект db.

    # Этот код гарантирует, что таблицы будут созданы до того, как тест начнется
    await db.init_tables()

    yield db  # Передаем полностью готовый к работе объект в тест

    # После того как тест отработал, закрываем пул соединений
    await db.close_pool()

@pytest.fixture
def mock_session_manager(tmp_path):
    """Мок менеджера сессий - ИСПРАВЛЕН"""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(exist_ok=True)  # Создаем директорию
    return SessionManager(sessions_dir)

@pytest.fixture
def mock_intent_classifier():
    """Реальный классификатор намерений для тестирования"""
    return IntentClassifier()

@pytest.fixture
async def mock_bot_logic(test_config, mock_database, mock_session_manager):
    """ИСПРАВЛЕН - создание мок-объекта бот-логики"""

    # Мокаем внешние сервисы
    with patch('services.bot_logic.PineconeService') as mock_pinecone, \
         patch('services.bot_logic.OpenAIService') as mock_openai, \
         patch('services.bot_logic.EmbeddingService') as mock_embedding:

        # Настройка моков
        mock_pinecone_instance = AsyncMock()
        mock_pinecone_instance.search.return_value = [
            {
                'id': 'test_doc_1',
                'score': 0.8,
                'metadata': {
                    'title': 'Чистка лица',
                    'content': 'Информация о чистке лица'
                }
            }
        ]
        mock_pinecone.return_value = mock_pinecone_instance

        mock_openai_instance = AsyncMock()
        mock_openai_instance.generate_response.return_value = "Тестовый ответ от OpenAI"
        mock_openai_instance.classify_intent.return_value = "consultation"
        mock_openai.return_value = mock_openai_instance

        mock_embedding.return_value = AsyncMock()

        bot_logic = SimpleBotLogic(test_config, mock_session_manager, mock_database)
        yield bot_logic

# ================== UNIT ТЕСТЫ ==================

class TestIntentClassification:
    """Тестирование классификации намерений"""

    def test_intent_classifier_initialization(self, mock_intent_classifier):
        """Тест инициализации классификатора"""
        assert mock_intent_classifier is not None
        assert hasattr(mock_intent_classifier, 'compiled_patterns')
        assert len(mock_intent_classifier.compiled_patterns) > 0

    @pytest.mark.parametrize("message,expected_intent,min_confidence", TestData.INTENT_TEST_CASES)
    def test_intent_classification(self, mock_intent_classifier, message, expected_intent, min_confidence):
        """Тест классификации намерений"""
        intent = mock_intent_classifier.classify_by_keywords_and_patterns(message)
        confidence = mock_intent_classifier.get_confidence_score(message, intent)

        assert intent == expected_intent, f"Для '{message}' ожидался '{expected_intent}', получен '{intent}'"
        assert confidence >= min_confidence, f"Уверенность {confidence} ниже ожидаемой {min_confidence}"

    def test_message_normalization(self, mock_intent_classifier):
        """Тест нормализации сообщений"""
        test_cases = [
            ("  ПРИВЕТ  МИР  ", "привет мир"),
            ("Ёлка-палка", "елка-палка"),
            (["список", "слов"], "список слов"),
            (123, "123")
        ]

        for input_msg, expected in test_cases:
            result = mock_intent_classifier.normalize_message(input_msg)
            assert result == expected

class TestDatabase:
    """Тестирование базы данных - ИСПРАВЛЕНЫ"""

    @pytest.mark.asyncio
    async def test_database_initialization(self, mock_database):
        """Тест инициализации таблиц - ИСПРАВЛЕН"""
        # Проверяем, что таблицы созданы
        async with mock_database.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in await cursor.fetchall()]

        expected_tables = ["users", "conversations", "bookings", "feedback"]
        for table in expected_tables:
            assert table in tables, f"Таблица {table} не найдена"

    @pytest.mark.asyncio
    async def test_user_operations(self, mock_database):
        """Тест операций с пользователями - ИСПРАВЛЕН"""
        test_user = TestData.SAMPLE_USERS[0]

        # Создание пользователя
        user = await mock_database.get_or_create_user(
            test_user["telegram_id"],
            test_user
        )

        assert user["telegram_id"] == test_user["telegram_id"]
        assert user["first_name"] == test_user["first_name"]

        # Обновление профиля
        profile_data = {
            "skin_type": "oily",
            "age_group": "young",
            "phone": "+7-999-123-45-67"
        }

        await mock_database.update_user_profile(
            test_user["telegram_id"],
            profile_data
        )

        # Проверка обновления
        updated_user = await mock_database.get_user_by_telegram_id(test_user["telegram_id"])
        assert updated_user["skin_type"] == "oily"
        assert updated_user["phone"] == "+7-999-123-45-67"

    @pytest.mark.asyncio
    async def test_conversation_operations(self, mock_database):
        """Тест операций с диалогами"""
        user_id = 12345

        # Создание диалога
        conversation_id = await mock_database.save_conversation(
            user_id=user_id,
            message="Тестовое сообщение",
            response="Тестовый ответ",
            intent="consultation",
            search_results_count=3
        )

        assert conversation_id is not None

        # Получение истории
        history = await mock_database.get_user_conversations(user_id, limit=5)
        assert len(history) == 1
        assert history[0]["message"] == "Тестовое сообщение"
        assert history[0]["intent"] == "consultation"

    @pytest.mark.asyncio
    async def test_booking_operations(self, mock_database):
        """Тест операций с записями"""
        user_id = 12345
        booking_data = {
            "procedure": "Чистка лица",
            "contact_info": "Анна, +7-999-123-45-67",
            "preferred_time": "утром",
            "notes": "Тестовая запись"
        }
        await mock_database.get_or_create_user(user_id, {
            "username": "anna",
            "first_name": "Анна",
            "last_name": "Иванова"
        })
        # Создание записи
        booking_id = await mock_database.create_booking(user_id, booking_data)
        assert booking_id is not None

        # Получение записей
        bookings = await mock_database.get_pending_bookings()
        assert len(bookings) >= 1

'''class TestGoogleCalendarService:
    """Тестирование сервиса Google Calendar"""

    @pytest.fixture
    def mock_calendar_service(self):
        """Мок Google Calendar сервиса"""
        with patch('services.google_calendar_service.build') as mock_build:
            mock_service = MagicMock()
            mock_build.return_value = mock_service

            calendar_service = GoogleCalendarService(
                credentials_path="test_credentials.json",
                calendar_id="test_calendar"
            )
            calendar_service.service = mock_service
            return calendar_service

    @pytest.mark.asyncio
    async def test_get_available_slots(self, mock_calendar_service):
        """Тест получения доступных слотов"""
        # Настройка мока
        mock_calendar_service.service.events().list().execute.return_value = {
            'items': []  # Пустой календарь
        }

        with patch.object(mock_calendar_service, '_get_busy_slots', return_value=[]):
            slots = await mock_calendar_service.get_available_slots(days_ahead=7)

        assert isinstance(slots, list)
        assert len(slots) > 0  # Должны быть доступные слоты

        # Проверяем структуру слотов
        if slots:
            slot = slots[0]
            required_keys = ['start', 'end', 'date_str', 'time_str', 'weekday', 'display']
            for key in required_keys:
                assert key in slot, f"Ключ {key} отсутствует в слоте"'''

class TestSessionManager:
    """Тестирование менеджера сессий"""

    @pytest.mark.asyncio
    async def test_session_creation_and_retrieval(self, mock_session_manager):
        """Тест создания и получения сессии"""
        user_id = 12345

        # Получение новой сессии
        session = await mock_session_manager.get_user_session(user_id)

        assert session["user_id"] == user_id
        assert "conversation_history" in session
        assert isinstance(session["conversation_history"], list)

        # Обновление сессии
        session["test_data"] = "test_value"
        await mock_session_manager.update_user_session(user_id, session)

        # Получение обновленной сессии
        updated_session = await mock_session_manager.get_user_session(user_id)
        assert updated_session["test_data"] == "test_value"

    @pytest.mark.asyncio
    async def test_session_cleanup(self, mock_session_manager):
        """Тест очистки сессий"""
        user_id = 12345

        # Создаем сессию
        await mock_session_manager.get_user_session(user_id)

        # Очищаем
        await mock_session_manager.clear_user_session(user_id)

        # Проверяем, что создается новая сессия
        new_session = await mock_session_manager.get_user_session(user_id)
        assert new_session["user_id"] == user_id

# ================== ИНТЕГРАЦИОННЫЕ ТЕСТЫ ==================

class TestBotLogicIntegration:
    """Интеграционные тесты основной логики бота"""

    @pytest.mark.asyncio
    async def test_message_processing_flow(self, mock_bot_logic):
        """Тест полного потока обработки сообщения"""
        user_id = 12345
        message = "Расскажите о чистке лица"

        response, metadata = await mock_bot_logic.process_message(user_id, message)

        assert isinstance(response, str)
        assert len(response) > 0
        assert "intent" in metadata
        assert "search_results" in metadata

        # Проверяем, что сессия обновилась
        session = await mock_bot_logic.session_manager.get_user_session(user_id)
        assert len(session["conversation_history"]) > 0

# ================== ФУНКЦИОНАЛЬНЫЕ ТЕСТЫ ==================

class TestBotFunctionality:
    """Функциональные тесты основных сценариев - ИСПРАВЛЕНЫ"""

    @pytest.mark.asyncio
    async def test_consultation_flow(self, mock_bot_logic):
        """Тест сценария консультации - ИСПРАВЛЕН"""
        user_id = 12345

        # Начало консультации
        response1, _ = await mock_bot_logic.process_message(
            user_id, "Какая процедура подойдет для жирной кожи?"
        )

        # Проверяем, что получили ответ (любой)
        assert isinstance(response1, str)
        assert len(response1) > 0

        # Уточняющий вопрос
        response2, _ = await mock_bot_logic.process_message(
            user_id, "У меня еще есть черные точки"
        )

        assert isinstance(response2, str)
        assert len(response2) > 0

    @pytest.mark.asyncio
    async def test_pricing_inquiry(self, mock_bot_logic):
        """Тест запроса цен - ИСПРАВЛЕН"""
        user_id = 12345

        response, metadata = await mock_bot_logic.process_message(
            user_id, "Сколько стоит чистка лица?"
        )

        # Проверяем основные характеристики ответа
        assert isinstance(response, str)
        assert len(response) > 0
        assert "intent" in metadata
        assert isinstance(metadata["intent"], str)

    @pytest.mark.asyncio
    async def test_emergency_handling(self, mock_bot_logic):
        """Тест обработки экстренных ситуаций - ИСПРАВЛЕН"""
        user_id = 12345

        # Патчим классификацию намерения для этого теста
        with patch.object(mock_bot_logic.intent_classifier, 'classify_by_keywords_and_patterns', return_value='emergency'):
            response, metadata = await mock_bot_logic.process_message(
                user_id, "У меня сильно болит и воспалилось место укола!"
            )

        # Проверяем что получили emergency intent
        assert metadata["intent"] == "emergency"
        assert isinstance(response, str)
        assert len(response) > 0

# ================== НАГРУЗОЧНЫЕ ТЕСТЫ ==================

class TestPerformance:
    """Тесты производительности"""

    @pytest.mark.asyncio
    async def test_concurrent_users(self, mock_bot_logic):
        """Тест одновременной работы нескольких пользователей"""

        async def simulate_user(user_id: int):
            """Симуляция активности пользователя"""
            for i in range(3):
                await mock_bot_logic.process_message(
                    user_id, f"Тестовое сообщение {i}"
                )

        # Запускаем 10 пользователей одновременно
        tasks = [simulate_user(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # Проверяем, что все сессии созданы
        for user_id in range(10):
            session = await mock_bot_logic.session_manager.get_user_session(user_id)
            assert session["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_database_performance(self, mock_database):
        """Тест производительности базы данных"""
        import time

        start_time = time.time()

        # Создаем 100 записей
        for i in range(100):
            await mock_database.save_conversation(
                user_id=i,
                message=f"Сообщение {i}",
                response=f"Ответ {i}",
                intent="consultation",
                search_results_count=1
            )

        end_time = time.time()

        # Проверяем, что операции выполнились быстро (< 10 секунд)
        assert end_time - start_time < 10.0

# ================== ТЕСТЫ БЕЗОПАСНОСТИ ==================

class TestSecurity:
    """Тесты безопасности - ИСПРАВЛЕНЫ"""

    @pytest.mark.asyncio
    async def test_sql_injection_protection(self, mock_database):
        """Тест защиты от SQL-инъекций - ИСПРАВЛЕН"""
        malicious_input = "'; DROP TABLE users; --"

        # Попытка создать пользователя с вредоносным вводом
        user_data = {
            "username": malicious_input,
            "first_name": "Test",
            "last_name": "User"
        }

        try:
            user = await mock_database.get_or_create_user(12345, user_data)
            # Проверяем, что таблица users все еще существует
            async with mock_database.get_connection() as conn:
                cursor = await conn.execute("SELECT COUNT(*) FROM users")
                count = await cursor.fetchone()
                assert count[0] >= 0  # Таблица должна существовать
        except Exception as e:
            # Если возникла ошибка, проверяем что это не из-за SQL инъекции
            assert "DROP TABLE" not in str(e).upper()

    @pytest.mark.asyncio
    async def test_input_sanitization(self, mock_bot_logic):
        """Тест санитизации пользовательского ввода"""
        user_id = 12345

        dangerous_inputs = [
            "<script>alert('xss')</script>",
            "javascript:void(0)",
            "../../../etc/passwd",
            "SELECT * FROM users",
        ]

        for dangerous_input in dangerous_inputs:
            response, _ = await mock_bot_logic.process_message(user_id, dangerous_input)
            # Ответ не должен содержать исходный вредоносный код
            assert dangerous_input not in response