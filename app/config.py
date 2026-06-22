from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/trip_service"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_GROUP_ID: str = "trip-service-group"

    # Topics consumed
    KAFKA_TOPIC_WARNING_CREATED: str = "warning.created"

    # Topics produced
    KAFKA_TOPIC_TRIP_WARNING_NOTIFICATION: str = "trip.warning.notification.required"
    KAFKA_TOPIC_PARTICIPANT_INVITED: str = "trip.participant.invited"
    KAFKA_TOPIC_TRIP_ORGANIZER_ASSIGNED: str = "trip.organizer.assigned"
    KAFKA_TOPIC_TRIP_CANCELLED: str = "trip.cancelled"

    # JWT
    JWT_SECRET: str = "secret"
    JWT_ALGORITHM: str = "HS256"

    DISABLE_AUTH: bool = False

    class Config:
        env_file = ".env"


settings = Settings()