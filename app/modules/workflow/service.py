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
from app.modules.workflow.catalog import REQUIRED_DOCS, WORKFLOW_STEP_DEFINITIONS
from app.modules.workflow.step_schemas import get_step_field_schema, validate_step_data


def _workflow_key(compliance_type: str, mode: str) -> tuple[str, str]:
    return compliance_type, mode


def _ensure_company(row: asyncpg.Record | None) -> asyncpg.Record:
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


def _ensure_workflow(row: asyncpg.Record | None) -> asyncpg.Record:
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found. Start it first.")
    return row


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
) -> dict:
    data = _parse_step_data(step_data)
    return {
        "step_number": step_number,
        "step_name": step_name,
        "is_completed": is_completed,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "step_data": data,
        "is_draft": bool(data) and not is_completed,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "field_schema": get_step_field_schema(compliance_type, mode, step_number),
    }


class WorkflowService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    def _steps_for(self, compliance_type: ComplianceType, mode: ComplianceMode) -> list[str]:
        return WORKFLOW_STEP_DEFINITIONS.get((compliance_type, mode), ["Step 1"])

    async def start(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_client(conn, company_id, user_id, role))
                template = await compliance_repo.fetch_workflow_template(
                    conn, compliance_type.value, mode.value
                )
                if template is None:
                    steps = self._steps_for(compliance_type, mode)
                    template = await compliance_repo.upsert_workflow_template(
                        conn,
                        compliance_type.value,
                        mode.value,
                        len(steps),
                    )
                    assert template is not None
                    await compliance_repo.replace_template_steps(conn, template["id"], steps)
                row = await compliance_repo.upsert_workflow(
                    conn,
                    company_id,
                    compliance_type.value,
                    mode.value,
                    int(template["total_steps"]),
                )
                await compliance_repo.mark_workflow_status(
                    conn, row["id"], ComplianceStatus.PENDING.value, 0
                )
                return _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )

    async def _resolve_template_step(
        self,
        conn: asyncpg.Connection,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        step_number: int,
        step_name: str | None,
    ) -> str:
        template_step = await compliance_repo.fetch_template_step(
            conn, compliance_type.value, mode.value, step_number
        )
        if template_step is None:
            raise HTTPException(status_code=400, detail="Workflow template step not configured")
        expected = str(template_step["step_name"])
        if step_name is not None and step_name.strip() != expected:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Step name does not match workflow template",
                    "expected_step_name": expected,
                },
            )
        return expected

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
                expected = await self._resolve_template_step(
                    conn, compliance_type, mode, step_number, None
                )
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

                row = await compliance_repo.fetch_step_progress(conn, wf["id"], step_number)
                assert row is not None
                return _format_step_row(
                    step_number,
                    expected,
                    is_completed=row["is_completed"],
                    completed_at=row["completed_at"],
                    step_data=row["step_data"],
                    updated_at=row["updated_at"],
                    compliance_type=compliance_type,
                    mode=mode,
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
                expected = await self._resolve_template_step(
                    conn, compliance_type, mode, step_number, step_name
                )
                payload = step_data if step_data is not None else {}
                if not isinstance(payload, dict):
                    raise HTTPException(status_code=400, detail="data must be a JSON object")
                try:
                    validate_step_data(
                        compliance_type, mode, step_number, payload, require_all=True
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

                await compliance_repo.upsert_step_completion(
                    conn, wf["id"], step_number, expected, payload
                )
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
            steps = await compliance_repo.list_template_steps_with_progress(
                conn, wf["id"], compliance_type.value, mode.value
            )
            docs = await compliance_repo.list_document_types(conn, company_id, compliance_type.value)
            outputs = await compliance_repo.list_workflow_outputs(conn, wf["id"])
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
                },
                "steps": [
                    _format_step_row(
                        s["step_number"],
                        s["step_name"],
                        is_completed=s["is_completed"],
                        completed_at=s["completed_at"],
                        step_data=s["step_data"],
                        updated_at=s["updated_at"],
                        compliance_type=compliance_type,
                        mode=mode,
                    )
                    for s in steps
                ],
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

    async def list_templates(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            templates = await compliance_repo.list_workflow_templates(conn)
            payload: list[dict] = []
            for t in templates:
                steps = await compliance_repo.list_template_steps(conn, t["id"])
                ct = ComplianceType(t["compliance_type"])
                md = ComplianceMode(t["mode"])
                payload.append(
                    {
                        "id": str(t["id"]),
                        "compliance_type": t["compliance_type"],
                        "mode": t["mode"],
                        "total_steps": t["total_steps"],
                        "steps": [
                            {
                                "step_number": s["step_number"],
                                "step_name": s["step_name"],
                                "field_schema": get_step_field_schema(ct, md, s["step_number"]),
                            }
                            for s in steps
                        ],
                    }
                )
            return payload

    async def get_template(self, compliance_type: ComplianceType, mode: ComplianceMode) -> dict:
        async with self._pool.acquire() as conn:
            template = await compliance_repo.fetch_workflow_template(
                conn, compliance_type.value, mode.value
            )
            if template is None:
                raise HTTPException(status_code=404, detail="Workflow template not found")
            steps = await compliance_repo.list_template_steps(conn, template["id"])
            return {
                "id": str(template["id"]),
                "compliance_type": template["compliance_type"],
                "mode": template["mode"],
                "total_steps": template["total_steps"],
                "steps": [
                    {
                        "step_number": s["step_number"],
                        "step_name": s["step_name"],
                        "field_schema": get_step_field_schema(
                            compliance_type, mode, s["step_number"]
                        ),
                    }
                    for s in steps
                ],
            }

    async def get_company_progress_admin(self, *, company_id: UUID) -> dict:
        """Full workflow progress for admins (any company)."""
        async with self._pool.acquire() as conn:
            from app.modules.cac.repository import fetch_company_by_id

            if await fetch_company_by_id(conn, company_id) is None:
                raise HTTPException(status_code=404, detail="Company not found")
            return await self._build_company_progress(conn, company_id)

    async def _build_company_progress(self, conn: asyncpg.Connection, company_id: UUID) -> dict:
        templates = await compliance_repo.list_workflow_templates(conn)
        instances = {
            _workflow_key(w["compliance_type"], w["mode"]): w
            for w in await compliance_repo.list_workflows_for_company(conn, company_id)
        }
        registry_by_type = {
            r["compliance_type"]: r
            for r in await compliance_repo.list_registry_for_company(conn, company_id)
        }

        workflows: list[dict] = []
        for template in templates:
            ct = template["compliance_type"]
            mode = template["mode"]
            key = _workflow_key(ct, mode)
            instance = instances.get(key)
            required_docs = sorted(REQUIRED_DOCS.get((ComplianceType(ct), ComplianceMode(mode)), set()))
            uploaded_docs = await compliance_repo.list_document_types(conn, company_id, ct)
            ct_enum = ComplianceType(ct)
            mode_enum = ComplianceMode(mode)

            if instance is None:
                template_steps = await compliance_repo.list_template_steps(conn, template["id"])
                steps = [
                    _format_step_row(
                        s["step_number"],
                        s["step_name"],
                        is_completed=False,
                        completed_at=None,
                        step_data={},
                        updated_at=None,
                        compliance_type=ct_enum,
                        mode=mode_enum,
                    )
                    for s in template_steps
                ]
                steps_completed = 0
                workflow_status = ComplianceStatus.NOT_STARTED.value
                workflow_id = None
                current_step = 0
            else:
                workflow_id = instance["id"]
                steps = [
                    _format_step_row(
                        s["step_number"],
                        s["step_name"],
                        is_completed=s["is_completed"],
                        completed_at=s["completed_at"],
                        step_data=s["step_data"],
                        updated_at=s["updated_at"],
                        compliance_type=ct_enum,
                        mode=mode_enum,
                    )
                    for s in await compliance_repo.list_template_steps_with_progress(
                        conn, workflow_id, ct, mode
                    )
                ]
                steps_completed = sum(1 for s in steps if s["is_completed"])
                workflow_status = instance["status"]
                current_step = instance["current_step"]

            total_steps = int(template["total_steps"])
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
                completed = await compliance_repo.count_completed_steps(conn, wf["id"])
                if completed < wf["total_steps"]:
                    missing.append(f"STEPS: {completed}/{wf['total_steps']}")

                required_docs = REQUIRED_DOCS.get((compliance_type, mode), set())
                uploaded_docs = set(
                    await compliance_repo.list_document_types(conn, company_id, compliance_type.value)
                )
                for doc in sorted(required_docs):
                    if doc not in uploaded_docs:
                        missing.append(f"DOCUMENT:{doc}")

                engine = ComplianceEngine(conn)
                if compliance_type == ComplianceType.FIRS and mode == ComplianceMode.RENEWAL:
                    missing.extend(await engine.missing_for_firs_tcc(company_id))
                if compliance_type == ComplianceType.PENCOM and mode == ComplianceMode.RENEWAL:
                    missing.extend(await engine.missing_for_pencom_renewal(company_id))
                if compliance_type in (ComplianceType.BPP_FEDERAL, ComplianceType.BPP_STATE):
                    missing.extend(await engine.missing_for_bpp(company_id))

                deduped = list(dict.fromkeys(missing))
                if deduped:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "message": "Workflow submission blocked by missing requirements",
                            "missing": deduped,
                        },
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
                return {
                    "company_id": str(company_id),
                    "compliance_type": compliance_type.value,
                    "mode": mode.value,
                    "status": ComplianceStatus.IN_REVIEW.value,
                    "expiry_date": expiry_date.isoformat() if expiry_date else None,
                }

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
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_agent(conn, company_id, user_id, role))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                step = current_step if current_step is not None else wf["current_step"]
                await compliance_repo.mark_workflow_status(conn, wf["id"], status.value, step)
                updated = await compliance_repo.fetch_workflow(
                    conn, company_id, compliance_type.value, mode.value
                )
                assert updated is not None
                return {
                    "workflow_id": str(updated["id"]),
                    "status": updated["status"],
                    "current_step": updated["current_step"],
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
                return {
                    "company_id": str(company_id),
                    "compliance_type": compliance_type.value,
                    "mode": mode.value,
                    "status": ComplianceStatus.COMPLETED.value,
                    "expiry_date": expiry_date.isoformat() if expiry_date else None,
                }

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
