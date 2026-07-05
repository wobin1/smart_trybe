from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.domain.enums import ComplianceMode, ComplianceType
from app.modules.cart.service import CartService

router = APIRouter(prefix="/cart", tags=["Compliance Cart"])


class AddCartItemBody(BaseModel):
    compliance_type: ComplianceType
    mode: ComplianceMode


class ConfirmPaymentBody(BaseModel):
    payment_id: UUID
    payment_reference: str = Field(..., min_length=1)
    start_workflows: bool = True


class InitializePaymentBody(BaseModel):
    payment_id: UUID


def get_cart_service(pool=Depends(db_pool)) -> CartService:
    return CartService(pool)


@router.get("/companies/{company_id}")
async def get_company_cart(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    return await svc.get_cart(company_id=company_id, user_id=user.id, role=user.role)


@router.post("/companies/{company_id}/items", status_code=201)
async def add_cart_item(
    company_id: UUID,
    body: AddCartItemBody,
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    return await svc.add_item(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        compliance_type=body.compliance_type,
        mode=body.mode,
    )


@router.delete("/companies/{company_id}/items/{item_id}")
async def remove_cart_item(
    company_id: UUID,
    item_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    return await svc.remove_item(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        item_id=item_id,
    )


@router.post("/companies/{company_id}/checkout")
async def checkout_cart(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    return await svc.checkout(company_id=company_id, user_id=user.id, role=user.role)


@router.post("/companies/{company_id}/initialize-payment")
async def initialize_payment(
    company_id: UUID,
    body: InitializePaymentBody,
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    return await svc.initialize_payment(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        payment_id=body.payment_id,
    )


@router.post("/companies/{company_id}/pay")
async def confirm_cart_payment(
    company_id: UUID,
    body: ConfirmPaymentBody,
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    return await svc.confirm_payment(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        payment_id=body.payment_id,
        payment_reference=body.payment_reference,
        start_workflows=body.start_workflows,
    )
