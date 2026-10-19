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
