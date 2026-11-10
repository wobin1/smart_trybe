import json
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, UploadFile

from app.core.storage import build_upload_folder, upload_file
from app.domain.enums import ComplianceMode, ComplianceStatus, ComplianceType, UserRole
from app.modules.access.company import (
    require_company_agent,
    require_company_client,
    require_company_read,
)
from app.modules.compliance import repository as compliance_repo
from app.modules.compliance.engine import ComplianceEngine
from app.modules.cart import repository as cart_repo
from app.modules.cart.propagation import propagate_shared_step_data, sync_company_profile_from_shared
from app.modules.company_data.merge import merge_step_data
from app.modules.company_data.repository import (
    extract_shared_values,
    fetch_company_data_map,
    upsert_company_data,
)
from app.modules.entitlements import repository as entitlements_repo
from app.modules.notifications.service import NotificationService
from app.modules.workflow import definitions
from app.modules.workflow.catalog import MAKE_PAYMENT_STEP_NAME
from app.modules.workflow.step_form import build_step_form_fields
from app.modules.workflow.step_schemas import validate_step_data


def _workflow_key(compliance_type: str, mode: str) -> tuple[str, str]:
    return compliance_type, mode


def _payment_payload(entitlement: asyncpg.Record | None) -> dict:
    if entitlement is None:
        return {
            "is_paid": False,
            "payment_id": None,
            "paid_at": None,
            "consumed": False,
            "payment_reference": None,
        }
    return {
        "is_paid": True,
        "payment_id": str(entitlement["payment_id"]),
        "paid_at": entitlement["paid_at"].isoformat() if entitlement["paid_at"] else None,
        "consumed": entitlement["consumed_at"] is not None,
        "payment_reference": entitlement["payment_reference"],
    }


def _ensure_company(row: asyncpg.Record | None) -> asyncpg.Record:
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


def _ensure_workflow(row: asyncpg.Record | None) -> asyncpg.Record:
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found. Start it first.")
    return row


async def _depends_on(
    conn: asyncpg.Connection, compliance_type: ComplianceType, mode: ComplianceMode
) -> list[dict]:
    """Dependencies are always read live from the template, never from a filing's snapshot."""
    template = await definitions.load_template_definition(
        conn, compliance_type.value, mode.value, include_inactive=True
    )
    return list(template["depends_on"]) if template else []


async def _engine_prerequisites(
    conn: asyncpg.Connection,
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    company_id: UUID,
) -> list[str]:
    """Cross-compliance dependency checks (e.g. BPP needs an active FIRS TCC/PENCOM/ITF/NSITF)."""
    engine = ComplianceEngine(conn)
    missing = await engine.missing_dependencies(
        company_id, await _depends_on(conn, compliance_type, mode)
    )
    if compliance_type == ComplianceType.PENCOM and mode == ComplianceMode.RENEWAL:
        missing.extend(await engine.missing_pencom_staff_list(company_id))
    return missing


def _raise_prerequisites(missing: list[str]) -> None:
    if not missing:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "message": "Compliance prerequisites not satisfied",
            "missing_compliance": missing,
        },
    )


async def _prerequisite_status(
    conn: asyncpg.Connection,
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    company_id: UUID,
) -> list[dict]:
    """Full dependency list (not just what's missing) so the client can show it before start()."""
    missing = set(await _engine_prerequisites(conn, compliance_type, mode, company_id))
    known = await _depends_on(conn, compliance_type, mode)
    items = [
        {
            "compliance_type": dep["compliance_type"],
            "mode": dep["mode"],
            "satisfied": dep["compliance_type"] not in missing,
        }
        for dep in known
    ]
    # Requirements the engine checks that aren't a plain compliance (e.g. a specific
    # document) — surface them too rather than silently dropping them from the list.
    # There's no single (type, mode) to link to for these, so mode is null.
    known_values = {dep["compliance_type"] for dep in known}
    for extra in sorted(missing - known_values):
        items.append({"compliance_type": extra, "mode": None, "satisfied": False})
    return items


def _template_payload(definition: dict) -> dict:
    """Public shape of a template (GET /workflow/templates)."""
    return {
        "id": str(definition["template_id"]),
        "compliance_type": definition["compliance_type"],
        "mode": definition["mode"],
        "total_steps": definition["total_steps"],
        "depends_on": definition["depends_on"],
        "required_documents": definitions.required_doc_types(definition),
        "required_document_details": definition["required_documents"],
        "steps": [
            {
                "step_number": s["step_number"],
                "step_name": s["step_name"],
                "field_schema": s["fields"],
            }
            for s in definition["steps"]
        ],
    }


