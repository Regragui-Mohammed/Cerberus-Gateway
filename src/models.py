from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TelemetryPayload(BaseModel):
    """
    Strict telemetry schema for incoming IoT sensor readings.
    Rejects implicit type coercion and unknown attributes.
    """
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
    )

    device_id: str = Field(
        ...,
        description="Unique sensor identifier (e.g., SENSOR-001)",
        min_length=3,
        max_length=64,
    )
    timestamp: datetime = Field(
        ...,
        description="UTC timestamp of the telemetry reading",
    )
    temperature: float = Field(
        ...,
        ge=-50.0,
        le=150.0,
        description="Temperature reading in Celsius",
    )
    pressure: float = Field(
        ...,
        ge=300.0,
        le=1100.0,
        description="Atmospheric pressure reading in hPa",
    )
    status: Literal["OK", "WARNING", "CRITICAL"] = Field(
        default="OK",
        description="Operating status flag",
    )

    @field_validator("device_id")
    @classmethod
    def validate_device_id_format(cls, value: str) -> str:
        if not value.replace("-", "").isalnum():
            raise ValueError("device_id must only contain alphanumeric characters and hyphens")
        return value
