import uuid
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.kafka.producer import publish_event
from app.models.trip import Trip, TripParticipant, TripStatus, ParticipantStatus
from app.schemas.trip import TripCreate, TripUpdate, InviteParticipant


class TripNotFoundError(Exception):
    pass


class TripAccessDeniedError(Exception):
    pass


class TripCapacityError(Exception):
    pass


class TripStateError(Exception):
    pass


class TripService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_trip_by_id(self, trip_id: uuid.UUID) -> Trip:
        result = await self.session.execute(
            select(Trip)
            .options(selectinload(Trip.participants))
            .where(Trip.id == trip_id)
        )
        trip = result.scalar_one_or_none()
        if trip is None:
            raise TripNotFoundError(f"Trip {trip_id} not found")
        return trip

    async def get_trips_by_area(self, area_id: uuid.UUID) -> list[Trip]:
        result = await self.session.execute(
            select(Trip)
            .options(selectinload(Trip.participants))
            .where(
                and_(
                    Trip.area_id == area_id,
                    Trip.status.in_([TripStatus.PLANNED, TripStatus.ACTIVE]),
                )
            )
        )
        return list(result.scalars().all())

    async def get_trips_for_tourist(self, tourist_id: uuid.UUID) -> list[Trip]:
        result = await self.session.execute(
            select(Trip)
            .options(selectinload(Trip.participants))
            .join(TripParticipant, TripParticipant.trip_id == Trip.id)
            .where(TripParticipant.tourist_id == tourist_id)
        )
        return list(result.scalars().all())

    # ── Commands ──────────────────────────────────────────────────────────────

    async def create_trip(
        self, data: TripCreate, organizer_id: uuid.UUID
    ) -> Trip:
        trip = Trip(
            name=data.name,
            description=data.description,
            area_id=data.area_id,
            organizer_id=organizer_id,
            start_date=data.start_date,
            end_date=data.end_date,
            max_participants=data.max_participants,
            status=TripStatus.PLANNED,
        )
        self.session.add(trip)
        await self.session.flush()

        # Organizer is also a participant
        organizer_participant = TripParticipant(
            trip_id=trip.id,
            tourist_id=organizer_id,
            status=ParticipantStatus.ACCEPTED,
            is_organizer=True,
            joined_at=datetime.now(timezone.utc),
        )
        self.session.add(organizer_participant)
        await self.session.commit()
        await self.session.refresh(trip)

        await publish_event(
            topic=settings.KAFKA_TOPIC_TRIP_ORGANIZER_ASSIGNED,
            event_type="TripOrganizerAssigned",
            payload={
                "trip_id": str(trip.id),
                "trip_name": trip.name,
                "organizer_id": str(organizer_id),
                "area_id": str(trip.area_id),
                "start_date": trip.start_date.isoformat(),
                "end_date": trip.end_date.isoformat(),
            },
        )

        return trip

    async def update_trip(
        self,
        trip_id: uuid.UUID,
        data: TripUpdate,
        requester_id: uuid.UUID,
    ) -> Trip:
        trip = await self.get_trip_by_id(trip_id)
        self._assert_organizer(trip, requester_id)
        self._assert_not_cancelled(trip)

        for field, value in data.model_dump(exclude_none=True).items():
            setattr(trip, field, value)

        await self.session.commit()
        await self.session.refresh(trip)
        return trip

    async def cancel_trip(
        self, trip_id: uuid.UUID, requester_id: uuid.UUID
    ) -> Trip:
        trip = await self.get_trip_by_id(trip_id)
        self._assert_organizer(trip, requester_id)
        self._assert_not_cancelled(trip)

        trip.status = TripStatus.CANCELLED
        await self.session.commit()
        await self.session.refresh(trip)

        await publish_event(
            topic=settings.KAFKA_TOPIC_TRIP_CANCELLED,
            event_type="TripCancelled",
            payload={
                "trip_id": str(trip.id),
                "trip_name": trip.name,
                "organizer_id": str(trip.organizer_id),
                "participant_ids": [str(p.tourist_id) for p in trip.participants],
                "area_id": str(trip.area_id),
            },
        )

        return trip

    async def invite_participant(
        self,
        trip_id: uuid.UUID,
        data: InviteParticipant,
        requester_id: uuid.UUID,
    ) -> TripParticipant:
        trip = await self.get_trip_by_id(trip_id)
        self._assert_organizer(trip, requester_id)
        self._assert_not_cancelled(trip)

        if trip.max_participants is not None:
            accepted_count = sum(
                1 for p in trip.participants
                if p.status == ParticipantStatus.ACCEPTED
            )
            if accepted_count >= trip.max_participants:
                raise TripCapacityError("Trip has reached maximum participants")

        already_invited = any(
            p.tourist_id == data.tourist_id for p in trip.participants
        )
        if already_invited:
            raise TripStateError("Tourist is already a participant or invited")

        participant = TripParticipant(
            trip_id=trip_id,
            tourist_id=data.tourist_id,
            status=ParticipantStatus.INVITED,
            is_organizer=False,
        )
        self.session.add(participant)
        await self.session.commit()
        await self.session.refresh(participant)

        await publish_event(
            topic=settings.KAFKA_TOPIC_PARTICIPANT_INVITED,
            event_type="ParticipantInvited",
            payload={
                "trip_id": str(trip_id),
                "trip_name": trip.name,
                "tourist_id": str(data.tourist_id),
                "organizer_id": str(trip.organizer_id),
                "start_date": trip.start_date.isoformat(),
                "end_date": trip.end_date.isoformat(),
            },
        )

        return participant

    async def respond_to_invitation(
        self,
        trip_id: uuid.UUID,
        tourist_id: uuid.UUID,
        accept: bool,
    ) -> TripParticipant:
        trip = await self.get_trip_by_id(trip_id)
        self._assert_not_cancelled(trip)

        participant = next(
            (p for p in trip.participants if p.tourist_id == tourist_id), None
        )
        if participant is None:
            raise TripNotFoundError("Participant not found in this trip")
        if participant.status != ParticipantStatus.INVITED:
            raise TripStateError("Invitation already responded to")

        if accept:
            if trip.max_participants is not None:
                accepted_count = sum(
                    1 for p in trip.participants
                    if p.status == ParticipantStatus.ACCEPTED
                )
                if accepted_count >= trip.max_participants:
                    raise TripCapacityError("Trip is already full")
            participant.status = ParticipantStatus.ACCEPTED
            participant.joined_at = datetime.now(timezone.utc)
        else:
            participant.status = ParticipantStatus.REJECTED

        await self.session.commit()
        await self.session.refresh(participant)
        return participant

    # ── Guards ────────────────────────────────────────────────────────────────

    def _assert_organizer(self, trip: Trip, requester_id: uuid.UUID):
        if trip.organizer_id != requester_id:
            raise TripAccessDeniedError("Only the trip organizer can perform this action")

    def _assert_not_cancelled(self, trip: Trip):
        if trip.status == TripStatus.CANCELLED:
            raise TripStateError("Trip is already cancelled")