def _parse_step_data(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _format_step_row(
    step_number: int,
    step_name: str,
    *,
    is_completed: bool,
    completed_at,
    step_data: Any,
    updated_at,
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    fields: list[dict[str, Any]],
    company_data: dict[str, Any] | None = None,
) -> dict:
    data = _parse_step_data(step_data)
    if company_data:
        data = merge_step_data(
            step_data=data,
            company_data=company_data,
            compliance_type=compliance_type,
            mode=mode,
            step_number=step_number,
            fields=fields,
        )
    return {
        "step_number": step_number,
        "step_name": step_name,
        "is_completed": is_completed,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "step_data": data,
        "is_draft": bool(data) and not is_completed,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "field_schema": fields,
    }


def _steps_payload(
    definition: dict,
    progress_rows: list[asyncpg.Record],
    *,
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    company_data: dict[str, Any] | None,
) -> list[dict]:
    """Steps of a definition joined with whatever the client has saved so far."""
    progress = {row["step_number"]: row for row in progress_rows}
    steps: list[dict] = []
    for step in definition["steps"]:
        row = progress.get(step["step_number"])
        steps.append(
            _format_step_row(
                step["step_number"],
                step["step_name"],
                is_completed=bool(row and row["is_completed"]),
                completed_at=row["completed_at"] if row else None,
                step_data=row["step_data"] if row else {},
                updated_at=row["updated_at"] if row else None,
                compliance_type=compliance_type,
                mode=mode,
                fields=step["fields"],
                company_data=company_data,
            )
        )
    return steps


class WorkflowService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def _definition(
        self,
        conn: asyncpg.Connection,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        workflow: asyncpg.Record | None = None,
    ) -> dict:
        """What a filing runs on: its own snapshot once started, else the live template."""
        template = None
        if workflow is None or not workflow["definition"]:
            template = await definitions.load_template_definition(
                conn, compliance_type.value, mode.value, include_inactive=workflow is not None
            )
        definition = definitions.workflow_definition(workflow, template)
        if definition is None:
            raise HTTPException(status_code=404, detail="This compliance is not available")
        return definition

    async def start(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        allow_inactive: bool = False,
    ) -> asyncpg.Record:
        """Start (or re-open) a filing.

        `allow_inactive` lets an already-paid cart line start even if an admin has
        since switched the compliance off; new purchases of it are still blocked.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_client(conn, company_id, user_id, role))
                existing = await compliance_repo.fetch_workflow(
                    conn, company_id, compliance_type.value, mode.value
                )
                template = await definitions.load_template_definition(
                    conn,
                    compliance_type.value,
                    mode.value,
                    include_inactive=allow_inactive or existing is not None,
                )
                if template is None:
                    raise HTTPException(status_code=404, detail="This compliance is not available")
                _raise_prerequisites(
                    await _engine_prerequisites(conn, compliance_type, mode, company_id)
                )
                if existing is None:
                    await compliance_repo.insert_workflow_if_missing(
                        conn, company_id, compliance_type.value, mode.value, template["total_steps"]
                    )
                row = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                # Freeze the steps this filing will follow (no-op if already frozen).
                await definitions.snapshot_workflow(conn, row["id"], template)
                await compliance_repo.mark_workflow_status(
                    conn, row["id"], ComplianceStatus.PENDING.value, 0
                )
                return _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )

    def _resolve_step(self, definition: dict, step_number: int, step_name: str | None) -> dict:
        step = definitions.find_step(definition, step_number=step_number)
        if step is None:
            raise HTTPException(status_code=400, detail="Workflow template step not configured")
        expected = str(step["step_name"])
        if step_name is not None and step_name.strip() != expected:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Step name does not match workflow template",
                    "expected_step_name": expected,
                },
            )
        return step

    async def save_step_draft(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        step_number: int,
        step_data: dict[str, Any],
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_client(conn, company_id, user_id, role))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                if step_number < 1 or step_number > wf["total_steps"]:
                    raise HTTPException(status_code=400, detail="Invalid step number")
                step = self._resolve_step(
                    await self._definition(conn, compliance_type, mode, wf), step_number, None
                )
                expected = str(step["step_name"])
                if not isinstance(step_data, dict):
                    raise HTTPException(status_code=400, detail="data must be a JSON object")

                existing = await compliance_repo.fetch_step_progress(conn, wf["id"], step_number)
                if existing and existing["is_completed"]:
                    await compliance_repo.update_step_data_only(
                        conn, wf["id"], step_number, expected, step_data
                    )
                else:
                    await compliance_repo.upsert_step_draft(
                        conn, wf["id"], step_number, expected, step_data
                    )

                await upsert_company_data(
                    conn, company_id, extract_shared_values(step_data)
                )
                propagated = await propagate_shared_step_data(
                    conn,
                    company_id=company_id,
                    source_compliance_type=compliance_type,
                    source_mode=mode,
                    step_data=step_data,
                )
                await sync_company_profile_from_shared(conn, company_id, step_data)

                row = await compliance_repo.fetch_step_progress(conn, wf["id"], step_number)
                assert row is not None
                company_data = await fetch_company_data_map(conn, company_id)
                return _format_step_row(
                    step_number,
                    expected,
                    is_completed=row["is_completed"],
                    completed_at=row["completed_at"],
                    step_data=row["step_data"],
                    updated_at=row["updated_at"],
                    compliance_type=compliance_type,
                    mode=mode,
                    fields=step["fields"],
                    company_data=company_data,
                )

    async def complete_step(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        step_number: int,
        step_name: str,
        step_data: dict[str, Any] | None = None,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_client(conn, company_id, user_id, role))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                if step_number < 1 or step_number > wf["total_steps"]:
                    raise HTTPException(status_code=400, detail="Invalid step number")
                step = self._resolve_step(
                    await self._definition(conn, compliance_type, mode, wf), step_number, step_name
                )
                expected = str(step["step_name"])
                if expected == MAKE_PAYMENT_STEP_NAME:
                    entitlement = await entitlements_repo.fetch_payment_entitlement(
                        conn,
                        company_id=company_id,
                        compliance_type=compliance_type.value,
                        mode=mode.value,
                    )
                    if entitlement is None:
                        raise HTTPException(
                            status_code=402,
                            detail=(
                                "Payment required. Pay via cart checkout or "
                                "POST .../checkout-payment — completing this step does not charge."
                            ),
                        )

                payload = step_data if step_data is not None else {}
                if not isinstance(payload, dict):
                    raise HTTPException(status_code=400, detail="data must be a JSON object")

                company_data = await fetch_company_data_map(conn, company_id)
                merged_payload = merge_step_data(
                    step_data=payload,
                    company_data=company_data,
                    compliance_type=compliance_type,
                    mode=mode,
                    step_number=step_number,
                    fields=step["fields"],
                )
                try:
                    validate_step_data(
                        compliance_type,
                        mode,
                        step_number,
                        merged_payload,
                        require_all=True,
                        fields=step["fields"],
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

                await compliance_repo.upsert_step_completion(
                    conn, wf["id"], step_number, expected, merged_payload
                )
                await upsert_company_data(
                    conn, company_id, extract_shared_values(merged_payload)
                )
                await propagate_shared_step_data(
                    conn,
                    company_id=company_id,
                    source_compliance_type=compliance_type,
                    source_mode=mode,
                    step_data=merged_payload,
                )
                await sync_company_profile_from_shared(conn, company_id, merged_payload)
                completed = await compliance_repo.count_completed_steps(conn, wf["id"])
                current_step = min(completed, wf["total_steps"])
                await compliance_repo.mark_workflow_status(
                    conn, wf["id"], ComplianceStatus.PENDING.value, current_step
                )
                return _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )

    async def mark_make_payment_complete(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        payment_reference: str,
        payment_amount: float | None = None,
        ensure_started: bool = True,
    ) -> asyncpg.Record | None:
        """Idempotently complete the Make payment step after cart payment succeeds."""
        if ensure_started:
            await self.start(
                company_id=company_id,
                user_id=user_id,
                role=role,
                compliance_type=compliance_type,
                mode=mode,
                allow_inactive=True,
            )

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                wf = await compliance_repo.fetch_workflow(
                    conn, company_id, compliance_type.value, mode.value
                )
                if wf is None:
                    return None

                payment_step = definitions.find_step(
                    await self._definition(conn, compliance_type, mode, wf),
                    step_name=MAKE_PAYMENT_STEP_NAME,
                )
                if payment_step is None:
                    return wf

                step_number = int(payment_step["step_number"])
                existing = await compliance_repo.fetch_step_progress(conn, wf["id"], step_number)
                if existing and existing["is_completed"]:
                    return wf

                step_data: dict[str, Any] = {"payment_reference": payment_reference}
                if payment_amount is not None:
                    step_data["payment_amount"] = payment_amount

                await compliance_repo.upsert_step_completion(
                    conn,
                    wf["id"],
                    step_number,
                    MAKE_PAYMENT_STEP_NAME,
                    step_data,
                )
                completed = await compliance_repo.count_completed_steps(conn, wf["id"])
                current_step = min(completed, wf["total_steps"])
                await compliance_repo.mark_workflow_status(
                    conn, wf["id"], ComplianceStatus.PENDING.value, current_step
                )
                return await compliance_repo.fetch_workflow(
                    conn, company_id, compliance_type.value, mode.value
                )

    async def checkout_payment(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
    ) -> dict:
        """Ensure this compliance is in cart, checkout, and initialize payment."""
        from app.modules.cart.service import CartService

        cart_svc = CartService(self._pool)

        async with self._pool.acquire() as conn:
            await require_company_client(conn, company_id, user_id, role)

            checkout_cart = await cart_repo.fetch_checkout_cart(conn, company_id)
            in_checkout = False
            pending_payment_id: UUID | None = None
            if checkout_cart is not None:
                items = await cart_repo.list_cart_items(conn, checkout_cart["id"])
                in_checkout = any(
                    i["compliance_type"] == compliance_type.value and i["mode"] == mode.value
                    for i in items
                )
                if in_checkout:
                    payment = await cart_repo.fetch_latest_payment(conn, checkout_cart["id"])
                    if payment is not None and payment["status"] == "PENDING":
                        pending_payment_id = payment["id"]

        if in_checkout and pending_payment_id is not None:
            payment_id = pending_payment_id
        else:
            await cart_svc.add_item(
                company_id=company_id,
                user_id=user_id,
                role=role,
                compliance_type=compliance_type,
                mode=mode,
            )
            checkout = await cart_svc.checkout(
                company_id=company_id, user_id=user_id, role=role
            )
            payment_id = UUID(checkout["payment_id"])

        return await cart_svc.initialize_payment(
            company_id=company_id,
            user_id=user_id,
            role=role,
            payment_id=payment_id,
        )

    async def upload_document(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        doc_type: str,
        file: UploadFile,
    ) -> UUID:
        safe_name = Path(file.filename or "upload").name
        data = await file.read()
        folder = build_upload_folder(
            company_id=str(company_id),
            compliance_type=compliance_type.value,
        )
        storage_url = upload_file(data=data, filename=safe_name, folder=folder)
        async with self._pool.acquire() as conn:
            if role == UserRole.CLIENT:
                _ensure_company(await require_company_client(conn, company_id, user_id, role))
            else:
                _ensure_company(await require_company_agent(conn, company_id, user_id, role))
            return await compliance_repo.insert_document(
                conn,
                company_id,
                compliance_type.value,
                doc_type,
                storage_url,
            )

    async def add_output(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        output_type: str,
        output_value: str,
    ) -> UUID:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_agent(conn, company_id, user_id, role))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                return await compliance_repo.insert_workflow_output(
                    conn, wf["id"], output_type, output_value
                )

    async def get_company_progress(
        self, *, company_id: UUID, user_id: UUID, role: UserRole
    ) -> dict:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_read(conn, company_id, user_id, role))
            return await self._build_company_progress(conn, company_id)

    async def get_status(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
    ) -> dict:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_read(conn, company_id, user_id, role))
            wf = _ensure_workflow(
                await compliance_repo.fetch_workflow(conn, company_id, compliance_type.value, mode.value)
            )
            company_data = await fetch_company_data_map(conn, company_id)
            definition = await self._definition(conn, compliance_type, mode, wf)
            steps = _steps_payload(
                definition,
                await compliance_repo.list_step_progress(conn, wf["id"]),
                compliance_type=compliance_type,
                mode=mode,
                company_data=company_data,
            )
            docs = await compliance_repo.list_document_types(conn, company_id, compliance_type.value)
            outputs = await compliance_repo.list_workflow_outputs(conn, wf["id"])
            entitlement = await entitlements_repo.fetch_payment_entitlement(
                conn,
                company_id=company_id,
                compliance_type=compliance_type.value,
                mode=mode.value,
            )
            return {
                "workflow": {
                    "id": str(wf["id"]),
                    "company_id": str(wf["company_id"]),
                    "compliance_type": wf["compliance_type"],
                    "mode": wf["mode"],
                    "status": wf["status"],
                    "current_step": wf["current_step"],
                    "total_steps": wf["total_steps"],
                    "last_updated": wf["last_updated"].isoformat(),
                    "status_reason": wf["status_reason"],
                    "required_action": wf["required_action"],
                },
                "payment": _payment_payload(entitlement),
                "steps": steps,
                "required_documents": definitions.required_doc_types(definition),
                "required_document_details": definition["required_documents"],
                "documents_uploaded": docs,
                "outputs": [
                    {
                        "id": str(o["id"]),
                        "output_type": o["output_type"],
                        "output_value": o["output_value"],
                        "issued_at": o["issued_at"].isoformat(),
                    }
                    for o in outputs
                ],
            }

    async def get_step_form(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        step_name: str | None = None,
        step_number: int | None = None,
    ) -> dict:
        if step_name is None and step_number is None:
            raise HTTPException(
                status_code=400,
                detail="Provide step_name or step_number query parameter",
            )

        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_read(conn, company_id, user_id, role))

            wf = await compliance_repo.fetch_workflow(
                conn, company_id, compliance_type.value, mode.value
            )
            if wf is None:
                raise HTTPException(
                    status_code=404,
                    detail="Workflow not found. Start it first or complete cart payment.",
                )

            step = definitions.find_step(
                await self._definition(conn, compliance_type, mode, wf),
                step_number=step_number,
                step_name=step_name,
            )
            if step is None:
                raise HTTPException(status_code=404, detail="Workflow step not found")

            resolved_number = int(step["step_number"])
            resolved_name = str(step["step_name"])

            progress = await compliance_repo.fetch_step_progress(conn, wf["id"], resolved_number)
            step_data = _parse_step_data(progress["step_data"] if progress else None)
            company_data = await fetch_company_data_map(conn, company_id)

            fields, missing_required, merged_data = build_step_form_fields(
                compliance_type=compliance_type,
                mode=mode,
                step_number=resolved_number,
                step_data=step_data,
                company_data=company_data,
                fields=step["fields"],
            )

            entitlement = await entitlements_repo.fetch_payment_entitlement(
                conn,
                company_id=company_id,
                compliance_type=compliance_type.value,
                mode=mode.value,
            )
            payment = _payment_payload(entitlement)

            return {
                "company_id": str(company_id),
                "workflow_id": str(wf["id"]),
                "compliance_type": compliance_type.value,
                "mode": mode.value,
                "step_number": resolved_number,
                "step_name": resolved_name,
                "is_completed": bool(progress and progress["is_completed"]),
                "payment": payment,
                "fields": fields,
                "data": merged_data,
                "missing_required": missing_required,
                "ready_to_complete": len(missing_required) == 0,
                "save": {
                    "method": "PUT",
                    "path": f"/api/v1/workflow/{compliance_type.value}/{mode.value}/companies/{company_id}/steps/{resolved_number}/draft",
                    "body": {"data": {"<field_key>": "<value>"}},
                },
                "complete": {
                    "method": "POST",
                    "path": f"/api/v1/workflow/{compliance_type.value}/{mode.value}/companies/{company_id}/steps/{resolved_number}/complete",
                    "body": {"step_name": resolved_name, "data": {"<field_key>": "<value>"}},
                },
            }

    async def list_templates(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            return [
                _template_payload(d) for d in await definitions.list_template_definitions(conn)
            ]

    async def get_template(self, compliance_type: ComplianceType, mode: ComplianceMode) -> dict:
        async with self._pool.acquire() as conn:
            definition = await definitions.load_template_definition(
                conn, compliance_type.value, mode.value
            )
            if definition is None:
                raise HTTPException(status_code=404, detail="Workflow template not found")
            return _template_payload(definition)

    async def get_prerequisites(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
    ) -> dict:
        """Read-only prerequisite check so the client can show what's missing before start()."""
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_read(conn, company_id, user_id, role))
            items = await _prerequisite_status(conn, compliance_type, mode, company_id)
            return {
                "compliance_type": compliance_type.value,
                "mode": mode.value,
                "depends_on": items,
                "all_satisfied": all(i["satisfied"] for i in items),
            }

    async def get_company_progress_admin(self, *, company_id: UUID) -> dict:
        """Full workflow progress for admins (any company)."""
        async with self._pool.acquire() as conn:
            from app.modules.cac.repository import fetch_company_by_id

            if await fetch_company_by_id(conn, company_id) is None:
                raise HTTPException(status_code=404, detail="Company not found")
            return await self._build_company_progress(conn, company_id)

    async def _build_company_progress(self, conn: asyncpg.Connection, company_id: UUID) -> dict:
        company_data = await fetch_company_data_map(conn, company_id)
        instances = {
            _workflow_key(w["compliance_type"], w["mode"]): w
            for w in await compliance_repo.list_workflows_for_company(conn, company_id)
        }
        registry_by_type = {
            r["compliance_type"]: r
            for r in await compliance_repo.list_registry_for_company(conn, company_id)
        }

        workflows: list[dict] = []
        # A compliance an admin has switched off still shows for companies that
        # already have a filing on it; everyone else only sees active ones.
        for template in await definitions.list_template_definitions(conn, include_inactive=True):
            ct = template["compliance_type"]
            mode = template["mode"]
            instance = instances.get(_workflow_key(ct, mode))
            if instance is None and not template["is_active"]:
                continue
            ct_enum = ComplianceType(ct)
            mode_enum = ComplianceMode(mode)
            definition = definitions.workflow_definition(instance, template)
            assert definition is not None
            uploaded_docs = await compliance_repo.list_document_types(conn, company_id, ct)
            required_docs = definitions.required_doc_types(definition)

            steps = _steps_payload(
                definition,
                await compliance_repo.list_step_progress(conn, instance["id"]) if instance else [],
                compliance_type=ct_enum,
                mode=mode_enum,
                company_data=company_data,
            )
            if instance is None:
                steps_completed = 0
                workflow_status = ComplianceStatus.NOT_STARTED.value
                workflow_id = None
                current_step = 0
            else:
                workflow_id = instance["id"]
                steps_completed = sum(1 for s in steps if s["is_completed"])
                workflow_status = instance["status"]
                current_step = instance["current_step"]

            total_steps = len(definition["steps"])
            missing_docs = [d for d in required_docs if d not in uploaded_docs]
            reg = registry_by_type.get(ct)

            workflows.append(
                {
                    "compliance_type": ct,
                    "mode": mode,
                    "started": instance is not None,
                    "workflow_id": str(workflow_id) if workflow_id else None,
                    "status": workflow_status,
                    "current_step": current_step,
                    "total_steps": total_steps,
                    "steps_completed": steps_completed,
                    "progress_percent": round((steps_completed / total_steps) * 100) if total_steps else 0,
                    "steps": steps,
                    "required_documents": required_docs,
                    "required_document_details": definition["required_documents"],
                    "documents_uploaded": uploaded_docs,
                    "missing_documents": missing_docs,
                    "registry": {
                        "status": reg["status"] if reg else ComplianceStatus.NOT_STARTED.value,
                        "expiry_date": reg["expiry_date"].isoformat() if reg and reg["expiry_date"] else None,
                    },
                }
            )

        return {"company_id": str(company_id), "workflows": workflows}

    async def submit(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        expiry_date: date | None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_client(conn, company_id, user_id, role))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(conn, company_id, compliance_type.value, mode.value)
                )
                missing: list[str] = []

                entitlement = await entitlements_repo.fetch_unconsumed_entitlement(
                    conn,
                    company_id=company_id,
                    compliance_type=compliance_type.value,
                    mode=mode.value,
                )
                if entitlement is None:
                    missing.append("PAYMENT: compliance fee not paid")

                completed = await compliance_repo.count_completed_steps(conn, wf["id"])
                if completed < wf["total_steps"]:
                    missing.append(f"STEPS: {completed}/{wf['total_steps']}")

                required_docs = definitions.required_doc_types(
                    await self._definition(conn, compliance_type, mode, wf)
                )
                uploaded_docs = set(
                    await compliance_repo.list_document_types(conn, company_id, compliance_type.value)
                )
                for doc in required_docs:
                    if doc not in uploaded_docs:
                        missing.append(f"DOCUMENT:{doc}")

                missing.extend(await _engine_prerequisites(conn, compliance_type, mode, company_id))

                deduped = list(dict.fromkeys(missing))
                if deduped:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "message": "Workflow submission blocked by missing requirements",
                            "missing": deduped,
                        },
                    )

                assert entitlement is not None
                consumed = await entitlements_repo.consume_entitlement(
                    conn,
                    entitlement_id=entitlement["id"],
                    workflow_id=wf["id"],
                )
                if not consumed:
                    raise HTTPException(
                        status_code=409,
                        detail="Payment entitlement already used for submission",
                    )

                await compliance_repo.mark_workflow_status(
                    conn, wf["id"], ComplianceStatus.IN_REVIEW.value, wf["total_steps"]
                )
                await compliance_repo.upsert_registry_status(
                    conn,
                    company_id,
                    compliance_type.value,
                    ComplianceStatus.IN_REVIEW.value,
                    expiry_date,
                )

                owner = await conn.fetchrow(
                    """
                    SELECT u.email AS owner_email, c.name AS company_name
                    FROM companies c
                    JOIN users u ON u.id = c.user_id
                    WHERE c.id = $1
                    """,
                    company_id,
                )
                result = {
                    "company_id": str(company_id),
                    "compliance_type": compliance_type.value,
                    "mode": mode.value,
                    "status": ComplianceStatus.IN_REVIEW.value,
                    "expiry_date": expiry_date.isoformat() if expiry_date else None,
                }

        NotificationService.emit(
            "workflow.submitted",
            {
                **result,
                "owner_email": owner["owner_email"] if owner else None,
                "company_name": owner["company_name"] if owner else None,
            },
        )
        return result

    async def update_workflow_status(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        status: ComplianceStatus,
        current_step: int | None = None,
        reason: str | None = None,
        required_action: str | None = None,
    ) -> dict:
        if status in (ComplianceStatus.REJECTED, ComplianceStatus.INFO_REQUIRED) and not reason:
            raise HTTPException(
                status_code=422,
                detail="A reason is required when marking a workflow REJECTED or INFO_REQUIRED",
            )
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_agent(conn, company_id, user_id, role))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                step = current_step if current_step is not None else wf["current_step"]
                await compliance_repo.mark_workflow_status(
                    conn,
                    wf["id"],
                    status.value,
                    step,
                    reason=reason,
                    required_action=required_action,
                    updated_by=user_id,
                )
                updated = await compliance_repo.fetch_workflow(
                    conn, company_id, compliance_type.value, mode.value
                )
                assert updated is not None
                return {
                    "workflow_id": str(updated["id"]),
                    "status": updated["status"],
                    "current_step": updated["current_step"],
                    "status_reason": updated["status_reason"],
                    "required_action": updated["required_action"],
                }

    async def complete_workflow_as_agent(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        expiry_date: date | None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_agent(conn, company_id, user_id, role))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                await compliance_repo.mark_workflow_status(
                    conn, wf["id"], ComplianceStatus.COMPLETED.value, wf["total_steps"]
                )
                await compliance_repo.upsert_registry_status(
                    conn,
                    company_id,
                    compliance_type.value,
                    ComplianceStatus.COMPLETED.value,
                    expiry_date,
                )

                owner = await conn.fetchrow(
                    """
                    SELECT u.email AS owner_email, c.name AS company_name
                    FROM companies c
                    JOIN users u ON u.id = c.user_id
                    WHERE c.id = $1
                    """,
                    company_id,
                )
                result = {
                    "company_id": str(company_id),
                    "compliance_type": compliance_type.value,
                    "mode": mode.value,
                    "status": ComplianceStatus.COMPLETED.value,
                    "expiry_date": expiry_date.isoformat() if expiry_date else None,
                }

        NotificationService.emit(
            "workflow.completed",
            {
                **result,
                "owner_email": owner["owner_email"] if owner else None,
                "company_name": owner["company_name"] if owner else None,
                "completed_by_user_id": str(user_id),
            },
        )
        return result

    async def update_registry(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        status: ComplianceStatus,
        expiry_date: date | None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_agent(conn, company_id, user_id, role))
                await compliance_repo.upsert_registry_status(
                    conn, company_id, compliance_type.value, status.value, expiry_date
                )
                row = await compliance_repo.fetch_registry_row(
                    conn, company_id, compliance_type.value
                )
                return {
                    "compliance_type": compliance_type.value,
                    "status": row["status"] if row else status.value,
                    "expiry_date": row["expiry_date"].isoformat()
                    if row and row["expiry_date"]
                    else None,
                }
