import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

class SessionManager:
    """Менеджер пользовательских сессий с файловым хранением"""

    def __init__(self, sessions_dir: str):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_cache: Dict[int, Dict[str, Any]] = {}
        self.cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_task(self):
        """Запускает задачу очистки старых сессий"""
        self.cleanup_task = asyncio.create_task(self._cleanup_sessions())

    async def get_user_session(self, user_id: int) -> Dict[str, Any]:
        """Получает сессию пользователя"""
        if user_id in self.sessions_cache:
            session = self.sessions_cache[user_id]
            return session

        # Загружаем из файла
        session_file = self.sessions_dir / f"user_{user_id}.json"
        if session_file.exists():
            try:
                content = await asyncio.to_thread(session_file.read_text, encoding="utf-8")
                session = json.loads(content)
                self.sessions_cache[user_id] = session
                return session
            except Exception as e:
                logger.exception(f"Ошибка загрузки сессии {user_id}: {e}")
                try:
                    await asyncio.to_thread(session_file.unlink)
                except Exception:
                    logger.exception("Failed to delete corrupted session file %s", session_file)

        # Создаем новую сессию
        session = {"data": {}, "updated_at": datetime.now(timezone.utc).isoformat()}
        self.sessions_cache[user_id] = session
        return session

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
        try:
            await asyncio.to_thread(self._write_session_file_sync, user_id, data)
        except Exception:
            logger.exception("Sync write failed; scheduling background save task for user %s", user_id)
            task = asyncio.create_task(self._save_session_to_file(user_id, data))
            def _on_done(t: asyncio.Task):
                try:
                    _ = t.result()
                except Exception:
                    logger.exception("Background session save failed for user %s", user_id)
            task.add_done_callback(_on_done)

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

    def _write_session_file_sync(self, user_id: int, data: dict):
        session_file = self.sessions_dir / f"user_{user_id}.json"
        content = json.dumps(data, ensure_ascii=False, indent=2)
        session_file.write_text(content, encoding="utf-8")

    async def _save_session_to_file(self, user_id: int, data: dict):
        """Сохраняет сессию в файл"""
        try:
            await asyncio.to_thread(self._write_session_file_sync, user_id, data)
        except Exception:
            logger.exception("Ошибка сохранения сессии %s", user_id)

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