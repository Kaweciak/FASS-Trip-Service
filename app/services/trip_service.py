import uuid
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.kafka.producer import publish_event
from app.models.trip import Trip, TripParticipant, TripStatus, ParticipantStatus
from app.schemas.trip import TripCreate, PatchTripMetadata, PatchTripRoute, InviteParticipant


# ── Domain errors ─────────────────────────────────────────────────────────────

class TripNotFoundError(Exception):
    pass


class TripAccessDeniedError(Exception):
    pass


class TripCapacityError(Exception):
    pass


class TripStateError(Exception):
    pass


# ── Service ───────────────────────────────────────────────────────────────────

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

    async def get_trips_for_tourist(self, tourist_id: uuid.UUID) -> list[Trip]:
        result = await self.session.execute(
            select(Trip)
            .options(selectinload(Trip.participants))
            .join(TripParticipant, TripParticipant.trip_id == Trip.id)
            .where(TripParticipant.tourist_id == tourist_id)
        )
        return list(result.scalars().all())

    # ── Trip lifecycle ────────────────────────────────────────────────────────

    async def create_trip(
        self, data: TripCreate, organizer_id: uuid.UUID
    ) -> Trip:
        """
        Creates a new trip in DRAFT status. The organizer is automatically
        added as an accepted participant.
        Emits: TripOrganizerAssigned
        """
        route_data = [point.model_dump() for point in data.route]

        trip = Trip(
            name=data.name,
            description=data.description,
            organizer_id=organizer_id,
            start_date=data.start_date,
            end_date=data.end_date,
            route=route_data,
            status=TripStatus.DRAFT,
        )
        self.session.add(trip)
        await self.session.flush()

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
                "start_date": trip.start_date.isoformat(),
                "end_date": trip.end_date.isoformat(),
            },
        )

        return trip

    async def patch_trip_metadata(
        self,
        trip_id: uuid.UUID,
        data: PatchTripMetadata,
        requester_id: uuid.UUID,
    ) -> Trip:
        """
        Updates non-geometric trip fields (name, description, dates).
        Allowed in DRAFT or ACTIVE status.
        Corresponds to: PatchTripMetadata in the route/metadata update sequence.
        Emits: TripUpdated
        """
        trip = await self.get_trip_by_id(trip_id)
        self._assert_organizer(trip, requester_id)
        self._assert_modifiable(trip)

        for field, value in data.model_dump(exclude_none=True).items():
            setattr(trip, field, value)

        await self.session.commit()
        await self.session.refresh(trip)
        return trip

    async def patch_trip_route(
        self,
        trip_id: uuid.UUID,
        data: PatchTripRoute,
        requester_id: uuid.UUID,
    ) -> Trip:
        """
        Replaces the full route with a new list of resolved coordinates.
        Allowed in DRAFT or ACTIVE status.
        Corresponds to: PatchTripRoute in the route/metadata update sequence.
        Emits: TripRouteUpdated
        """
        trip = await self.get_trip_by_id(trip_id)
        self._assert_organizer(trip, requester_id)
        self._assert_modifiable(trip)

        trip.route = [point.model_dump() for point in data.route]

        await self.session.commit()
        await self.session.refresh(trip)

        await publish_event(
            topic=settings.KAFKA_TOPIC_TRIP_ROUTE_UPDATED,
            event_type="TripRouteUpdated",
            payload={
                "trip_id": str(trip.id),
                "trip_name": trip.name,
                "organizer_id": str(trip.organizer_id),
                "route": trip.route,
            },
        )

        return trip

    async def cancel_trip(
        self, trip_id: uuid.UUID, requester_id: uuid.UUID
    ) -> Trip:
        """
        Cancels a trip. Only the organizer may cancel.
        Emits: TripCancelled
        """
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
            },
        )

        return trip

    async def start_trip(self, trip_id: uuid.UUID) -> Trip:
        """
        Triggered by the scheduler when the trip's start_date arrives.
        Transitions: DRAFT/PLANNED → ACTIVE
        Corresponds to: StartTripScheduleTriggered
        """
        trip = await self.get_trip_by_id(trip_id)
        if trip.status not in (TripStatus.DRAFT, TripStatus.PLANNED):
            raise TripStateError(
                f"Trip cannot be started from status '{trip.status}'"
            )

        trip.status = TripStatus.ACTIVE
        await self.session.commit()
        await self.session.refresh(trip)
        return trip

    async def complete_trip(self, trip_id: uuid.UUID) -> Trip:
        """
        Triggered by the scheduler when the trip's end_date passes.
        Transitions: ACTIVE → COMPLETED
        Corresponds to: CompleteTripScheduleTriggered
        """
        trip = await self.get_trip_by_id(trip_id)
        if trip.status != TripStatus.ACTIVE:
            raise TripStateError(
                f"Trip cannot be completed from status '{trip.status}'"
            )

        trip.status = TripStatus.COMPLETED
        await self.session.commit()
        await self.session.refresh(trip)
        return trip

    # ── Participant management ────────────────────────────────────────────────

    async def invite_participant(
        self,
        trip_id: uuid.UUID,
        data: InviteParticipant,
        requester_id: uuid.UUID,
    ) -> TripParticipant:
        """
        Invites a tourist to the trip. Only the organizer may invite.
        Allowed in DRAFT or ACTIVE status.
        Emits: ParticipantInvited
        """
        trip = await self.get_trip_by_id(trip_id)
        self._assert_organizer(trip, requester_id)
        self._assert_modifiable(trip)

        already_present = any(
            p.tourist_id == data.tourist_id for p in trip.participants
        )
        if already_present:
            raise TripStateError("Tourist is already a participant or has been invited")

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
        """
        A tourist accepts (AcceptInvitation) or rejects (RejectInvitation)
        their pending invitation.
        """
        trip = await self.get_trip_by_id(trip_id)
        self._assert_not_cancelled(trip)

        participant = next(
            (p for p in trip.participants if p.tourist_id == tourist_id), None
        )
        if participant is None:
            raise TripNotFoundError("Participant not found in this trip")
        if participant.status != ParticipantStatus.INVITED:
            raise TripStateError("Invitation has already been responded to")

        if accept:
            participant.status = ParticipantStatus.ACCEPTED
            participant.joined_at = datetime.now(timezone.utc)
        else:
            participant.status = ParticipantStatus.REJECTED

        await self.session.commit()
        await self.session.refresh(participant)
        return participant

    async def leave_trip(
        self,
        trip_id: uuid.UUID,
        requester_id: uuid.UUID,
    ) -> TripParticipant:
        """
        A participant voluntarily leaves the trip (LeaveTrip).
        The organizer is not allowed to leave — they must cancel the trip instead.
        Emits: TripParticipantLeft
        """
        trip = await self.get_trip_by_id(trip_id)
        self._assert_not_cancelled(trip)

        participant = next(
            (p for p in trip.participants if p.tourist_id == requester_id), None
        )
        if participant is None:
            raise TripNotFoundError("You are not a participant of this trip")

        # Sequence diagram: organizer cannot leave
        if participant.is_organizer:
            raise TripAccessDeniedError(
                "The organizer cannot leave the trip. Cancel the trip instead."
            )

        await self.session.delete(participant)
        await self.session.commit()

        await publish_event(
            topic=settings.KAFKA_TOPIC_TRIP_PARTICIPANT_LEFT,
            event_type="TripParticipantLeft",
            payload={
                "trip_id": str(trip.id),
                "trip_name": trip.name,
                "tourist_id": str(requester_id),
                "organizer_id": str(trip.organizer_id),
            },
        )

        return participant

    # ── Guards ────────────────────────────────────────────────────────────────

    def _assert_organizer(self, trip: Trip, requester_id: uuid.UUID):
        if trip.organizer_id != requester_id:
            raise TripAccessDeniedError(
                "Only the trip organizer can perform this action"
            )

    def _assert_not_cancelled(self, trip: Trip):
        if trip.status == TripStatus.CANCELLED:
            raise TripStateError("Trip is already cancelled")

    def _assert_modifiable(self, trip: Trip):
        """Route and participant changes are allowed in DRAFT or ACTIVE status."""
        if trip.status not in (TripStatus.DRAFT, TripStatus.ACTIVE):
            raise TripStateError(
                f"Trip modifications are not allowed in status '{trip.status}'"
            )