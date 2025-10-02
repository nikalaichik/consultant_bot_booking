import time
import asyncio
from typing import Dict, Tuple, Optional
from functools import wraps

class SmartRateLimiter:
    """
    Rate limiter: работает как in-memory.
    При необходимости можно переключить на Redis (раскомментировать блок).
    """
    def __init__(self, redis_client: Optional[object] = None):
        # лимиты: категория -> (count, window_seconds)
        self.limits = {
            "text": (20, 60),      # 20 текстов в минуту
            "photo": (5, 60),      # 5 фото в минуту
            "booking": (3, 300),   # 3 записи за 5 минут
        }
        self._store: Dict[Tuple[int, str], list] = {}
        self._lock = asyncio.Lock()
        self.redis = redis_client

    async def allow(self, user_id: int, category: str) -> bool:
        if category not in self.limits:
            return True

        max_count, window = self.limits[category]

        # --- Redis вариант (для проды) ---
        if self.redis:
            try:
                key = f"ratelimit:{category}:{user_id}"
                cnt = await self.redis.incr(key)
                if cnt == 1:
                    await self.redis.expire(key, window)
                return cnt <= max_count
            except Exception:
                # fail-open — если Redis упал, не блокируем
                return True

        # --- In-memory вариант ---
        now = time.time()
        async with self._lock:
            k = (user_id, category)
            lst = self._store.get(k, [])
            # удаляем старые записи
            lst = [t for t in lst if t > now - window]
            if len(lst) >= max_count:
                self._store[k] = lst
                return False
            lst.append(now)
            self._store[k] = lst
            return True


# глобальный экземпляр
rate_limiter = SmartRateLimiter()


def rate_limit(category: str):
    """
    Декоратор для aiogram-хендлеров.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user_id = None
            if args:
                first = args[0]
                if hasattr(first, "from_user") and getattr(first.from_user, "id", None):
                    user_id = first.from_user.id
                elif hasattr(first, "message") and hasattr(first.message, "from_user"):
                    user_id = first.message.from_user.id
            if user_id is None:
                user_id = kwargs.get("user_id", 0)

            allowed = await rate_limiter.allow(user_id, category)
            if not allowed:
                try:
                    if hasattr(first, "answer"):
                        await first.answer("⚠️ Слишком много запросов. Попробуйте позже.")
                    elif hasattr(first, "message") and hasattr(first.message, "answer"):
                        await first.message.answer("⚠️ Слишком много запросов. Попробуйте позже.")
                except Exception:
                    pass
                return
            return await func(*args, **kwargs)
        return wrapper
    return decorator
