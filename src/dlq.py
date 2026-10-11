import asyncio
from datetime import datetime, timezone
import json 
from pathlib import Path
from typing import Any, Dict

class DeadLetterQueue:

    def __init__(self, log_path: str = "logs/dlq.jsonl") -> None:
        self.log_file = Path(log_path)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _format_entry(
        self,
        tenant_id: str,
        raw_payload: str,
        error_type: str,
        error_details: str
    ) -> str:
        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenant_id": tenant_id,
            "raw_payload": raw_payload,
            "error_type": error_type,
            "error_details": error_details
        }
        return json.dumps(entry) + "\n"

    def _sync_write(self, data: str) -> None:
        with open(self.log_file, mode="a", encoding="utf-8") as f:
            f.write(data)

    async def record_failure(
        self,
        tenant_id: str,
        raw_payload: str,
        error_type: str,
        error_details: str
    ) -> None:
        line = self._format_entry(
            tenant_id=tenant_id,
            raw_payload=raw_payload,
            error_type=error_type,
            error_details=error_details
        )
        async with self._lock:
            await asyncio.to_thread(self._sync_write, line)
