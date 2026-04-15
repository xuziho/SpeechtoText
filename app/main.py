from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import get_worker
from app.api.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = get_worker()
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()


app = FastAPI(title="Speech to Text Service", lifespan=lifespan)
app.include_router(router)
