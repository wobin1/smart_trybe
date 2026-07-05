from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.database import close_pool, create_pool
from app.db.bootstrap import bootstrap_database
from app.modules.admin.router import router as admin_router
from app.modules.agent.router import router as agent_router
from app.modules.auth.router import router as auth_router
from app.modules.bpp_federal.router import router as bpp_federal_router
from app.modules.bpp_state.router import router as bpp_state_router
from app.modules.cac.router import router as cac_router
from app.modules.cart.router import router as cart_router
from app.modules.catalog.router import router as catalog_router
from app.modules.company_data.router import router as company_data_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.documents.router import router as documents_router
from app.modules.webhooks.router import router as webhooks_router
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
app.include_router(catalog_router, prefix="/api/v1")
app.include_router(cart_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(bpp_federal_router, prefix="/api/v1")
app.include_router(bpp_state_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(company_data_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
