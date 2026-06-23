import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.trip import TripStatus, ParticipantStatus


# ── Shared sub-schemas ────────────────────────────────────────────────────────

class RoutePoint(BaseModel):
    """A single coordinate on the trip route."""
    order: int = Field(..., ge=0, description="0-based position in the route")
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)
    label: Optional[str] = Field(None, max_length=255)


# ── Trip CRUD schemas ─────────────────────────────────────────────────────────

class TripCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    start_date: datetime
    end_date: datetime
    # At least one coordinate is required so the trip has a meaningful location.
    route: list[RoutePoint] = Field(..., min_length=1)


class PatchTripMetadata(BaseModel):
    """Non-geometric trip fields that can be changed without re-resolving the route."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class PatchTripRoute(BaseModel):
    """Replaces the entire route with a new ordered list of coordinates.

    The API gateway is responsible for resolving raw location points via
    MapGateway before calling this endpoint, so the service only stores the
    already-resolved coordinates.
    """
    route: list[RoutePoint] = Field(..., min_length=1)


# ── Participant schemas ───────────────────────────────────────────────────────

class InviteParticipant(BaseModel):
    tourist_id: uuid.UUID
    email: str


class ParticipantStatusUpdate(BaseModel):
    """Used by a tourist to accept or reject their invitation."""
    status: ParticipantStatus


# ── Response schemas ──────────────────────────────────────────────────────────

class ParticipantResponse(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID
    tourist_id: uuid.UUID
    status: ParticipantStatus
    is_organizer: bool
    invited_at: datetime
    joined_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TripResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    organizer_id: uuid.UUID
    status: TripStatus
    start_date: datetime
    end_date: datetime
    route: list[RoutePoint] = []
    created_at: datetime
    updated_at: datetime
    participants: list[ParticipantResponse] = []

    model_config = {"from_attributes": True}


# ── Kafka event schemas ───────────────────────────────────────────────────────

class KafkaEvent(BaseModel):
    event_type: str
    payload: dict


class WarningCreatedPayload(BaseModel):
    warning_id: uuid.UUID
    area_id: uuid.UUID
    message: str
    severity: str