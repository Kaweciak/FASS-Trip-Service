from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.database import init_db
from app.kafka.consumer import trip_consumer
from app.routers import trips


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await trip_consumer.start()

    yield

    # Shutdown
    await trip_consumer.stop()

    from app.kafka.producer import stop_producer
    await stop_producer()


app = FastAPI(
    title="Trip Service",
    description="Planowanie wycieczek i zarządzanie uczestnikami.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(trips.router)

@app.get("/health")
async def health():
    return {"status": "ok"}