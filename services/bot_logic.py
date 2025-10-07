import logging
import asyncio
import re
import json
from datetime import datetime, timezone
from services.pinecone_service import PineconeService
from services.openai_service import OpenAIService
from services.embeddings import EmbeddingService
from utils.security import sanitize_for_model
from services.google_calendar_service import GoogleCalendarService

logger = logging.getLogger(__name__)

INTENT_KEYWORDS = {
            "pricing": ["цена", "стоимость", "прайс", "тариф", "расценка", "оплата", "сколько стоит", "прайслист",
                        "сколько обойдется", "сколько стоит", "цена", "стоимость", "прайс", "прайслист",
                        "сколько будет стоить", "во сколько обойдется", "дорого ли", "цены на",
                        "стоимость процедур", "сколько за", "цену на"],
            "booking": ["запись", "записаться", "назначить", "расписание", "прием", "окно", "время", "хочу прийти", "хочу на приём",
                        "хочу записаться", "хочу на прием", "можно записаться", "когда можно прийти", "есть время",
                        "свободное время", "расписание", "график работы", "хочу попасть", "нужно попасть",
                        "записать меня"],
            "emergency": ["кровь", "болит", "температура", "аллергия", "болеть", "боль", "покраснение", "сыпь",
                        "шишка", "тошнить", "кровь", "кровотечение", "отек", "отёк", "опухло", "воспаление",
                        "воспалилось", "жжение", "плохо себя чувствую", "уплотнение", "гной", "нагноение"]
        }
# Регулярные выражения для сложных паттернов
INTENT_PATTERNS = {
    "aftercare": [
        r"\bпосле\s+(?:процедур|чистк|пилинг|мезо|инъекц|ботокс|филлер)",
        r"\bуход\s+после\b",
        r"\bчто\s+(?:можно|нельзя|делать)\s+после\b",
        r"\bпосле\s+(?:сеанса|визита)\s+что\b",
        r"\bреабилитация\s+после\b",
        r"\bограничения\s+после\b",
        r"\bвосстановление\s+после\b",
        r"\bпосле\s+лазер",
        r"\bпосле\s+шлифовк"
    ],
    "consultation": [
        r"\bкакая\s+процедура\s+(?:лучше|подойдет|нужна)\b",
        r"\bчто\s+делать\s+с\s+(?:кожей|лицом|морщинами)\b",
        r"\bкак\s+избавиться\s+от\b",
        r"\bчто\s+посоветуете\b",
        r"\bкакой\s+уход\b"
    ]
}

# Исключения - фразы, которые НЕ должны попадать в определенные категории
INTENT_EXCLUSIONS = {
    "pricing": [
        "не важна цена",  # Клиент говорит, что цена не важна
        "цена не важна"
    ],
    "emergency": [
        "не болит",  # Отрицание
        "больше не болит"
    ]
}

class IntentClassifier:
    """Классификатор намерений пользователя"""

    def __init__(self):
        # Компилируем регулярные выражения для производительности
        self.compiled_patterns = {
            intent: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for intent, patterns in INTENT_PATTERNS.items()
        }

    @staticmethod
    def normalize_message(message) -> str:
        """Приводит любое входное сообщение к строке и нормализует"""
        if isinstance(message, list):
            text = " ".join(str(x) for x in message)
        else:
            text = str(message)

        # Базовая нормализация
        text = text.lower().strip()
        # Убираем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        # Нормализуем ё -> е для лучшего поиска
        text = text.replace('ё', 'е')

        return text

    def classify_by_keywords_and_patterns(self, message: str) -> str:
        """Классификация по ключевым словам и паттернам"""
        text = self.normalize_message(message)

        if not text:
            return "general"

        # 1. Проверяем исключения
        for intent, exclusions in INTENT_EXCLUSIONS.items():
            if any(exclusion in text for exclusion in exclusions):
                logger.debug(f"Найдено исключение для {intent}: {text}")
                # Если нашли исключение, не классифицируем как этот intent
                continue

        # 2. Проверяем emergency в первую очередь (приоритет безопасности)
        if self._check_intent_keywords(text, "emergency"):
            return "emergency"

        # 3. Проверяем остальные ключевые слова
        for intent in ["booking", "pricing"]:
            if self._check_intent_keywords(text, intent):
                return intent

        # 4. Проверяем паттерны
        for intent, compiled_patterns in self.compiled_patterns.items():
            if any(pattern.search(text) for pattern in compiled_patterns):
                logger.debug(f"Найден паттерн для {intent}: {text}")
                return intent

        # 5. Если ничего не найдено - консультация
        return "consultation"

    def _check_intent_keywords(self, text: str, intent: str) -> bool:
        """Проверяет ключевые слова для конкретного намерения"""
        keywords = INTENT_KEYWORDS.get(intent, [])

        # Сначала ищем исключения
        exclusions = INTENT_EXCLUSIONS.get(intent, [])
        if any(exclusion in text for exclusion in exclusions):
            return False

        # Затем ищем совпадения
        return any(keyword in text for keyword in keywords)

    def get_confidence_score(self, message: str, intent: str) -> float:
        """Возвращает оценку уверенности в классификации (0.0 - 1.0)"""
        text = self.normalize_message(message)

        if not text:
            return 0.0

        # Базовые очки за совпадения
        score = 0.0

        # Проверяем ключевые слова (каждое совпадение = +0.5)
        keywords = INTENT_KEYWORDS.get(intent, [])
        for keyword in keywords:
            if keyword in text:
                score += 0.5
                # Бонус за точное совпадение целого слова
                if f" {keyword} " in f" {text} ":
                    score += 0.2

        # Проверяем паттерны (каждый паттерн = +0.6)
        patterns = self.compiled_patterns.get(intent, [])
        for pattern in patterns:
            if pattern.search(text):
                score += 0.6

        # Нормализуем к диапазону 0.0-1.0
        return min(score, 1.0)

