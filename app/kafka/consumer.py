import asyncio
import json
from typing import Optional

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.kafka.event_router import route_event
from app.schemas.trip import KafkaEvent

_consumer: Optional[AIOKafkaConsumer] = None


class TripKafkaConsumer:
    def __init__(self):
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._consumer = AIOKafkaConsumer(
            settings.KAFKA_TOPIC_WARNING_CREATED,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_GROUP_ID,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        print(
            f"Kafka consumer started. "
            f"Subscribed to: {settings.KAFKA_TOPIC_WARNING_CREATED}"
        )
        self._task = asyncio.create_task(self._consume_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()
            print("Kafka consumer stopped.")

    async def _consume_loop(self):
        async for msg in self._consumer:
            await self.process_message(msg.value)

    async def process_message(self, raw_message: bytes):
        try:
            decoded = raw_message.decode()
            print(f"RAW MESSAGE: {decoded}")

            payload = json.loads(decoded)

            # The outer envelope contains event_type + payload,
            # or the message itself is the payload for WarningCreated.
            event_type = payload.get("event_type", "WarningCreated")
            inner_payload = payload.get("payload", payload)

            event = KafkaEvent(
                event_type=event_type,
                payload=inner_payload,
            )

            print(f"Processing event: {event.event_type}")
            await route_event(event)
            print("Event processed successfully")

        except json.JSONDecodeError as exc:
            print(f"Invalid JSON message: {exc}")

        except Exception as exc:
            print(f"Failed to process message: {exc}")


trip_consumer = TripKafkaConsumer()