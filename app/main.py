from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.database import close_pool, create_pool
from app.db.bootstrap import bootstrap_database
from app.modules.auth.router import router as auth_router
from app.modules.bpp_federal.router import router as bpp_federal_router
from app.modules.bpp_state.router import router as bpp_state_router
from app.modules.cac.router import router as cac_router
from app.modules.documents.router import router as documents_router
from app.modules.workflow.router import router as workflow_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await create_pool()
    await bootstrap_database(pool)
    yield
    await close_pool()


app = FastAPI(title="Smart Trybe Compliance System", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api/v1")
app.include_router(cac_router, prefix="/api/v1")
app.include_router(bpp_federal_router, prefix="/api/v1")
app.include_router(bpp_state_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")


def _ensure_upload_dir() -> None:
    from pathlib import Path

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)


_ensure_upload_dir()
