from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.domain.enums import ComplianceMode, ComplianceStatus, ComplianceType
from app.modules.cac.repository import fetch_company_for_user
from app.modules.compliance import repository as compliance_repo
from app.modules.compliance.engine import ComplianceEngine
from app.modules.workflow.catalog import REQUIRED_DOCS, WORKFLOW_STEP_DEFINITIONS


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
        compliance_type: ComplianceType,
        mode: ComplianceMode,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await fetch_company_for_user(conn, company_id, user_id))
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

    async def complete_step(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        step_number: int,
        step_name: str,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await fetch_company_for_user(conn, company_id, user_id))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                if step_number < 1 or step_number > wf["total_steps"]:
                    raise HTTPException(status_code=400, detail="Invalid step number")
                template_step = await compliance_repo.fetch_template_step(
                    conn, compliance_type.value, mode.value, step_number
                )
                if template_step is None:
                    raise HTTPException(status_code=400, detail="Workflow template step not configured")
                expected = str(template_step["step_name"])
                if step_name.strip() != expected:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "message": "Step name does not match workflow template",
                            "expected_step_name": expected,
                        },
                    )
                await compliance_repo.upsert_step_completion(conn, wf["id"], step_number, expected)
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
        compliance_type: ComplianceType,
        doc_type: str,
        file: UploadFile,
    ) -> UUID:
        safe_name = Path(file.filename or "upload").name
        data = await file.read()
        async with self._pool.acquire() as conn:
            _ensure_company(await fetch_company_for_user(conn, company_id, user_id))
            dest_dir = Path(settings.upload_dir) / str(company_id) / compliance_type.value.lower()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / f"{uuid4()}_{safe_name}"
            dest_path.write_bytes(data)
            return await compliance_repo.insert_document(
                conn,
                company_id,
                compliance_type.value,
                doc_type,
                str(dest_path.resolve()),
            )

    async def add_output(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        output_type: str,
        output_value: str,
    ) -> UUID:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await fetch_company_for_user(conn, company_id, user_id))
                wf = _ensure_workflow(
                    await compliance_repo.fetch_workflow(
                        conn, company_id, compliance_type.value, mode.value
                    )
                )
                return await compliance_repo.insert_workflow_output(
                    conn, wf["id"], output_type, output_value
                )

    async def get_company_progress(self, *, company_id: UUID, user_id: UUID) -> dict:
        async with self._pool.acquire() as conn:
            _ensure_company(await fetch_company_for_user(conn, company_id, user_id))

            templates = await compliance_repo.list_workflow_templates(conn)
            instances = {
                _workflow_key(w["compliance_type"], w["mode"]): w
                for w in await compliance_repo.list_workflows_for_company(conn, company_id)
            }
            registry_by_type = {
                r["compliance_type"]: r for r in await compliance_repo.list_registry_for_company(conn, company_id)
            }

            workflows: list[dict] = []
            for template in templates:
                ct = template["compliance_type"]
                mode = template["mode"]
                key = _workflow_key(ct, mode)
                instance = instances.get(key)
                required_docs = sorted(REQUIRED_DOCS.get((ComplianceType(ct), ComplianceMode(mode)), set()))
                uploaded_docs = await compliance_repo.list_document_types(conn, company_id, ct)

                if instance is None:
                    template_steps = await compliance_repo.list_template_steps(conn, template["id"])
                    steps = [
                        {
                            "step_number": s["step_number"],
                            "step_name": s["step_name"],
                            "is_completed": False,
                            "completed_at": None,
                        }
                        for s in template_steps
                    ]
                    steps_completed = 0
                    workflow_status = ComplianceStatus.NOT_STARTED.value
                    workflow_id = None
                    current_step = 0
                else:
                    workflow_id = instance["id"]
                    steps = [
                        {
                            "step_number": s["step_number"],
                            "step_name": s["step_name"],
                            "is_completed": s["is_completed"],
                            "completed_at": s["completed_at"].isoformat() if s["completed_at"] else None,
                        }
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

            return {
                "company_id": str(company_id),
                "workflows": workflows,
            }

    async def get_status(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
    ) -> dict:
        async with self._pool.acquire() as conn:
            _ensure_company(await fetch_company_for_user(conn, company_id, user_id))
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
                    {
                        "step_number": s["step_number"],
                        "step_name": s["step_name"],
                        "is_completed": s["is_completed"],
                        "completed_at": s["completed_at"].isoformat() if s["completed_at"] else None,
                    }
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
                    }
                    for s in steps
                ],
            }

    async def submit(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        expiry_date: date | None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await fetch_company_for_user(conn, company_id, user_id))
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
                    "status": "COMPLETED",
                    "expiry_date": expiry_date.isoformat() if expiry_date else None,
                }
