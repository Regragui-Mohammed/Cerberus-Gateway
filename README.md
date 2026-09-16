# 🛡️ Projet: Cerberus (Secure IoT/Telemetry Gateway)

> An Enterprise-grade, Zero-Idle Asynchronous Gateway for Secure IoT Telemetry Data Ingestion.

## 📖 Introduction
**Cerberus** is a high-performance, asynchronous Python-based gateway designed to securely receive, validate, and store thousands of concurrent requests from IoT sensors and APIs[cite: 7]. Built with a strict focus on Software Engineering best practices and Linux system administration, it bridges the gap between raw infrastructure and data systems[cite: 4, 7].

## 🛑 Problem Statement
In large-scale AI and Industry 4.0 integrations, enterprises rely on thousands of IoT sensors transmitting data simultaneously[cite: 7]. This introduces three critical challenges that Cerberus solves:
1. **Server Collapse (Concurrency):** Standard synchronous frameworks (like Flask or Django) often crash under heavy concurrent loads[cite: 7].
2. **Corrupted Pipelines (Bad Data):** Malformed JSON payloads can break downstream Machine Learning pipelines[cite: 7].
3. **Cybersecurity Threats:** Public-facing gateways are constantly exposed to network scans, spoofed IPs, and DDoS attacks[cite: 7].

## 💡 The Solution & Architecture
Cerberus is built from the ground up to be resilient, secure, and resource-efficient:
* **Zero-Idle & Multi-Tenancy:** Utilizes Linux Systemd Socket Activation to keep the server asleep until data arrives, and isolates each tenant using `cgroup v2` (DynamicUser, NoNewPrivileges, MemoryMax).
* **Asynchronous Engine:** Leverages Python's `asyncio` (`asyncio.start_server`) to handle massive concurrency without blocking the CPU[cite: 7, 8].
* **Strict Authentication (mTLS):** Enforces Mutual TLS (`ssl.SSLContext`) to cryptographically verify the identity (Certificates) of every sensor before accepting connections.
* **Robust Validation:** Uses **Pydantic V2** in strict mode to validate incoming payloads. Invalid data is safely routed to a Dead-Letter Queue (DLQ) rather than crashing the system[cite: 7, 8].
* **Active Auto-Defense:** Integrates with the Linux kernel firewall (`nftables`) via async subprocesses to instantly IP-ban attackers and handle rate-limiting (Token-Bucket)[cite: 7, 8].

## ⚙️ Tech Stack
* **Language:** Advanced Python 3 (asyncio, mypy strict typing)[cite: 6, 8]
* **Infrastructure:** Linux (Systemd, Bash, cgroup v2, nftables)
* **Security:** OpenSSL (mTLS / Client Certificates)
* **Data Validation:** Pydantic V2
* **Testing:** Pytest & pytest-asyncio

## 📂 Project Structure
```text
cerberus-gateway/
├── config/
│   ├── generate_certs.sh       # mTLS Certificate Authority & Generation
│   └── certs/                  # .pem and .key files
├── src/
│   └── main.py                 # Asyncio Engine & Request Handler
├── systemd/
│   ├── cerberus.socket         # Socket Activation
│   └── cerberus@.service       # Sandboxed Template Unit
├── tests/
└── pyproject.toml              # Dependencies & Config

```

## 🗺️ System Architecture

```text
[ IoT Sensors / Clients ]
           │ (mTLS / TCP)
           ▼
┌───────────────────────────────────────────────┐
│              Linux OS (Kernel)                │
│   cerberus.socket  ──► Socket Activation      │
└──────────────────────┬────────────────────────┘
                       │ File Descriptor
                       ▼
┌───────────────────────────────────────────────┐
│     cerberus@.service (Sandboxed Process)     │
│  ┌─────────────────────────────────────────┐  │
│  │ asyncio Server (Engine)                 │  │
│  ├─────────────────────────────────────────┤  │
│  │ Rate Limiting & Queue (Backpressure)    │  │
│  ├─────────────────────────────────────────┤  │
│  │ Pydantic V2 Validation                  │  │
│  └───────┬─────────────────────────┬───────┘  │
└──────────┼─────────────────────────┼──────────┘
           │ (Valid Data)            │ (Attack / Anomaly)
           ▼                         ▼
┌──────────────────────┐   ┌────────────────────┐
│ TimescaleDB / asyncpg│   │ nftables (Kernel)  │
│ (Hypertables Storage)│   │ (IP Auto-Ban)      │
└──────────────────────┘   └────────────────────┘
