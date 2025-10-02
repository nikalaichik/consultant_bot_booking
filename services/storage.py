import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

class DateTimeEncoder(json.JSONEncoder):
    """JSON энкодер для datetime объектов"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def datetime_decoder(dct):
    """Декодер для восстановления datetime объектов"""
    for key, value in dct.items():
        if isinstance(value, str):
            # Пытаемся распарсить datetime из ISO формата
            try:
                if 'T' in value and ('+' in value or 'Z' in value or value.count(':') >= 2):
                    dct[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                pass  # Оставляем как строку
    return dct

class SimpleFileStorage(BaseStorage):
    """
    Адаптированное файловое хранилище состояний, совместимое с aiogram.fsm.storage.base.BaseStorage.
    """

    def __init__(self, storage_dir: Path, state_ttl_hours: int = 24):
        self.storage_dir = storage_dir
        self.state_ttl_hours = state_ttl_hours
        self.storage_dir.mkdir(exist_ok=True, parents=True)
        # Кэш больше не нужен, так как aiogram кэширует состояния на уровне FSMContext

        # Кэш для часто используемых состояний (опционально)
        self._cache = {}
        self._cache_max_size = 1000
        # Блокировка для thread-safe операций
        self._file_locks = {}

    def resolve_state(self, state: StateType) -> Optional[str]:
        """
        Преобразует объект состояния (или строку, или None) в строку для хранения.
        """
        if state is None:
            return None
        if isinstance(state, State):
            return state.state
        return str(state)

    def _get_file_key(self, key: StorageKey) -> str:
        """Создает уникальное имя файла из ключа aiogram."""
        return f"state_b{key.bot_id}_c{key.chat_id}_u{key.user_id}.json"

    def _get_file_path(self, key: StorageKey) -> Path:
        """Возвращает полный путь к файлу состояния"""
        return self.storage_dir / self._get_file_key(key)

    async def _get_file_lock(self, file_key: str) -> asyncio.Lock:
        """Получает блокировку для конкретного файла"""
        if file_key not in self._file_locks:
            self._file_locks[file_key] = asyncio.Lock()
        return self._file_locks[file_key]

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        """Устанавливает состояние (state)."""
        file_key = self._get_file_key(key)

        file_path = self._get_file_path(key)

        # Используем блокировку для thread-safe записи
        lock = await self._get_file_lock(file_key)
        async with lock:
            # Получаем текущие данные или создаем пустой словарь
            storage_data = await self._load_from_file(file_path) or {}

            # Обновляем состояние и временные метки
            storage_data.update({
                "state": self.resolve_state(state),
                "updated_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(hours=self.state_ttl_hours)).isoformat()
            })

            # Если это первое сохранение - добавляем время создания
            if "created_at" not in storage_data:
                storage_data["created_at"] = storage_data["updated_at"]

            await self._save_to_file(file_path, storage_data)

            # Обновляем кэш
            self._update_cache(file_key, storage_data)

    async def get_state(self, key: StorageKey) -> Optional[str]:
        """"Получает состояние FSM"""
        file_key = self._get_file_key(key)
        file_path = self._get_file_path(key)

        # Проверяем кэш
        if file_key in self._cache:
            cached_data = self._cache[file_key]
            if self._is_data_valid(cached_data):
                return cached_data.get("state")
            else:
                # Удаляем невалидные данные из кэша
                del self._cache[file_key]

        # Загружаем из файла
        storage_data = await self._load_from_file(file_path)
        if storage_data and self._is_data_valid(storage_data):
            self._update_cache(file_key, storage_data)
            return storage_data.get("state")

        # Удаляем невалидный файл
        if storage_data:
            await self._remove_file(file_path)

        return None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        """Устанавливает данные состояния (data)."""
        file_key = self._get_file_key(key)

        file_path = self._get_file_path(key)

        lock = await self._get_file_lock(file_key)
        async with lock:
            # Получаем или создаем storage_data
            storage_data = await self._load_from_file(file_path) or {}

            # Обновляем данные и временные метки
            storage_data.update({
                "data": data,
                "updated_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(hours=self.state_ttl_hours)).isoformat()
            })

            if "created_at" not in storage_data:
                storage_data["created_at"] = storage_data["updated_at"]

            await self._save_to_file(file_path, storage_data)
            self._update_cache(file_key, storage_data)

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        """Получает данные состояния FSM"""
        file_key = self._get_file_key(key)
        file_path = self._get_file_path(key)

        # Проверяем кэш
        if file_key in self._cache:
            cached_data = self._cache[file_key]
            if self._is_data_valid(cached_data):
                return cached_data.get("data", {})
            else:
                del self._cache[file_key]

        # Загружаем из файла
        storage_data = await self._load_from_file(file_path)
        if storage_data and self._is_data_valid(storage_data):
            self._update_cache(file_key, storage_data)
            return storage_data.get("data", {})

        # Удаляем невалидный файл
        if storage_data:
            await self._remove_file(file_path)

        return {}

    async def close(self) -> None:
        """Корректное завершение работы хранилища"""
        # Очищаем кэш
        self._cache.clear()
        self._file_locks.clear()
        logger.info("Файловое хранилище FSM закрыто")


    # --- Вспомогательные методы ---

    async def _save_to_file(self, file_path: str, data: Dict)-> bool:
        """Асинхронно сохраняет данные в файл с поддержкой datetime"""
        try:
            content = json.dumps(data, ensure_ascii=False, indent=2, cls=DateTimeEncoder)
            await asyncio.to_thread(file_path.write_text, content, encoding='utf-8')
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения файла состояния {file_path.name}: {e}")
            return False

    async def _get_from_file(self, file_key: str) -> Optional[Dict]:
        """Асинхронно читает данные из файла."""
        file_path = self.storage_dir / file_key
        if not file_path.exists():
            return None

        try:
            # Используем asyncio.to_thread для неблокирующего чтения файла
            content = await asyncio.to_thread(file_path.read_text, 'utf-8')
            data = json.loads(content)

            # Проверяем свежесть данных, чтобы не использовать устаревшие состояния
            if self._is_data_fresh(data):
                return data
            else:
                file_path.unlink() # Удаляем устаревший файл
                return None

        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Файл состояния {file_key} поврежден или нечитаем, удаляем. Ошибка: {e}")
            file_path.unlink() # Удаляем поврежденный файл
            return None

    def _is_data_fresh(self, data: Dict, hours: int = 24) -> bool:
        """Проверяет, что состояние не старше 24 часов."""
        try:
            timestamp = datetime.fromisoformat(data["timestamp"])
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - timestamp < timedelta(hours=hours)
        except (KeyError, ValueError):
            return False

    async def _save_to_file(self, file_path: Path, data: Dict) -> bool:
        """Асинхронно сохраняет данные в файл с поддержкой datetime"""
        try:
            content = json.dumps(data, ensure_ascii=False, indent=2, cls=DateTimeEncoder)
            await asyncio.to_thread(file_path.write_text, content, encoding='utf-8')
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения файла состояния {file_path.name}: {e}")
            return False

    async def _load_from_file(self, file_path: Path) -> Optional[Dict]:
        """Асинхронно загружает данные из файла с восстановлением datetime"""
        if not file_path.exists():
            return None

        try:
            content = await asyncio.to_thread(file_path.read_text, encoding='utf-8')
            return json.loads(content, object_hook=datetime_decoder)
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.warning(f"Ошибка чтения файла состояния FSM {file_path.name}: {e}")
            return None

    async def _remove_file(self, file_path: Path):
        """Асинхронно удаляет файл"""
        try:
            if file_path.exists():
                await asyncio.to_thread(file_path.unlink)
        except Exception as e:
            logger.error(f"Ошибка удаления файла состояния {file_path.name}: {e}")

    def _is_data_valid(self, data: Dict, hours: int = None) -> bool:
        """Проверяет валидность данных по времени"""
        if not data:
            return False

        try:
            expires_at_str = data.get("expires_at")
            if not expires_at_str:
                # Если нет expires_at, проверяем updated_at
                updated_at_str = data.get("updated_at")
                if not updated_at_str:
                    return False

                if isinstance(updated_at_str, str):
                    updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                else:
                    updated_at = updated_at_str

                ttl_hours = hours or self.state_ttl_hours
                return datetime.now() - updated_at < timedelta(hours=ttl_hours)

            if isinstance(expires_at_str, str):
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            else:
                expires_at = expires_at_str

            return datetime.now() < expires_at

        except (ValueError, TypeError) as e:
            logger.debug(f"Ошибка проверки валидности данных: {e}")
            return False

    def _update_cache(self, file_key: str, data: Dict):
        """Обновляет кэш с ограничением размера"""
        # Проверяем размер кэша
        if len(self._cache) >= self._cache_max_size:
            # Удаляем самый старый элемент (простая реализация LRU)
            try:
                oldest_key = min(
                    self._cache.keys(),
                    key=lambda k: self._cache[k].get("updated_at", "")
                )
                del self._cache[oldest_key]
            except (ValueError, KeyError):
                # Если кэш пуст или произошла ошибка, очищаем его
                self._cache.clear()

        self._cache[file_key] = data

    # Методы для обслуживания и отладки

    async def cleanup_expired_states(self):
        """Очищает просроченные состояния (можно вызывать периодически)"""
        cleaned_count = 0

        # Очищаем кэш
        expired_keys = [
            key for key, data in self._cache.items()
            if not self._is_data_valid(data)
        ]

        for key in expired_keys:
            del self._cache[key]
            cleaned_count += 1

        # Очищаем файлы
        state_files = list(self.storage_dir.glob("state_*.json"))
        for state_file in state_files:
            try:
                data = await self._load_from_file(state_file)
                if not data or not self._is_data_valid(data):
                    await self._remove_file(state_file)
                    cleaned_count += 1
            except Exception:
                # Удаляем поврежденные файлы
                await self._remove_file(state_file)
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Очищено {cleaned_count} просроченных состояний FSM")

        return cleaned_count

    async def get_storage_stats(self) -> Dict[str, int]:
        """Возвращает статистику хранилища"""
        cache_size = len(self._cache)

        file_count = len(list(self.storage_dir.glob("state_*.json")))

        # Подсчитываем валидные файлы
        valid_files = 0
        for state_file in self.storage_dir.glob("state_*.json"):
            try:
                data = await self._load_from_file(state_file)
                if data and self._is_data_valid(data):
                    valid_files += 1
            except Exception:
                continue

        return {
            "cache_size": cache_size,
            "total_files": file_count,
            "valid_files": valid_files,
            "expired_files": file_count - valid_files
        }

    async def clear_all_states(self):
        """Очищает все состояния (для тестирования)"""
        # Очищаем кэш
        self._cache.clear()

        # Удаляем все файлы
        state_files = list(self.storage_dir.glob("state_*.json"))
        for state_file in state_files:
            await self._remove_file(state_file)

        logger.info("Все состояния FSM очищены")