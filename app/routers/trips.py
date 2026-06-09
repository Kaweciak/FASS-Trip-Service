import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user_id
from app.db.database import get_db, AsyncSession
from app.schemas.trip import (
    TripCreate,
    TripUpdate,
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


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TripResponse])
async def list_my_trips(current_user: CurrentUser, db: DB):
    """List all trips the authenticated tourist is part of."""
    service = _service(db)
    return await service.get_trips_for_tourist(current_user)


@router.post("", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def create_trip(body: TripCreate, current_user: CurrentUser, db: DB):
    """Create a new trip. The caller becomes the organizer."""
    service = _service(db)
    return await service.create_trip(body, organizer_id=current_user)


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(trip_id: uuid.UUID, current_user: CurrentUser, db: DB):
    service = _service(db)
    try:
        return await service.get_trip_by_id(trip_id)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/{trip_id}", response_model=TripResponse)
async def update_trip(
    trip_id: uuid.UUID, body: TripUpdate, current_user: CurrentUser, db: DB
):
    service = _service(db)
    try:
        return await service.update_trip(trip_id, body, requester_id=current_user)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except TripStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.delete("/{trip_id}", response_model=TripResponse)
async def cancel_trip(trip_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Cancel a trip (organizer only). Emits TripCancelled event."""
    service = _service(db)
    try:
        return await service.cancel_trip(trip_id, requester_id=current_user)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
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
    """Invite a tourist to the trip. Emits ParticipantInvited event."""
    service = _service(db)
    try:
        return await service.invite_participant(trip_id, body, requester_id=current_user)
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TripAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (TripCapacityError, TripStateError) as exc:
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
    """Accept or reject a trip invitation."""
    from app.models.trip import ParticipantStatus
    if body.status not in (ParticipantStatus.ACCEPTED, ParticipantStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be ACCEPTED or REJECTED",
        )
    service = _service(db)
    try:
        return await service.respond_to_invitation(
            trip_id,
            tourist_id=current_user,
            accept=(body.status == ParticipantStatus.ACCEPTED),
        )
    except TripNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (TripCapacityError, TripStateError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))