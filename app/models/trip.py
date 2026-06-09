import uuid
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Text, DateTime, ForeignKey, Enum as SAEnum, Boolean
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.database import Base


class TripStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ParticipantStatus(str, enum.Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    area_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organizer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[TripStatus] = mapped_column(
        SAEnum(TripStatus), default=TripStatus.PLANNED, nullable=False
    )
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_participants: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    participants: Mapped[list["TripParticipant"]] = relationship(
        "TripParticipant", back_populates="trip", cascade="all, delete-orphan"
    )


class TripParticipant(Base):
    __tablename__ = "trip_participants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    tourist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[ParticipantStatus] = mapped_column(
        SAEnum(ParticipantStatus), default=ParticipantStatus.INVITED, nullable=False
    )
    is_organizer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    trip: Mapped["Trip"] = relationship("Trip", back_populates="participants")