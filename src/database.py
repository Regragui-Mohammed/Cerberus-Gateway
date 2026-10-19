import os
import logging
from typing import Optional
from contextlib import asynccontextmanager
import asyncpg

logger = logging.getLogger("cerberus.database")

class Database:
    def __init__(self, dsn: Optional[str] = None, min_size: int = 5, max_size: int = 20, ) -> None:
        self.dsn: str = dsn or os.getenv(
            "DATABASE_URL",
            "postgresql://cerberus_user:cerberus_password@127.0.0.1:5432/cerberus_db",
        )
        self.min_size: int = min_size
        self.max_size: int = max_size
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self._pool is not None:
            return

        try:
            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=self.min_size,
                max_size=self.max_size,
                command_timeout=10.0,
            )
            logger.info("Database connection pool established successfully.")
        except Exception as e:
            logger.error("Failed to connect to TimescaleDB: %s", e)
            raise

    async def disconnect(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Database connection pool closed.")

    @asynccontextmanager
    async def acquire(self):
        if self._pool is None:
            raise RuntimeError("Database pool is not initialized. Call connect() first.")

        async with self._pool.acquire() as connection:
            yield connection

db = Database()
