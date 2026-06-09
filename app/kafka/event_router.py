import uuid

from app.config import settings
from app.kafka.producer import publish_event
from app.schemas.trip import KafkaEvent, WarningCreatedPayload


async def route_event(event: KafkaEvent):
    handlers = {
        "WarningCreated": handle_warning_created,
    }

    handler = handlers.get(event.event_type)
    if handler is None:
        print(f"No handler registered for event type: {event.event_type}")
        return

    await handler(event.payload)


async def handle_warning_created(payload: dict):
    """
    When a warning is created for an area, find all active/planned trips
    in that area and emit TripWarningNotificationRequired for each.
    """
    print(f"Handling WarningCreated: {payload}")

    try:
        warning_payload = WarningCreatedPayload(
            warning_id=uuid.UUID(payload["warning_id"]),
            area_id=uuid.UUID(payload["area_id"]),
            message=payload.get("message", ""),
            severity=payload.get("severity", "UNKNOWN"),
        )
    except (KeyError, ValueError) as exc:
        print(f"Malformed WarningCreated payload: {exc}")
        return

    # Import here to avoid circular imports
    from app.db.database import AsyncSessionLocal
    from app.services.trip_service import TripService

    async with AsyncSessionLocal() as session:
        service = TripService(session)
        trips = await service.get_trips_by_area(warning_payload.area_id)

    for trip in trips:
        await publish_event(
            topic=settings.KAFKA_TOPIC_TRIP_WARNING_NOTIFICATION,
            event_type="TripWarningNotificationRequired",
            payload={
                "trip_id": str(trip.id),
                "trip_name": trip.name,
                "area_id": str(warning_payload.area_id),
                "warning_id": str(warning_payload.warning_id),
                "warning_message": warning_payload.message,
                "warning_severity": warning_payload.severity,
                "organizer_id": str(trip.organizer_id),
                "participant_ids": [
                    str(p.tourist_id) for p in trip.participants
                ],
            },
        )
        print(f"Emitted TripWarningNotificationRequired for trip {trip.id}")