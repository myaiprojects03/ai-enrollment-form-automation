"""Short-lived shared state: idempotency gates and locks. Redis in production (shared by every worker and
server); an in-memory version for development and tests (correct for one process only)."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

from redis.asyncio import Redis

PREFIX = "enroll:"


class SharedStore(ABC):
    @abstractmethod
    async def add(self, key: str, value: str, ttl_s: int) -> bool:
        """Set only if absent; True when this call set it (the caller owns the key)."""

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def put(self, key: str, value: str, ttl_s: int) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def incr(self, key: str, ttl_s: int) -> int:
        """Count up; the count expires ttl_s after the first increment (a fixed window)."""

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class RedisStore(SharedStore):
    def __init__(self, client: Redis):
        self.client = client

    async def add(self, key: str, value: str, ttl_s: int) -> bool:
        return bool(await self.client.set(PREFIX + key, value, ex=ttl_s, nx=True))

    async def get(self, key: str) -> str | None:
        v = await self.client.get(PREFIX + key)
        return v if v is None or isinstance(v, str) else v.decode()

    async def put(self, key: str, value: str, ttl_s: int) -> None:
        await self.client.set(PREFIX + key, value, ex=ttl_s)

    async def delete(self, key: str) -> None:
        await self.client.delete(PREFIX + key)

    async def incr(self, key: str, ttl_s: int) -> int:
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.incr(PREFIX + key)
            pipe.expire(PREFIX + key, ttl_s, nx=True)
            count, _ = await pipe.execute()
        return int(count)

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception:
            return False

    async def aclose(self) -> None:
        await self.client.aclose()


class MemoryStore(SharedStore):
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    def _live(self, key: str) -> str | None:
        item = self._data.get(key)
        if item and item[1] > time.monotonic():
            return item[0]
        self._data.pop(key, None)
        return None

    async def add(self, key: str, value: str, ttl_s: int) -> bool:
        if self._live(key) is not None:
            return False
        self._data[key] = (value, time.monotonic() + ttl_s)
        return True

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def put(self, key: str, value: str, ttl_s: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl_s)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, ttl_s: int) -> int:
        current = self._live(key)
        expires = self._data[key][1] if current is not None else time.monotonic() + ttl_s
        count = int(current or 0) + 1
        self._data[key] = (str(count), expires)
        return count


async def build_store(redis_url: str, production: bool) -> SharedStore:
    if not redis_url:
        if production:
            raise RuntimeError("REDIS_URL is required in production: idempotency must be shared by all workers")
        return MemoryStore()
    client = Redis.from_url(redis_url, decode_responses=True, socket_timeout=5)
    store = RedisStore(client)
    if not await store.ping():
        await store.aclose()
        if production:
            raise RuntimeError("Redis is not reachable")
        return MemoryStore()
    return store
