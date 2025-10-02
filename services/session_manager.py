import json
import asyncio
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

class SessionManager:
    """Менеджер пользовательских сессий с файловым хранением"""

    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.sessions_cache = {}
        self.cleanup_task = None

    async def start_cleanup_task(self):
        """Запускает задачу очистки старых сессий"""
        self.cleanup_task = asyncio.create_task(self._cleanup_sessions())

    async def get_user_session(self, user_id: int) -> Dict[str, Any]:
        """Получает сессию пользователя"""
        if user_id in self.sessions_cache:
            session = self.sessions_cache[user_id]
            if self._is_session_valid(session):
                return session["data"]

        # Загружаем из файла
        session_file = self.sessions_dir / f"user_{user_id}.json"
        if session_file.exists():
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session = json.load(f)
                if self._is_session_valid(session):
                    self.sessions_cache[user_id] = session
                    return session["data"]
            except Exception as e:
                logger.exception(f"Ошибка загрузки сессии {user_id}: {e}")

        # Создаем новую сессию
        return self._create_new_session(user_id)

    async def update_user_session(self, user_id: int, data: Dict[str, Any]):
        """Обновляет сессию пользователя"""
        session = {
            "data": data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        }

        self.sessions_cache[user_id] = session

        # Сохраняем в файл асинхронно
        asyncio.create_task(self._save_session_to_file(user_id, session))

    async def clear_user_session(self, user_id: int):
        """Очищает сессию пользователя"""
        if user_id in self.sessions_cache:
            del self.sessions_cache[user_id]

        session_file = self.sessions_dir / f"user_{user_id}.json"
        if session_file.exists():
            session_file.unlink()

    def _create_new_session(self, user_id: int) -> Dict[str, Any]:
        """Создает новую пустую сессию"""
        data = {
            "user_id": user_id,
            "conversation_history": [],
            "user_profile": {},
            "current_context": {},
            "preferences": {}
        }

        session = {
            "data": data,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        }

        self.sessions_cache[user_id] = session
        asyncio.create_task(self._save_session_to_file(user_id, session))

        return data

    def _is_session_valid(self, session: Dict) -> bool:
        """Проверяет валидность сессии"""
        try:
            expires_at = datetime.fromisoformat(session["expires_at"])
            return datetime.now(timezone.utc) < expires_at
        except:
            return False

    async def _save_session_to_file(self, user_id: int, session: Dict):
        """Сохраняет сессию в файл"""
        session_file = self.sessions_dir / f"user_{user_id}.json"
        try:
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception(f"Ошибка сохранения сессии {user_id}: {e}")

    async def _cleanup_sessions(self):
        """Периодическая очистка устаревших сессий"""
        while True:
            try:
                # Очищаем кэш
                expired_users = []
                for user_id, session in self.sessions_cache.items():
                    if not self._is_session_valid(session):
                        expired_users.append(user_id)

                for user_id in expired_users:
                    del self.sessions_cache[user_id]

                # Очищаем файлы
                for session_file in self.sessions_dir.glob("user_*.json"):
                    try:
                        with open(session_file, 'r', encoding='utf-8') as f:
                            session = json.load(f)
                        if not self._is_session_valid(session):
                            session_file.unlink()
                    except:
                        # Если файл поврежден - удаляем
                        session_file.unlink()

                await asyncio.sleep(3600)  # Очистка каждый час

            except Exception as e:
                logger.exception(f"Ошибка очистки сессий: {e}")
                await asyncio.sleep(3600)

    async def stop_cleanup_task(self):
        if self.cleanup_task:
            self.cleanup_task.cancel()