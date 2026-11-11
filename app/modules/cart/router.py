from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.domain.enums import ComplianceMode, ComplianceType, UserRole
from app.modules.cart.service import CartService

router = APIRouter(prefix="/cart", tags=["Compliance Cart"])


class AddCartItemBody(BaseModel):
    compliance_type: ComplianceType
    mode: ComplianceMode


class ConfirmPaymentBody(BaseModel):
    payment_id: UUID
    # Accepted for backward compatibility but ignored: the server always
    # generates its own reference for manual/dev-mode confirmations (PF-2).
    payment_reference: str | None = Field(None, min_length=1)
    start_workflows: bool = True


class InitializePaymentBody(BaseModel):
    payment_id: UUID


class ConfirmAllPaymentsBody(BaseModel):
    start_workflows: bool = True


def get_cart_service(pool=Depends(db_pool)) -> CartService:
    return CartService(pool)


@router.get("/mine")
async def get_my_carts(
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    """All pending (OPEN/CHECKOUT) carts across every company the client
    owns — backs the global cart icon so a finished-but-unpaid compliance
    is visible from anywhere in the app, not just its own workflow page."""
    if user.role != UserRole.CLIENT:
        return {"carts": [], "total_items": 0, "total_ngn": 0}
    return await svc.get_my_carts(user_id=user.id)


@router.post("/mine/checkout")
async def checkout_all_carts(
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    """Check out every OPEN cart across all of the client's companies at
    once — first step of a "Pay All" action from the global cart page."""
    return await svc.checkout_all(user_id=user.id, role=user.role)


@router.post("/mine/initialize-payment")
async def initialize_all_payments(
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    """One combined Paystack charge for every pending payment across all of
    the client's companies."""
    return await svc.initialize_all_payments(user_id=user.id, role=user.role)


@router.post("/mine/pay")
async def confirm_all_payments(
    body: ConfirmAllPaymentsBody = ConfirmAllPaymentsBody(),
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    """Dev/manual confirmation for a combined "pay all" charge."""
    return await svc.confirm_all_payments(
        user_id=user.id, role=user.role, start_workflows=body.start_workflows
    )


@router.get("/payments/status")
async def get_payment_status(
    reference: str = Query(..., min_length=1),
    user: CurrentUser = Depends(get_current_user),
    svc: CartService = Depends(get_cart_service),
):
    """Look up a Paystack payment (single or combined "pay all" batch) by its
    reference — used by the /payments/callback page while the webhook may
    still be in flight."""
    return await svc.get_payment_status(user_id=user.id, reference=reference)


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
