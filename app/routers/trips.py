import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user_id
from app.db.database import get_db, AsyncSession
from app.schemas.trip import (
    TripCreate,
    PatchTripMetadata,
    PatchTripRoute,
    TripResponse,
    ParticipantResponse,
    InviteParticipant,
    ParticipantStatusUpdate,
)
from app.services.trip_service import (
    TripService,
    TripNotFoundError,
    TripAccessDeniedError,
    TripCapacityError,
    TripStateError,
)

router = APIRouter(prefix="/trips", tags=["trips"])

CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]
DB = Annotated[AsyncSession, Depends(get_db)]


def _service(db: DB) -> TripService:
    return TripService(db)


# ── Trip CRUD ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TripResponse])
async def list_my_trips(current_user: CurrentUser, db: DB):
    """List all trips the authenticated user participates in."""
    return await _service(db).get_trips_for_tourist(current_user)


@router.post("", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def create_trip(body: TripCreate, current_user: CurrentUser, db: DB):
    """Create a new trip (starts in DRAFT status). Caller becomes the organizer."""
    return await _service(db).create_trip(body, organizer_id=current_user)


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(trip_id: uuid.UUID, current_user: CurrentUser, db: DB):
    try:
        return await _service(db).get_trip_by_id(trip_id)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Route & metadata updates (sequence: UpdateTripRouteOrMetadata) ────────────

@router.patch("/{trip_id}/metadata", response_model=TripResponse)
async def patch_trip_metadata(
    trip_id: uuid.UUID, body: PatchTripMetadata, current_user: CurrentUser, db: DB
):
    """
    Update non-geometric trip fields: name, description, dates.
    Allowed in DRAFT or ACTIVE status (organizer only).
    Corresponds to PatchTripMetadata in the sequence diagram.
    """
    try:
        return await _service(db).patch_trip_metadata(
            trip_id, body, requester_id=current_user
        )
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.patch("/{trip_id}/route", response_model=TripResponse)
async def patch_trip_route(
    trip_id: uuid.UUID, body: PatchTripRoute, current_user: CurrentUser, db: DB
):
    """
    Replace the full route with a new ordered list of resolved coordinates.
    The API gateway should have already called MapGateway to resolve each
    point before forwarding to this endpoint.
    Allowed in DRAFT or ACTIVE status (organizer only).
    Corresponds to PatchTripRoute in the sequence diagram.
    """
    try:
        return await _service(db).patch_trip_route(
            trip_id, body, requester_id=current_user
        )
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Trip cancellation ─────────────────────────────────────────────────────────

@router.delete("/{trip_id}", response_model=TripResponse)
async def cancel_trip(trip_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """
    Cancel a trip (organizer only).
    Emits TripCancelled — NotificationService then notifies all participants.
    """
    try:
        return await _service(db).cancel_trip(trip_id, requester_id=current_user)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Scheduler-triggered status transitions ────────────────────────────────────

@router.post("/{trip_id}/start", response_model=TripResponse)
async def start_trip(trip_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """
    Mark a trip as ACTIVE. Called by the internal scheduler when
    start_date is reached (StartTripScheduleTriggered).
    """
    try:
        return await _service(db).start_trip(trip_id)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/{trip_id}/complete", response_model=TripResponse)
async def complete_trip(trip_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """
    Mark a trip as COMPLETED. Called by the internal scheduler when
    end_date has passed (CompleteTripScheduleTriggered).
    """
    try:
        return await _service(db).complete_trip(trip_id)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Participants ──────────────────────────────────────────────────────────────

@router.post(
    "/{trip_id}/participants",
    response_model=ParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_participant(
    trip_id: uuid.UUID, body: InviteParticipant, current_user: CurrentUser, db: DB
):
    """
    Invite a tourist to the trip (organizer only).
    Emits ParticipantInvited — NotificationService sends the invitation email.
    """
    try:
        return await _service(db).invite_participant(
            trip_id, body, requester_id=current_user
        )
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.patch(
    "/{trip_id}/participants/me",
    response_model=ParticipantResponse,
)
async def respond_to_invitation(
    trip_id: uuid.UUID,
    body: ParticipantStatusUpdate,
    current_user: CurrentUser,
    db: DB,
):
    """
    Accept (AcceptInvitation) or reject (RejectInvitation) a trip invitation.
    Called by the tourist via the Public API Gateway.
    """
    from app.models.trip import ParticipantStatus
    if body.status not in (ParticipantStatus.ACCEPTED, ParticipantStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be ACCEPTED or REJECTED",
        )
    try:
        return await _service(db).respond_to_invitation(
            trip_id,
            tourist_id=current_user,
            accept=(body.status == ParticipantStatus.ACCEPTED),
        )
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/{trip_id}/participants/me/leave",
    response_model=ParticipantResponse,
)
async def leave_trip(trip_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """
    Leave a trip voluntarily (LeaveTrip).
    The organizer cannot leave — they must cancel the trip instead.
    Emits TripParticipantLeft when a non-organizer leaves.
    Returns 403 with LeaveTripRejectedOrganizerRole detail when the organizer tries to leave.
    """
    try:
        return await _service(db).leave_trip(trip_id, requester_id=current_user)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LeaveTripRejectedOrganizerRole",
        )
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))