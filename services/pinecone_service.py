from pinecone import Pinecone
import asyncio
import json
from typing import List, Dict, Optional
import logging
from services.embeddings import EmbeddingService
from async_lru import alru_cache

logger = logging.getLogger(__name__)

class PineconeService:
    def __init__(self, config, embedding_service: EmbeddingService):
        # СОЗДАЕМ ЭКЗЕМПЛЯР КЛАССА Pinecone
        self.pc = Pinecone(api_key=config.PINECONE_API_KEY)
        # ПРОВЕРЯЕМ СУЩЕСТВОВАНИЕ ИНДЕКСА
        self.index_name = config.PINECONE_INDEX_NAME
        if self.index_name not in self.pc.list_indexes().names():
            # Если бот запускается в продакшене, он не должен пытаться создать индекс.
            # Он должен упасть с ошибкой, если индекса нет.
            # Создание индекса - это разовая операция, которую делают отдельно.
            raise NameError(
                f"Индекс '{self.index_name}' не существует в вашем проекте Pinecone. "
                "Пожалуйста, создайте его вручную в UI Pinecone или через отдельный скрипт."
            )
        # ПОДКЛЮЧАЕМСЯ К ИНДЕКСУ
        self.index = self.pc.Index(self.index_name)
        # ИНИЦИАЛИЗИРУЕМ СЕРВИС ЭМБЕДДИНГОВ
        self.embedding_service = embedding_service # Используем переданный экземпляр

        logger.info(f"Сервис Pinecone успешно подключен к индексу '{self.index_name}'.")

    @alru_cache(maxsize=128)
    async def search(self, query: str, filters_json: Optional[str] = None, top_k: int = 5, similarity_threshold: float = 0.5) -> List[Dict]:

        """
        Поиск в Pinecone с асинхронным LRU-кэшированием.
        ВАЖНО: Аргумент filters должен передаваться в виде JSON-строки для корректной работы кэша.
        """
        logger.info(f"Выполняется поиск для запроса: {query[:50]}...")
        try:
            # Преобразуем JSON-строку обратно в словарь
            filters = json.loads(filters_json) if filters_json else None

            query_embedding = await self.embedding_service.get_embedding(query)
            if not query_embedding:
                return []

            # Выполняем блокирующий вызов в отдельном потоке
            results = await asyncio.to_thread(
                self.index.query,
                vector=query_embedding,
                filter=filters,
                top_k=top_k,
                include_metadata=True
            )

            processed_results = [
                {
                    "id": match.id,
                    "score": match.score,
                    "metadata": match.metadata
                }
                for match in results.matches
                if match.score > similarity_threshold
            ]

            logger.info(f"Найдено {len(processed_results)} релевантных результатов для: {query[:50]}...")
            return processed_results

        except json.JSONDecodeError:
            logger.error(f"Ошибка декодирования JSON в фильтрах: {filters_json}")
            return []
        except Exception as e:
            logger.error(f"Ошибка поиска в Pinecone: {e}", exc_info=True)
            return []

    async def upsert_vectors(self, vectors: List[Dict]):
        """
        Асинхронная загрузка векторов в Pinecone батчами.
        """
        try:
            batch_size = 100
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i:i + batch_size]
                # Выполняем блокирующий вызов в отдельном потоке
                await asyncio.to_thread(self.index.upsert, vectors=batch)
                logger.debug(f"Загружен батч {i//batch_size + 1}, размер: {len(batch)}")
        except Exception as e:
            logger.exception(f"Ошибка при загрузке векторов в Pinecone: {e}", exc_info=True)
            raise

    async def get_stats(self) -> Dict[str, int]:
        """
        Асинхронно получает статистику индекса.
        """
        try:
            # describe_index_stats - это блокирующий вызов, выполняем его в потоке
            stats = await asyncio.to_thread(self.index.describe_index_stats)

            # Новая версия возвращает объект, преобразуем его в словарь
            stats_dict = stats.to_dict()

            return {
                "total_vectors": stats_dict.get("total_vector_count", 0),
                "dimension": stats_dict.get("dimension", 0),
            }
        except Exception as e:
            logger.exception(f"Ошибка получения статистики Pinecone: {e}", exc_info=True)
            return {}