import logging
import json
import csv
import asyncio
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime
#from services.pinecone_service import PineconeService
#from services.embeddings import EmbeddingService
from data.sample_data import SAMPLE_KNOWLEDGE_BASE

logger = logging.getLogger(__name__)


class KnowledgeBaseLoader:
    """Класс для загрузки данных в базу знаний Pinecone"""

    def __init__(self, pinecone_service, embedding_service):
        self.pinecone_service = pinecone_service
        self.embedding_service = embedding_service

    async def load_sample_data(self) -> bool:
        """
        Загрузка тестовых данных в Pinecone

        Returns:
            True если загрузка успешна
        """
        try:
            logger.info("Начинаем загрузку тестовых данных...")

            vectors_to_upsert = []
            for item in SAMPLE_KNOWLEDGE_BASE:
                # Создаем эмбеддинг для текста
                embedding_text = f"Процедура: {item['title']}. Описание: {item['content']}"
                # Используем асинхронный метод получения эмбеддинга
                embedding = await self.embedding_service.get_embedding(embedding_text)
                if not embedding:
                    logger.warning(f"Не удалось создать эмбеддинг для: {item['title']}")
                    continue

                vector = {
                    "id": item["id"],
                    "values": embedding,
                    "metadata": {
                        # Сохраняем и title, и content для будущего использования
                        "title": item["title"],
                        "content": item["content"],
                        **item["metadata"] # Добавляем всю остальную метаинформацию
                    }
                }
                vectors_to_upsert.append(vector)
            if not vectors_to_upsert:
                logger.warning("Нет данных для загрузки.")
                return False

            # Загружаем в Pinecone батчами
            batch_size = 50
            for i in range(0, len(vectors_to_upsert), batch_size):
                batch = vectors_to_upsert[i:i + batch_size]
                await self.pinecone_service.upsert_vectors(batch)
                logger.info(f"Загружен батч {i//batch_size + 1}: {len(batch)} документов")

            logger.info(f"Успешно загружено {len(vectors_to_upsert)} тестовых документов.")
            return True

        except Exception as e:
            logger.exception(f"Критическая ошибка загрузки тестовых данных: {e}")
            return False

    async def load_default_knowledge_base(self) -> bool:
        """Загрузка базовой базы знаний косметолога"""
        try:
            logger.info("Начинаем загрузку базовой базы знаний...")

            vectors_to_upsert = []
            for item in self.knowledge_base:
                # Создаем текст для эмбеддинга
                embedding_text = f"{item['title']} {item['text']}"

                # Получаем эмбеддинг
                embedding = await self.embedding_service.get_embedding(embedding_text)
                if not embedding:
                    logger.warning(f"Не удалось получить эмбеддинг для: {item['title']}")
                    continue

                vector = {
                    "id": item["id"],
                    "values": embedding,
                    "metadata": {
                        **item["metadata"],
                        "title": item["title"],
                        "text": item["text"],
                        "source": item["source"],
                        "category": item["category"],
                        "doc_type": "default_knowledge",
                        "created_at": datetime.now().isoformat()
                    }
                }
                vectors_to_upsert.append(vector)

            # Загружаем батчами
            batch_size = 50
            total_uploaded = 0

            for i in range(0, len(vectors_to_upsert), batch_size):
                batch = vectors_to_upsert[i:i + batch_size]

                try:
                    await self.pinecone_service.upsert_vectors(batch)
                    total_uploaded += len(batch)
                    logger.info(f"Загружен батч {i//batch_size + 1}: {len(batch)} документов")
                except Exception as e:
                    logger.error(f"Ошибка загрузки батча {i//batch_size + 1}: {e}")
                    return False

            logger.info(f"Успешно загружено {total_uploaded} документов базы знаний")
            return True

        except Exception as e:
            logger.exception(f"Критическая ошибка загрузки базы знаний: {e}")
            return False

    async def load_from_json(self, file_path: str) -> bool:
        """Загрузка дополнительных данных из JSON файла"""
        try:
            json_path = Path(file_path)
            if not json_path.exists():
                logger.exception(f"JSON файл не найден: {file_path}")
                return False

            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            logger.info(f"Загружаем {len(data)} записей из {file_path}")

            vectors_to_upsert = []
            for i, item in enumerate(data):
                text = item.get("text", "")
                if not text.strip():
                    logger.warning(f"Пустой текст в записи {i}, пропускаем")
                    continue

                embedding = await self.embedding_service.get_embedding(text)
                if not embedding:
                    continue

                vector = {
                    "id": f"json_{i}_{hash(text) % 1000000}",
                    "values": embedding,
                    "metadata": {
                        "title": item.get("title", f"Документ {i+1}"),
                        "text": text,
                        "source": item.get("source", f"JSON: {json_path.name}"),
                        "category": item.get("category", "general"),
                        "doc_type": "json_import",
                        "created_at": datetime.now().isoformat(),
                        **item.get("metadata", {})
                    }
                }
                vectors_to_upsert.append(vector)

            if not vectors_to_upsert:
                logger.warning("Нет валидных данных для загрузки из JSON")
                return True

            # Загружаем батчами
            batch_size = 50
            for i in range(0, len(vectors_to_upsert), batch_size):
                batch = vectors_to_upsert[i:i + batch_size]
                await self.pinecone_service.upsert_vectors(batch)
                logger.info(f"Загружен JSON батч {i//batch_size + 1}: {len(batch)} документов")

            logger.info(f"Успешно загружено {len(vectors_to_upsert)} документов из JSON")
            return True

        except Exception as e:
            logger.exception(f"Ошибка загрузки из JSON: {e}")
            return False

    async def load_from_csv(self, file_path: str, text_column: str = "text",
                           title_column: str = "title", category_column: str = "category") -> bool:
        """Загрузка данных из CSV файла"""
        try:
            csv_path = Path(file_path)
            if not csv_path.exists():
                logger.exception(f"CSV файл не найден: {file_path}")
                return False

            vectors_to_upsert = []

            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                for i, row in enumerate(reader):
                    text = row.get(text_column, "").strip()
                    if not text:
                        continue

                    embedding = await self.embedding_service.get_embedding(text)
                    if not embedding:
                        continue

                    vector = {
                        "id": f"csv_{i}_{hash(text) % 1000000}",
                        "values": embedding,
                        "metadata": {
                            "title": row.get(title_column, f"CSV документ {i+1}"),
                            "text": text,
                            "source": f"CSV: {csv_path.name}",
                            "category": row.get(category_column, "general"),
                            "doc_type": "csv_import",
                            "created_at": datetime.now().isoformat()
                        }
                    }
                    vectors_to_upsert.append(vector)

            if not vectors_to_upsert:
                logger.warning("Нет валидных данных в CSV файле")
                return True

            # Загружаем батчами
            batch_size = 100
            for i in range(0, len(vectors_to_upsert), batch_size):
                batch = vectors_to_upsert[i:i + batch_size]
                await self.pinecone_service.upsert_vectors(batch)
                logger.info(f"Загружен CSV батч {i//batch_size + 1}: {len(batch)} документов")

            logger.info(f"Успешно загружено {len(vectors_to_upsert)} документов из CSV")
            return True

        except Exception as e:
            logger.exception(f"Ошибка загрузки из CSV: {e}")
            return False

    async def load_from_text_files(self, directory_path: str) -> bool:
        """Загрузка из текстовых файлов"""
        try:
            directory = Path(directory_path)
            if not directory.exists():
                logger.exception(f"Директория не существует: {directory_path}")
                return False

            text_files = list(directory.glob("*.txt"))
            if not text_files:
                logger.warning(f"Текстовые файлы не найдены в {directory_path}")
                return True

            vectors_to_upsert = []

            for i, file_path in enumerate(text_files):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()

                    if not content:
                        continue

                    embedding = await self.embedding_service.get_embedding(content)
                    if not embedding:
                        continue

                    vector = {
                        "id": f"txt_{i}_{hash(content) % 1000000}",
                        "values": embedding,
                        "metadata": {
                            "title": file_path.stem,
                            "text": content,
                            "source": f"Файл: {file_path.name}",
                            "category": "documents",
                            "doc_type": "text_file",
                            "created_at": datetime.now().isoformat()
                        }
                    }
                    vectors_to_upsert.append(vector)

                except Exception as file_error:
                    logger.exception(f"Ошибка чтения файла {file_path}: {file_error}")
                    continue

            if vectors_to_upsert:
                await self.pinecone_service.upsert_vectors(vectors_to_upsert)
                logger.info(f"Успешно загружено {len(vectors_to_upsert)} текстовых документов")
                return True
            else:
                logger.warning("Не найдено валидных текстовых данных")
                return True

        except Exception as e:
            logger.exception(f"Ошибка загрузки текстовых файлов: {e}")
            return False

    async def extend_knowledge_with_custom_data(self, custom_data: List[Dict]) -> bool:
        """Расширение базы знаний пользовательскими данными"""
        try:
            if not custom_data:
                logger.warning("Нет пользовательских данных для загрузки")
                return True

            vectors_to_upsert = []

            for i, item in enumerate(custom_data):
                text = item.get("text", "")
                if not text.strip():
                    continue

                embedding = await self.embedding_service.get_embedding(text)
                if not embedding:
                    continue

                vector = {
                    "id": f"custom_{i}_{hash(text) % 1000000}",
                    "values": embedding,
                    "metadata": {
                        "title": item.get("title", f"Пользовательский документ {i+1}"),
                        "text": text,
                        "source": item.get("source", "Пользовательские данные"),
                        "category": item.get("category", "custom"),
                        "doc_type": "custom_data",
                        "created_at": datetime.now().isoformat(),
                        **item.get("metadata", {})
                    }
                }
                vectors_to_upsert.append(vector)

            if vectors_to_upsert:
                await self.pinecone_service.upsert_vectors(vectors_to_upsert)
                logger.info(f"Успешно загружено {len(vectors_to_upsert)} пользовательских документов")
                return True
            else:
                logger.warning("Нет валидных пользовательских данных")
                return True

        except Exception as e:
            logger.exception(f"Ошибка загрузки пользовательских данных: {e}")
            return False

    async def load_faq_data(self) -> bool:
        """Загрузка FAQ по косметологии"""
        faq_data = [
            {
                "title": "Часто задаваемые вопросы - чистка лица",
                "text": """FAQ по чистке лица: Больно ли делать чистку? Мануальная может быть болезненной,
                ультразвуковая безболезненна. Какая лучшая чистка? Подбирается индивидуально по типу кожи.
                Забиваются ли поры быстрее после чистки? Нет, правильный домашний уход предотвращает это.
                Периодичность: нормальная кожа - раз в 4-5 месяцев, проблемная - раз в 1-3 месяца.""",
                "category": "faq",
                "metadata": {
                    "subcategory": "facial_cleansing",
                    "info_type": "frequently_asked"
                }
            },
            {
                "title": "FAQ - карбокситерапия",
                "text": """Часто задаваемые вопросы по карбокситерапии: Можно ли летом? Да, процедура безопасна круглый год.
                Как подготовиться? Следовать рекомендациям врача, ограничить прием жидкости перед процедурой.
                Сколько нужно процедур? От 3 до 20, обычно 6-10 в зависимости от проблемы.
                Безопасна ли? Да, неинвазивная методика практически без побочных эффектов.""",
                "category": "faq",
                "metadata": {
                    "subcategory": "carboxytherapy",
                    "info_type": "frequently_asked"
                }
            }
        ]

        return await self.extend_knowledge_with_custom_data(faq_data)

    def get_statistics(self) -> Dict:
        """
        Получение статистики базы знаний

        Returns:
            Словарь со статистикой
        """
        try:
            stats = self.pinecone_service.get_stats()

            return {
                "total_documents": stats.get("total_vectors", 0),
                "dimension": stats.get("dimension", 0),
                "index_fullness": stats.get("index_fullness", 0),
                "embedding_model": self.embedding_service.model.model_name if hasattr(self.embedding_service.model, 'model_name') else "Unknown"
            }

        except Exception as e:
            logger.exception(f"Ошибка получения статистики: {e}")
            return {}

    async def clear_knowledge_base(self, namespace: Optional[str] = None) -> bool:
        """Очищает все векторы в индексе или в указанном пространстве имен (namespace)."""
        try:
            logger.warning(f"Начинается полная очистка векторов из индекса '{self.pinecone_service.index_name}'...")
            # Выполняем блокирующий вызов в отдельном потоке
            await asyncio.to_thread(
                self.pinecone_service.index.delete,
                delete_all=True,
                namespace=namespace # Если используете пространства имен
            )
            logger.info("База знаний успешно очищена.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при очистке базы знаний: {e}", exc_info=True)
            return False