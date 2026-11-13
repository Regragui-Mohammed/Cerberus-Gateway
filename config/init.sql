-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create base telemetry table 
CREATE TABLE IF NOT EXISTS telemetry (
    timestamp TIMESTAMPTZ NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    device_id VARCHAR(64) NOT NULL,
    temperature DOUBLE PRECISION NOT NULL,
    pressure DOUBLE PRECISION NOT NULL,
    status VARCHAR(16) NOT NULL
);

SELECT create_hypertable('telemetry', 'timestamp', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_telemetry_lookup 
ON telemetry (tenant_id, device_id, timestamp DESC);

-- Create security and DLQ events table for Grafana security observability
CREATE TABLE IF NOT EXISTS security_events (
    timestamp TIMESTAMPTZ NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    client_ip VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    raw_payload TEXT NOT NULL
);
