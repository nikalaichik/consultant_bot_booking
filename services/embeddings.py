import logging
import asyncio
from typing import List, Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """Получает embedding для текста"""
        try:
            response = await self.client.embeddings.create(
                input=text.strip(),
                model=self.model
            )
            return response.data[0].embedding
        except Exception as e:
            logger.exception(f"Ошибка получения embedding: {e}")
            return None

    async def get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Получает embeddings для списка текстов"""
        tasks = [self.get_embedding(text) for text in texts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, list)]

        #return await asyncio.gather(*tasks, return_exceptions=True)