class SimpleBotLogic:
    """Упрощенная логика бота для VPS"""

    def __init__(self, config, session_manager, database, calendar_service: GoogleCalendarService):
        self.config = config
        self.session_manager = session_manager
        self.database = database
        self.calendar_service = calendar_service
        self.intent_classifier = IntentClassifier()
        # Сначала создаем сервис эмбеддингов
        self.embedding_service = EmbeddingService(
            api_key=config.OPENAI_API_KEY,
            model=config.EMBEDDING_MODEL
        )
        # Затем передаем его в PineconeService
        self.pinecone_service = PineconeService(
            config=config,
            embedding_service=self.embedding_service
        )
        self.openai_service = OpenAIService(config.OPENAI_API_KEY, config.OPENAI_MODEL, config.OPENAI_MODEL_MINI, config=config)
        self.reminder_service = None

    async def get_info_from_kb(self, query: str, user_profile: dict = None) -> str:
        """
        "Легкий" метод: только поиск в Pinecone и генерация ответа OpenAI.
        Не сохраняет историю, не работает с сессиями.
        """
        try:
            # 1. Поиск в Pinecone (фильтры можно добавить по аналогии, если нужно)
            search_results = await self.pinecone_service.search(
                query=query,
                top_k=2 # Достаточно 1-2 документов для краткой справки
            )

            # 2. Формирование контекста
            if not search_results:
                context = "Информация в базе знаний не найдена."
            else:
                context = "\n\n".join([
                    f"{res['metadata']['title']}\n{res['metadata']['content']}"
                    for res in search_results
                ])

            # 3. Генерация ответа (всегда используем 'consultation' intent для таких запросов)
            response = await self.openai_service.generate_response(
                user_message=query,
                context=context,
                intent="consultation",
                user_profile=user_profile,
                use_mini=True # Используем быструю модель для справок
            )
            return response
        except Exception as e:
            logger.error(f"Ошибка в get_info_from_kb: {e}")
            return "К сожалению, не удалось загрузить информацию о процедуре."

    async def classify_intent(self, message: str) -> str:
        """Гибридная классификация намерений"""

        # Сначала пробуем быструю классификацию
        keyword_intent = self.intent_classifier.classify_by_keywords_and_patterns(message)

        # Получаем оценку уверенности
        confidence = self.intent_classifier.get_confidence_score(message, keyword_intent)

        # Адаптивный порог уверенности в зависимости от типа намерения
        thresholds = {
            "emergency": 0.3,    # Низкий порог для безопасности
            "booking": 0.4,      # Средний порог
            "pricing": 0.4,      # Средний порог
            "aftercare": 0.5,    # Выше, т.к. паттерны точнее
            "consultation": 0.0  # Всегда принимаем
        }
        threshold = thresholds.get(keyword_intent, 0.5)

        # Если уверенность достаточная или это emergency - возвращаем результат
        if confidence >= threshold:
            logger.debug(f"Классификация по ключевым словам: {keyword_intent} (уверенность: {confidence:.2f})")
            return keyword_intent

        # Если уверенность низкая - используем GPT
        logger.debug(f"Низкая уверенность ({confidence:.2f} < {threshold}), используем GPT для: {message}")
        return await self.openai_service.classify_intent(message)

    def generate_search_filters(self, message: str, user_session: dict) -> dict:
        """Генерирует фильтры для поиска"""
        filters = {}
        message_lower = message.lower()

        # Из профиля пользователя
        user_profile = user_session.get("user_profile", {})
        if user_profile.get("skin_type"):
            filters["skin_types"] = {"$in": [user_profile["skin_type"], "all"]}

        if user_profile.get("age_group"):
            filters["age_groups"] = {"$in": [user_profile["age_group"]]}

        # Из сообщения
        skin_mapping = {
            "жирная": "oily", "сухая": "dry", "нормальная": "normal",
            "чувствительная": "sensitive", "проблемная": "problematic"
        }

        for skin_ru, skin_en in skin_mapping.items():
            if skin_ru in message_lower:
                filters["skin_types"] = {"$in": [skin_en, "all"]}
                break

        return filters

    async def process_message(self, user_id: int, message: str) -> tuple[str, dict]:
        """Основная обработка сообщения"""
        start_time = asyncio.get_event_loop().time()
        try:
            # очищаем перед использованием
            clean_message = sanitize_for_model(message)
            # Получаем сессию пользователя
            user_session = await self.session_manager.get_user_session(user_id)

            cached_intent = user_session.get("last_intent")
            cached_query = user_session.get("last_query")

            if cached_intent and cached_query == message and (datetime.now(timezone.utc) - datetime.fromisoformat(user_session.get("intent_timestamp", ""))).total_seconds() < 300:
                intent = cached_intent
            else:
                intent = await self.classify_intent(message)
                user_session["last_intent"] = intent
                user_session["last_query"] = message
                user_session["intent_timestamp"] = datetime.now(timezone.utc).isoformat()

            # Получаем историю (последние 5 сообщений)
            history = await self.database.get_user_conversations(user_id, limit=5)

            logger.info(f"История диалога: {history}")

            # Формируем текстовую историю для GPT
            history_text = "\n".join([
                f"Пользователь: {h['message']}\nБот: {h['response']}"
                for h in reversed(history)  # от старых к новым
            ])
            # Обрезаем историю, чтобы уложиться в MAX_CONTEXT_LENGTH
            if len(history_text) > self.config.MAX_CONTEXT_LENGTH:
                history_text = history_text[-self.config.MAX_CONTEXT_LENGTH:]
                # Находим ближайшую границу сообщения
                last_newline = history_text.rfind("\n", 0, self.config.MAX_CONTEXT_LENGTH)
                if last_newline != -1:
                    history_text = history_text[last_newline + 1:]
                logger.warning(f"История диалога обрезана до {self.config.MAX_CONTEXT_LENGTH} символов")

            # Генерируем фильтры для поиска
            filters = self.generate_search_filters(message, user_session)

            # Преобразуем словарь фильтров в JSON-строку
            filters_str = json.dumps(filters) if filters else None

            # Поиск в базе знаний
            search_results = await self.pinecone_service.search(
                query=clean_message,
                filters_json=filters_str if filters else None,
                top_k=3
            )
            if not search_results:
                context = "⚠️ В базе знаний не найдено релевантной информации по вашему запросу. Пожалуйста, ответь на основе общих знаний о косметологии и услугах клиники."
            else:
                # Формируем контекст
                context = "\n".join([
        f"Документ {i+1}: {result['metadata']['title']}\n{result['metadata']['content']}"
        for i, result in enumerate(search_results)
    ])
            if history_text:
                context = f"{history_text}\n\n{context}"
            # Генерируем ответ
            use_mini = intent in ["pricing", "aftercare"]
            response = await self.openai_service.generate_response(
                user_message=message,
                context=context,
                intent=intent,
                user_profile=user_session.get("user_profile"),
                use_mini=use_mini
            )

            end_time = asyncio.get_event_loop().time()

            # Обновляем историю беседы
            conversation_history = user_session.get("conversation_history", [])
            conversation_history.append({
                "user": message,
                "assistant": response,
                "intent": intent,
                "timestamp": datetime.now().isoformat()
            })

            # Ограничиваем историю последними 10 сообщениями
            if len(conversation_history) > 10:
                conversation_history = conversation_history[-10:]

            user_session["conversation_history"] = conversation_history
            await self.session_manager.update_user_session(user_id, user_session)

            # Сохраняем в базу данных
            await self.database.save_conversation(
                user_id=user_id,
                message=message,
                response=response,
                intent=intent,
                search_results_count=len(search_results)
            )

            logger.info(f"Обработка сообщения {user_id}: intent={intent}, time={end_time-start_time:.2f}s, results={len(search_results)}")
            return response, {"intent": intent, "search_results": len(search_results)}

        except Exception as e:
            logger.exception(f"Ошибка обработки сообщения пользователя {user_id}: {e}")
            return self._get_error_response(), {"intent": "error", "error": str(e)}

    def _get_error_response(self) -> str:
        return f"""😔 Извините, произошла техническая ошибка.

📞 Для получения помощи:
Телефон: {self.config.CLINIC_PHONE}
Режим работы: {self.config.WORKING_HOURS}

Попробуйте задать вопрос позже или обратитесь по телефону."""

    async def init_reminder_service(self, bot):
        """Инициализация сервиса напоминаний"""
        from services.reminder_service import ReminderService
        self.reminder_service = ReminderService(self.database, bot)
        await self.reminder_service.start()

    async def shutdown(self):
        """Корректное завершение работы"""
        if self.reminder_service:
            await self.reminder_service.stop()