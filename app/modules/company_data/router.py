from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.modules.company_data.service import CompanyDataService

router = APIRouter(prefix="/companies", tags=["Company Data"])


class UpdateCompanyDataBody(BaseModel):
    data: dict = Field(default_factory=dict)


def get_company_data_service(pool: asyncpg.Pool = Depends(db_pool)) -> CompanyDataService:
    return CompanyDataService(pool)


@router.get("/{company_id}/data")
async def get_company_data(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: CompanyDataService = Depends(get_company_data_service),
):
    return await svc.get_company_data(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
    )


@router.put("/{company_id}/data")
async def update_company_data(
    company_id: UUID,
    body: UpdateCompanyDataBody,
    user: CurrentUser = Depends(get_current_user),
    svc: CompanyDataService = Depends(get_company_data_service),
):
    return await svc.update_company_data(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        payload=body.data,
    )
