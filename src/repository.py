from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from src.database import Database, db
from src.models import TelemetryPayload

logger = logging.getLogger("cerberus.repository")


class TelemetryRepository:
    """
    Repository pattern isolating database persistence operations for telemetry data.
    Provides methods for atomic and batch insertions into TimescaleDB hypertable.
    """

    def __init__(self, database: Optional[Database] = None) -> None:
        self.db: Database = database or db

    async def insert_telemetry(self, tenant_id: str, payload: TelemetryPayload) -> None:
        """Inserts a single validated telemetry record."""
        query = """
        INSERT INTO telemetry (timestamp, tenant_id, device_id, temperature, pressure, status)
        VALUES ($1, $2, $3, $4, $5, $6);
        """
        async with self.db.acquire() as conn:
            await conn.execute(
                query,
                payload.timestamp,
                tenant_id,
                payload.device_id,
                payload.temperature,
                payload.pressure,
                payload.status,
            )
            logger.debug("Persisted telemetry for device %s", payload.device_id)

    async def insert_batch(
        self, records: List[Tuple[datetime, str, str, float, float, str]]
    ) -> None:
        """
        Batch inserts multiple telemetry tuples for maximum ingestion throughput.
        Each tuple must match: (timestamp, tenant_id, device_id, temperature, pressure, status)
        """
        query = """
        INSERT INTO telemetry (timestamp, tenant_id, device_id, temperature, pressure, status)
        VALUES ($1, $2, $3, $4, $5, $6);
        """
        async with self.db.acquire() as conn:
            await conn.executemany(query, records)
            logger.info("Successfully ingested batch of %d telemetry records", len(records))

    async def get_latest_metrics(
        self, tenant_id: str, device_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Queries the most recent telemetry readings using the hypertable composite index."""
        query = """
        SELECT timestamp, tenant_id, device_id, temperature, pressure, status
        FROM telemetry
        WHERE tenant_id = $1 AND device_id = $2
        ORDER BY timestamp DESC
        LIMIT $3;
        """
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, device_id, limit)
            return [dict(row) for row in rows]
