import asyncio
import logging
import time
from collections import defaultdict
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import BotCommand, BotCommandScopeDefault
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from services.storage import SimpleFileStorage
from aiogram.types import TelegramObject, Message
from typing import Callable, Dict, Any, Awaitable
from config import Config
from data.database import Database
from data.loader import KnowledgeBaseLoader
from services.session_manager import SessionManager
from services.bot_logic import SimpleBotLogic
from bot.handlers import start, fsm_consultation, fsm_booking, info_queries, admin, fallback

# Настройка логирования
def setup_logging(config: Config):

    log_file = config.LOGS_DIR / "bot.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

async def set_bot_commands(bot: Bot):
    """
    Устанавливает команды, которые будут видны в меню команд Telegram.
    """
    commands = [
        BotCommand(command="start", description="🔄 Перезапустить бота"),
        BotCommand(command="menu", description="🏠 Главное меню"),
        # Можете добавить и другие команды, например:
        # BotCommand(command="help", description="❓ Помощь"),
        # BotCommand(command="contacts", description="📞 Контакты")
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())

class DependenciesMiddleware(BaseMiddleware):
    def __init__(self, bot_logic: SimpleBotLogic, database: Database):
        self.bot_logic = bot_logic
        self.database = database

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Прокидываем bot_logic и database в каждый хендлер
        data["bot_logic"] = self.bot_logic
        data["database"] = self.database
        return await handler(event, data)

#Защита от спама и DDOS-атак
class RateLimiterMiddleware(BaseMiddleware):
    def __init__(self, max_messages: int = 5, window_seconds: int = 60):
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self.user_counts = defaultdict(list)

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            user_id = event.from_user.id
            now = time.time()
            # Очистка старых сообщений
            self.user_counts[user_id] = [
                t for t in self.user_counts[user_id] if now - t < self.window_seconds
            ]
            if len(self.user_counts[user_id]) >= self.max_messages:
                await event.answer("⏳ Пожалуйста, подождите немного перед следующим сообщением.")
                return
            self.user_counts[user_id].append(now)
        return await handler(event, data)

async def check_and_prepare_knowledge_base(bot_logic: SimpleBotLogic):
    """
    Проверяет, пуста ли база знаний, и если да, загружает в нее данные.
    """
    logger = logging.getLogger(__name__)
    logger.info("Проверка состояния базы знаний Pinecone...")

    try:
        stats = await bot_logic.pinecone_service.get_stats()
        vector_count = stats.get("total_vectors", 0)

        if vector_count == 0:
            logger.warning("База знаний пуста! Запускаем загрузку данных из sample_data...")

            # Создаем экземпляр загрузчика, передавая ему уже созданные сервисы
            loader = KnowledgeBaseLoader(
                pinecone_service=bot_logic.pinecone_service,
                embedding_service=bot_logic.embedding_service
            )

            # Запускаем загрузку
            success = await loader.load_sample_data()

            if success:
                logger.info("База знаний успешно заполнена тестовыми данными.")
                # Даем Pinecone время на индексацию
                await asyncio.sleep(5)
            else:
                logger.error("Не удалось загрузить тестовые данные в базу знаний!")
                # В реальном проекте здесь можно остановить бота, если БЗ критична
        else:
            logger.info(f"База знаний уже содержит {vector_count} векторов. Загрузка не требуется.")

    except Exception as e:
        logger.error(f"Ошибка при проверке или заполнении базы знаний: {e}", exc_info=True)

async def main():
    config = Config()
    # Проверяем, что все ключи из .env загрузились, прежде чем что-то делать
    if not all([config.BOT_TOKEN, config.OPENAI_API_KEY, config.PINECONE_API_KEY]):
        raise ValueError(
            "Один или несколько обязательных ключей API не найдены в .env файле. "
            "Пожалуйста, проверьте наличие BOT_TOKEN, OPENAI_API_KEY и PINECONE_API_KEY."
        )


    setup_logging(config)
    logger = logging.getLogger(__name__)

    # Инициализация базы данных
    database = Database(config.DATABASE_PATH)

    # Вызываем init_tables один раз при старте
    await database.init_tables()

    # Инициализация менеджера сессий (файловый)
    session_manager = SessionManager(config.SESSIONS_DIR)
    bot_logic = SimpleBotLogic(config, session_manager, database)

    await check_and_prepare_knowledge_base(bot_logic)

    # Инициализация бота с файловым хранилищем
    storage = SimpleFileStorage(storage_dir=config.SESSIONS_DIR / "fsm_states")
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=storage)

    await set_bot_commands(bot)

    await bot_logic.init_reminder_service(bot)

    # Регистрация хендлеров
    # 1. Административные команды
    dp.include_router(admin.router)

    # 2. Основные команды и кнопки главного меню
    dp.include_router(start.router)
    #dp.include_router(reminders.router)
    # 3. Сценарии FSM (консультация и запись)
    dp.include_router(fsm_consultation.router)
    dp.include_router(fsm_booking.router)

    # 4. Обработчики колбэков с информацией
    dp.include_router(info_queries.router)

    # 5. В САМОМ КОНЦЕ - обработчик свободных текстовых сообщений
    dp.include_router(fallback.router)

    # Регистрируем Middleware
    dp.update.middleware(DependenciesMiddleware(bot_logic=bot_logic, database=database))
    dp.update.middleware(RateLimiterMiddleware())

    # Запуск бота
    logger.info("🚀 Запуск бота...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}", exc_info=True)
    finally:
        logger.info("🛑 Остановка бота...")
        # Останавливаем сервис напоминаний
        await bot_logic.shutdown()
        await database.close_pool() # <-- Гарантированно закрываем соединение
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())