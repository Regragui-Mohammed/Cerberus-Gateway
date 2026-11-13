import asyncio
import logging
import os
import signal
import socket
import ssl
from typing import Tuple

from pydantic import ValidationError

from src.database import Database
from src.dlq import DeadLetterQueue
from src.firewall import ActiveDefenseFirewall
from src.limiter import TokenBucketLimiter
from src.models import TelemetryPayload
from src.repository import TelemetryRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cerberus.gateway")


def build_mtls_context() -> ssl.SSLContext:
    """Configures Mutual TLS (mTLS) enforcing client certificate verification."""
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(
        certfile="config/certs/server.pem",
        keyfile="config/certs/server.key",
    )
    context.load_verify_locations(cafile="config/certs/ca.pem")
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def extract_tenant_id(writer: asyncio.StreamWriter) -> str:
    """Extracts the Common Name (CN) from the verified client X.509 certificate."""
    cert = writer.get_extra_info("peercert")
    if not cert or "subject" not in cert:
        return "unknown_tenant"
    subject = dict(x[0] for x in cert["subject"])
    return str(subject.get("commonName", "unknown_tenant"))


async def db_consumer_worker(
    queue: asyncio.Queue[Tuple[str, str, str]],
    repo: TelemetryRepository,
    dlq: DeadLetterQueue,
    firewall: ActiveDefenseFirewall,
) -> None:
    """
    Background worker consuming raw telemetry from the backpressure queue,
    validating with Pydantic V2, persisting to TimescaleDB, and reporting
    schema violations to the Active Defense Firewall.
    """
    while True:
        client_ip, tenant_id, raw_payload = await queue.get()
        try:
            payload = TelemetryPayload.model_validate_json(raw_payload)
            await repo.insert_telemetry(tenant_id, payload)
            logger.info(
                "Persisted telemetry | Tenant: %s | Device: %s | Temp: %.2f",
                tenant_id,
                payload.device_id,
                payload.temperature,
            )
        except ValidationError as err:
            logger.warning(
                "Invalid payload from %s (%s) -> Routing to DLQ",
                tenant_id,
                client_ip,
            )
            await dlq.record_failure(
                tenant_id=tenant_id,
                raw_payload=raw_payload,
                error_type=type(err).__name__,
                error_details=str(err),
            )
            await firewall.record_violation(
                client_ip,
                reason=f"Malformed telemetry JSON from {tenant_id}",
            )
        except Exception as exc:
            logger.exception("Unexpected worker error: %s", exc)
        finally:
            queue.task_done()


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    queue: asyncio.Queue[Tuple[str, str, str]],
    limiter: TokenBucketLimiter,
    firewall: ActiveDefenseFirewall,
) -> None:
    """Handles an incoming mTLS client connection with rate limiting and backpressure."""
    peername = writer.get_extra_info("peername")
    client_ip: str = str(peername[0]) if peername else "0.0.0.0"
    tenant_id = extract_tenant_id(writer)

    try:
        if not await limiter.acquire(tenant_id):
            logger.warning("Rate limit exceeded | Tenant: %s | IP: %s", tenant_id, client_ip)
            await firewall.record_violation(
                client_ip,
                reason=f"Rate limit exceeded by {tenant_id}",
            )
            writer.write(b"ERR: Rate limit exceeded\n")
            await writer.drain()
            return

        data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        if not data:
            return

        try:
            raw_payload = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            await firewall.record_violation(client_ip, reason="Non-UTF8 binary fuzzing")
            writer.write(b"ERR: Invalid encoding\n")
            await writer.drain()
            return

        try:
            queue.put_nowait((client_ip, tenant_id, raw_payload))
            writer.write(b"ACK: Telemetry accepted\n")
        except asyncio.QueueFull:
            logger.error("Backpressure queue full! Dropping packet from %s", tenant_id)
            writer.write(b"ERR: Gateway overloaded (Backpressure)\n")

        await writer.drain()

    except asyncio.TimeoutError:
        await firewall.record_violation(client_ip, reason="Connection read timeout (Slowloris)")
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    # 1. Initialize Sprint 3, 4 & 5 subsystems
    telemetry_queue: asyncio.Queue[Tuple[str, str, str]] = asyncio.Queue(maxsize=1000)
    limiter = TokenBucketLimiter(capacity=10.0, refill_rate=5.0)
    dlq = DeadLetterQueue("logs/dlq.jsonl")
    firewall = ActiveDefenseFirewall(
        max_strikes=3,
        strike_window=60.0,
        ban_duration="60s",
        protected_ips=set(),
    )

    db = Database()
    await db.connect()
    repo = TelemetryRepository(db)

    # 2. Launch background DB & Validation consumer worker
    worker_task = asyncio.create_task(
        db_consumer_worker(telemetry_queue, repo, dlq, firewall)
    )

    # 3. Start mTLS Server (Systemd Socket Activation or Standalone)
    ssl_ctx = build_mtls_context()
    client_callback = lambda r, w: handle_client(r, w, telemetry_queue, limiter, firewall)

    if os.environ.get("LISTEN_FDS"):
        sock = socket.fromfd(3, socket.AF_INET, socket.SOCK_STREAM)
        server = await asyncio.start_server(client_callback, sock=sock, ssl=ssl_ctx)
        logger.info("Cerberus Gateway started via Systemd Socket Activation (FD 3)")
    else:
        server = await asyncio.start_server(
            client_callback, host="0.0.0.0", port=8443, ssl=ssl_ctx
        )
        logger.info("Cerberus Gateway listening on 0.0.0.0:8443 (Standalone mTLS)")

    # 4. Graceful Shutdown handling
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    async with server:
        await stop_event.wait()

    logger.info("Shutting down Cerberus Gateway gracefully...")
    await telemetry_queue.join()
    worker_task.cancel()
    await db.disconnect()
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
