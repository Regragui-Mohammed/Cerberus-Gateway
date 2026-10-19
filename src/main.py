import asyncio
import logging
import socket
import ssl
import sys
from pydantic import ValidationError
from src.database import db
from src.dlq import DeadLetterQueue
from src.limiter import TokenBucketLimiter
from src.models import TelemetryPayload
from src.repository import TelemetryRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("cerberus.gateway")

# Global pipeline primitives
QUEUE_MAX_SIZE = 1000
telemetry_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
rate_limiter = TokenBucketLimiter(capacity=10.0, refill_rate=5.0)
dlq = DeadLetterQueue("logs/dlq.jsonl")
repo = TelemetryRepository(db)


async def db_consumer_worker() -> None:
    """
    Background worker draining the queue, validating payloads,
    and persisting records into TimescaleDB via TelemetryRepository.
    """
    logger.info("DB Ingestion worker started.")
    while True:
        try:
            tenant_id, raw_payload = await telemetry_queue.get()

            # 1. Strict validation via Pydantic V2
            try:
                payload = TelemetryPayload.model_validate_json(raw_payload)
            except ValidationError as val_err:
                logger.warning("Validation failed for tenant %s. Quarantining to DLQ.", tenant_id)
                await dlq.record_failure(
                    tenant_id=tenant_id,
                    raw_payload=raw_payload,
                    error_type=type(val_err).__name__,
                    error_details=str(val_err),
                )
                telemetry_queue.task_done()
                continue

            # 2. Persist to TimescaleDB hypertable
            try:
                await repo.insert_telemetry(tenant_id, payload)
            except Exception as db_err:
                logger.error("Failed to insert record into TimescaleDB: %s", db_err)
                await dlq.record_failure(
                    tenant_id=tenant_id,
                    raw_payload=raw_payload,
                    error_type=type(db_err).__name__,
                    error_details=str(db_err),
                )

            telemetry_queue.task_done()

        except asyncio.CancelledError:
            logger.info("DB Ingestion worker received shutdown cancellation.")
            break
        except Exception as err:
            logger.error("Unexpected worker exception: %s", err)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Handles incoming client mTLS TCP connection and passes payload to the queue."""
    peername = writer.get_extra_info("peername")

    try:
        # Extract Tenant identity from mTLS certificate
        cert = writer.get_extra_info("peercert")
        if not cert:
            writer.close()
            await writer.wait_closed()
            return

        tenant_id = dict(x[0] for x in cert["subject"])["commonName"]

        # Enforce Rate Limiting
        allowed = await rate_limiter.acquire(tenant_id)
        if not allowed:
            logger.warning("Rate limit exceeded for tenant: %s", tenant_id)
            writer.write(b"HTTP/1.1 429 Too Many Requests\r\n\r\n")
            await writer.drain()
            return

        # Read incoming payload
        data = await reader.read(4096)
        if not data:
            return

        raw_payload = data.decode("utf-8", errors="replace").strip()

        # Push to queue (non-blocking backpressure handling)
        try:
            telemetry_queue.put_nowait((tenant_id, raw_payload))
            writer.write(b"ACK: Queued for ingestion\n")
            await writer.drain()
        except asyncio.QueueFull:
            logger.error("Backpressure limit reached. Ingestion queue full.")
            writer.write(b"HTTP/1.1 503 Service Unavailable (Queue Full)\r\n\r\n")
            await writer.drain()

    except Exception as exc:
        logger.error("Error handling client %s: %s", peername, exc)
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    # 1. Initialize Database Pool
    await db.connect()

    # 2. Start background ingestion consumer worker
    worker_task = asyncio.create_task(db_consumer_worker())

    # 3. Setup TLS/mTLS context
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="config/certs/server.pem", keyfile="config/certs/server.key")
    context.load_verify_locations(cafile="config/certs/ca.pem")
    context.verify_mode = ssl.CERT_REQUIRED

    # 4. Bind socket (fallback to standalone if systemd socket is absent)
    try:
        sock = socket.fromfd(3, socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        server = await asyncio.start_server(handle_client, sock=sock, ssl=context)
        logger.info("Cerberus Gateway started with Systemd socket.")
    except OSError:
        server = await asyncio.start_server(handle_client, host="0.0.0.0", port=8443, ssl=context)
        logger.info("Cerberus Gateway started in standalone mode on port 8443.")

    try:
        async with server:
            await server.serve_forever()
    finally:
        logger.info("Initiating graceful shutdown...")
        # Cancel worker and wait for queue drainage
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        # Close connection pool
        await db.disconnect()
        logger.info("Shutdown sequence completed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Terminated by user.")
