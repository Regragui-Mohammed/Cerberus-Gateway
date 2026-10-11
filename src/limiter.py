import asyncio
import time
from typing import Dict, Tuple


class TokenBucketLimiter:

    def __init__(self, capacity: float = 5.0, refill_rate: float = 2.0) -> None:
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._buckets: Dict[str, Tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, tenant_id: str, tokens: float = 1.0) -> bool:
        async with self._lock:
            now = time.monotonic()

            if tenant_id not in self._buckets:
                self._buckets[tenant_id] = (self.capacity, now)

            current_tokens, last_refill = self._buckets[tenant_id]

            elapsed = now - last_refill
            current_tokens = min(self.capacity, current_tokens + (elapsed * self.refill_rate))

            if current_tokens >= tokens:
                self._buckets[tenant_id] = (current_tokens - tokens, now)
                return True

            self._buckets[tenant_id] = (current_tokens, now)
            return False
