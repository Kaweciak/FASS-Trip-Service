import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.trip import TripStatus, ParticipantStatus


# ── Trip schemas ──────────────────────────────────────────────────────────────

class TripCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    area_id: uuid.UUID
    start_date: datetime
    end_date: datetime
    max_participants: Optional[int] = Field(None, gt=0)


class TripUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    max_participants: Optional[int] = Field(None, gt=0)


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
    area_id: uuid.UUID
    organizer_id: uuid.UUID
    status: TripStatus
    start_date: datetime
    end_date: datetime
    max_participants: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    participants: list[ParticipantResponse] = []

    model_config = {"from_attributes": True}


# ── Participant schemas ───────────────────────────────────────────────────────

class InviteParticipant(BaseModel):
    tourist_id: uuid.UUID


class ParticipantStatusUpdate(BaseModel):
    status: ParticipantStatus


# ── Kafka event schemas ───────────────────────────────────────────────────────

class KafkaEvent(BaseModel):
    event_type: str
    payload: dict


class WarningCreatedPayload(BaseModel):
    warning_id: uuid.UUID
    area_id: uuid.UUID
    message: str
    severity: str