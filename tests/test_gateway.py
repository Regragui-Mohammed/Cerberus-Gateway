import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.dlq import DeadLetterQueue
from src.firewall import ActiveDefenseFirewall
from src.limiter import TokenBucketLimiter
from src.models import TelemetryPayload


# ==========================================
# 1. Pydantic V2 Schema Validation Tests
# ==========================================
def test_telemetry_payload_valid() -> None:
    raw = json.dumps({
        "device_id": "SENSOR-01",
        "timestamp": "2026-11-12T18:00:00Z",
        "temperature": 22.5,
        "pressure": 1013.25,
        "status": "OK",
    })
    payload = TelemetryPayload.model_validate_json(raw)
    assert payload.device_id == "SENSOR-01"
    assert payload.temperature == 22.5
    assert payload.pressure == 1013.25


def test_telemetry_payload_rejects_corrupted_types() -> None:
    bad_raw = json.dumps({
        "device_id": "SENSOR-01",
        "timestamp": "2026-11-12T18:00:00Z",
        "temperature": "HACKED_STRING",
        "pressure": 1013.25,
        "status": "OK",
    })
    with pytest.raises(ValidationError):
        TelemetryPayload.model_validate_json(bad_raw)


# ==========================================
# 2. Dead-Letter Queue (DLQ) Tests
# ==========================================
async def test_dlq_records_malformed_payload(tmp_path: Path) -> None:
    dlq_file = tmp_path / "test_dlq.jsonl"
    dlq = DeadLetterQueue(str(dlq_file))

    await dlq.record_failure(
        tenant_id="Tenant_001",
        raw_payload='{"bad": "json"}',
        error_type="ValidationError",
        error_details="Field required",
    )

    assert dlq_file.exists()
    lines = dlq_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["tenant_id"] == "Tenant_001"
    assert entry["error_type"] == "ValidationError"
    assert entry["raw_payload"] == '{"bad": "json"}'


# ==========================================
# 3. Token-Bucket Rate Limiter Tests
# ==========================================
async def test_token_bucket_burst_and_refill() -> None:
    limiter = TokenBucketLimiter(capacity=2.0, refill_rate=2.0)
    tenant = "Tenant_001"

    # Burst of 2 requests must succeed
    assert await limiter.acquire(tenant) is True
    assert await limiter.acquire(tenant) is True
    # 3rd immediate request must be rejected
    assert await limiter.acquire(tenant) is False

    # After 0.6s at 2 tokens/sec, >1 token is replenished
    await asyncio.sleep(0.6)
    assert await limiter.acquire(tenant) is True


# ==========================================
# 4. Active Defense Kernel Firewall Tests
# ==========================================
async def test_firewall_bans_after_max_strikes() -> None:
    fw = ActiveDefenseFirewall(max_strikes=3, strike_window=60.0, ban_duration="5m")
    attacker_ip = "203.0.113.55"

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
        # Strikes 1 and 2 should NOT trigger kernel ban yet
        assert await fw.record_violation(attacker_ip, "Bad payload 1") is False
        assert await fw.record_violation(attacker_ip, "Bad payload 2") is False
        mock_exec.assert_not_called()

        # Strike 3 MUST trigger nftables wrapper subprocess
        assert await fw.record_violation(attacker_ip, "Bad payload 3") is True
        mock_exec.assert_called_once_with(
            "sudo",
            "-n",
            "/usr/local/bin/cerberus-ban",
            attacker_ip,
            "5m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )


async def test_firewall_ignores_protected_ips() -> None:
    fw = ActiveDefenseFirewall(max_strikes=1, protected_ips={"10.0.0.1"})

    with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
        banned = await fw.record_violation("10.0.0.1", "Admin typo")
        assert banned is False
        mock_exec.assert_not_called()
