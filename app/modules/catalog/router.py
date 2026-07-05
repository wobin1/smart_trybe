from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.modules.catalog.service import CatalogService

router = APIRouter(prefix="/catalog", tags=["Compliance Catalog"])


def get_catalog_service(pool=Depends(db_pool)) -> CatalogService:
    return CatalogService(pool)


@router.get("/categories")
async def list_categories(
    user: CurrentUser = Depends(get_current_user),
    svc: CatalogService = Depends(get_catalog_service),
):
    return {"categories": await svc.list_categories()}


@router.get("/items")
async def list_catalog_items(
    category: str | None = Query(default="all", description="Category slug or 'all'"),
    user: CurrentUser = Depends(get_current_user),
    svc: CatalogService = Depends(get_catalog_service),
):
    return await svc.list_items(category=category)


@router.get("/items/{compliance_type}/{mode}")
async def get_catalog_item(
    compliance_type: str,
    mode: str,
    user: CurrentUser = Depends(get_current_user),
    svc: CatalogService = Depends(get_catalog_service),
):
    return await svc.get_item(compliance_type, mode)
