import asyncio
import logging
import socket
import ssl
import sys
from typing import Tuple

from pydantic import ValidationError

from src.dlq import DeadLetterQueue
from src.limiter import TokenBucketLimiter
from src.models import TelemetryPayload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

QUEUE_CAPACITY: int = 100
telemetry_queue: asyncio.Queue[Tuple[str, str]] = asyncio.Queue(maxsize=QUEUE_CAPACITY)
dlq_engine = DeadLetterQueue("logs/dlq.jsonl")
rate_limiter = TokenBucketLimiter(capacity=5.0, refill_rate=2.0)


async def telemetry_worker(queue: asyncio.Queue[Tuple[str, str]], dlq: DeadLetterQueue) -> None:
    """
    Background consumer coroutine that decouples TCP ingestion from validation processing.
    Pulls messages from the backpressure queue, applies strict Pydantic validation,
    and isolates corrupted payloads inside the Dead-Letter Queue.
    """
    logging.info("⚙️Telemetry background worker started.")
    while True:
        tenant_id, raw_payload = await queue.get()
        try:
            telemetry: TelemetryPayload = TelemetryPayload.model_validate_json(raw_payload)
            logging.info(
                f"Valid telemetry from [{tenant_id}] - Device: {telemetry.device_id} | "
                f"Temp: {telemetry.temperature}°C | Pressure: {telemetry.pressure} hPa"
            )
        except ValidationError as err:
            logging.warning(f"Validation failure from [{tenant_id}]. Isolating payload to DLQ...")
            await dlq.record_failure(
                tenant_id=tenant_id,
                raw_payload=raw_payload,
                error_type=type(err).__name__,
                error_details=str(err)
            )
        except Exception as err:
            logging.error(f"Unexpected processing error from [{tenant_id}]: {err}")
            await dlq.record_failure(
                tenant_id=tenant_id,
                raw_payload=raw_payload,
                error_type=type(err).__name__,
                error_details=str(err)
            )
        finally:
            queue.task_done()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """
    Producer handler per connection:
    1. Authenticates client via mTLS certificate CN.
    2. Enforces per-tenant rate limits.
    3. Pushes payload into the bounded queue to apply backpressure.
    """
    peername = writer.get_extra_info("peername")
    try:
        # 1. mTLS Peer Verification
        cert = writer.get_extra_info("peercert")
        if not cert:
            logging.warning(f"Unauthenticated connection attempt from {peername}.")
            writer.close()
            await writer.wait_closed()
            return

        tenant_id = dict(x[0] for x in cert["subject"])["commonName"]

        # 2. Rate Limiting Check (Token Bucket)
        if not await rate_limiter.acquire(tenant_id):
            logging.warning(f"Rate limit exceeded for tenant [{tenant_id}]. Dropping request.")
            writer.write(b"ERROR 429: Rate limit quota exceeded.\n")
            await writer.drain()
            return

        # 3. Read payload
        data = await reader.read(4096)
        if not data:
            return

        raw_payload = data.decode("utf-8", errors="replace").strip()

        # 4. Backpressure Protection (Bounded Queue)
        try:
            telemetry_queue.put_nowait((tenant_id, raw_payload))
            writer.write(f"ACK: Telemetry received and queued for [{tenant_id}]\n".encode())
            await writer.drain()
        except asyncio.QueueFull:
            logging.error(f"Server backpressure triggered: Queue is full ({QUEUE_CAPACITY} items).")
            writer.write(b"ERROR 503: Service overloaded. Buffer full.\n")
            await writer.drain()

    except Exception as e:
        logging.error(f"Network handler error with {peername}: {e}")
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    worker_task = asyncio.create_task(telemetry_worker(telemetry_queue, dlq_engine))

    # 2. Configure mTLS context
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="config/certs/server.pem", keyfile="config/certs/server.key")
    context.load_verify_locations(cafile="config/certs/ca.pem")
    context.verify_mode = ssl.CERT_REQUIRED

    # 3. Bind Systemd Socket or standalone fallback
    try:
        sock = socket.fromfd(3, socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        logging.info("Systemd Socket acquired via File Descriptor 3.")
        server = await asyncio.start_server(handle_client, sock=sock, ssl=context)
    except OSError:
        logging.warning("FD 3 unavailable. Starting standalone TCP server on 0.0.0.0:8443...")
        server = await asyncio.start_server(handle_client, host="0.0.0.0", port=8443, ssl=context)

    logging.info("Cerberus Gateway (Sprint 3) actively listening...")
    try:
        async with server:
            await server.serve_forever()
    finally:
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Gateway shutdown gracefully.")
