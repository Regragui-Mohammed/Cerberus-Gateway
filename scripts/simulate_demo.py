#!/usr/bin/env python3
"""
Cerberus Gateway — Live Traffic & Attack Simulator for LinkedIn Demo / Video
Usage:
    # 1. Continuous stream (runs indefinitely until Ctrl+C):
    python scripts/simulate_demo.py

    # 2. Fixed count:
    python scripts/simulate_demo.py --count 100

    # 3. Simulate malicious attacker payload fuzzing:
    python scripts/simulate_demo.py --attack
"""

import argparse
import itertools
import json
import random
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def get_ssl_context() -> ssl.SSLContext:
    cert_dir = Path("config/certs")
    client_cert = cert_dir / "client.pem"
    client_key = cert_dir / "client.key"
    ca_cert = cert_dir / "ca.pem"

    if not client_cert.exists() or not ca_cert.exists():
        print("❌ Certificates not found in config/certs! Run ./config/generate_certs.sh first.")
        sys.exit(1)

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_cert))
    context.load_cert_chain(certfile=str(client_cert), keyfile=str(client_key))
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def send_payload(payload_str: str, host: str = "127.0.0.1", port: int = 8443) -> str:
    ctx = get_ssl_context()
    with socket.create_connection((host, port), timeout=3.0) as raw_sock:
        with ctx.wrap_socket(raw_sock, server_hostname="Cerberus_Server") as s:
            s.sendall(payload_str.encode("utf-8"))
            response = s.recv(1024).decode("utf-8").strip()
            return response


def run_normal_simulation(count: int = 0, delay: float = 0.8) -> None:
    devices = [f"SENSOR-{i:03d}" for i in range(1, 6)]
    is_infinite = (count <= 0)

    mode_str = "CONTINUOUS STREAM (Press Ctrl+C to stop)" if is_infinite else f"{count} packets"
    print(f"🚀 Starting legitimate IoT telemetry stream [{mode_str}, interval={delay}s]...\n")

    counter = itertools.count(1) if is_infinite else range(1, count + 1)

    try:
        for i in counter:
            dev = random.choice(devices)
            temp = round(random.uniform(21.0, 28.5) + (6.0 if random.random() < 0.1 else 0), 2)
            pressure = round(random.uniform(1011.0, 1016.0), 2)
            status = "WARNING" if temp > 32.0 else "OK"

            payload = {
                "device_id": dev,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "temperature": temp,
                "pressure": pressure,
                "status": status,
            }

            try:
                resp = send_payload(json.dumps(payload))
                prefix = f"[{i:04d}]" if is_infinite else f"[{i:02d}/{count}]"
                print(f"{prefix} Sent {dev} | Temp: {temp:5.2f}°C | Status: {status:7s} -> {resp}")
            except Exception as e:
                print(f"[{i}] Connection error: {e}")

            time.sleep(delay)
    except KeyboardInterrupt:
        print("\n\n🛑 Telemetry stream stopped by user.")

    print("✅ Check Grafana dashboard at http://localhost:3000/d/cerberus-overview")


def run_attack_simulation() -> None:
    print("🚨 Simulating Malicious Threat Actor (Schema Poisoning & Fuzzing)...")
    malicious_payloads = [
        '{"device_id": "SENSOR-EVIL", "temperature": "CORRUPTED_STRING", "pressure": 1013.25}',
        '{"device_id": "X", "temperature": 9999.0, "pressure": -10.0, "status": "UNKNOWN"}',
        '{"raw_exploit": "<script>alert(1)</script>", "buffer_overflow": "A" * 1024}',
    ]

    for i, bad_payload in enumerate(malicious_payloads, 1):
        print(f"\n⚠️ Sending Malicious Payload #{i}...")
        try:
            resp = send_payload(bad_payload)
            print(f"Gateway Response: {resp}")
        except Exception as e:
            print(f"Connection dropped/banned: {e}")
        time.sleep(1.0)

    print("\n🛡️ Check Gateway Logs for KERNEL BAN APPLIED and logs/dlq.jsonl for recorded violations!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cerberus Gateway Traffic & Attack Simulator")
    parser.add_argument("--attack", action="store_true", help="Simulate malformed payloads and trigger IP ban")
    parser.add_argument("--count", type=int, default=0, help="Number of telemetry packets (0 = infinite continuous stream)")
    parser.add_argument("--delay", type=float, default=0.8, help="Delay in seconds between packets (default: 0.8s)")
    args = parser.parse_args()

    if args.attack:
        run_attack_simulation()
    else:
        run_normal_simulation(count=args.count, delay=args.delay)
