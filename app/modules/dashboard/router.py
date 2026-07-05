from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.domain.enums import UserRole
from app.modules.dashboard.service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def get_dashboard_service(pool=Depends(db_pool)) -> DashboardService:
    return DashboardService(pool)


@router.get("")
async def role_dashboard(
    user: CurrentUser = Depends(get_current_user),
    svc: DashboardService = Depends(get_dashboard_service),
):
    if user.role == UserRole.ADMIN:
        return await svc.admin_dashboard(user_id=user.id)
    if user.role == UserRole.AGENT:
        return await svc.agent_dashboard(user_id=user.id)
    return await svc.client_dashboard(user_id=user.id)


@router.get("/companies/{company_id}")
async def company_dashboard(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: DashboardService = Depends(get_dashboard_service),
):
    return await svc.company_dashboard(
        company_id=company_id, user_id=user.id, role=user.role
    )


@router.get("/renewals")
async def upcoming_renewals(
    days: int = Query(default=90, ge=1, le=365),
    company_id: UUID | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    svc: DashboardService = Depends(get_dashboard_service),
):
    return await svc.upcoming_renewals(
        user_id=user.id,
        role=user.role,
        days=days,
        company_id=company_id,
    )
