import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from aiokafka import AIOKafkaProducer

from app.config import settings

_producer: Optional[AIOKafkaProducer] = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await _producer.start()
    return _producer


async def stop_producer():
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def publish_event(topic: str, event_type: str, payload: dict, user_email: Optional[str] = None):
    producer = await get_producer()
    message = {
        "event_type": event_type,
        "user_email": user_email,
        "payload": payload,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "event_id": str(uuid.uuid4()),
    }
    await producer.send_and_wait(topic, message)
    print(f"Published event '{event_type}' to topic '{topic}'")