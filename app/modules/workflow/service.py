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

STEP_COUNTS: dict[tuple[ComplianceType, ComplianceMode], int] = {
    (ComplianceType.CAC, ComplianceMode.NEW): 8,
    (ComplianceType.CAC, ComplianceMode.RENEWAL): 5,
    (ComplianceType.FIRS, ComplianceMode.NEW): 5,
    (ComplianceType.FIRS, ComplianceMode.RENEWAL): 5,
    (ComplianceType.ITF, ComplianceMode.NEW): 4,
    (ComplianceType.ITF, ComplianceMode.RENEWAL): 4,
    (ComplianceType.NSITF, ComplianceMode.NEW): 4,
    (ComplianceType.NSITF, ComplianceMode.RENEWAL): 3,
    (ComplianceType.PENCOM, ComplianceMode.NEW): 4,
    (ComplianceType.PENCOM, ComplianceMode.RENEWAL): 3,
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.NEW): 4,
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.RENEWAL): 4,
    (ComplianceType.ACCOUNT_AUDITING, ComplianceMode.PROCESS): 3,
    (ComplianceType.SCUML, ComplianceMode.REGISTRATION): 5,
}

REQUIRED_DOCS: dict[tuple[ComplianceType, ComplianceMode], set[str]] = {
    (ComplianceType.CAC, ComplianceMode.NEW): {
        "VALID_ID",
        "PASSPORT_PHOTO",
        "ADDRESS_PROOF",
        "SIGNATURE",
    },
    (ComplianceType.CAC, ComplianceMode.RENEWAL): {"FINANCIAL_SUMMARY"},
    (ComplianceType.FIRS, ComplianceMode.NEW): {"CAC_CERTIFICATE", "CAC_STATUS_REPORT", "DIRECTOR_DETAILS"},
    (ComplianceType.FIRS, ComplianceMode.RENEWAL): {"AUDITED_FINANCIAL_STATEMENTS"},
    (ComplianceType.ITF, ComplianceMode.NEW): {"CAC_CERTIFICATE", "EMPLOYEE_LIST", "PAYROLL_INFO"},
    (ComplianceType.ITF, ComplianceMode.RENEWAL): {"PAYROLL_REPORT", "PAYMENT_PROOF"},
    (ComplianceType.NSITF, ComplianceMode.NEW): {"CAC_CERTIFICATE", "STAFF_LIST", "PAYROLL_SCHEDULE"},
    (ComplianceType.NSITF, ComplianceMode.RENEWAL): {"UPDATED_PAYROLL", "PAYMENT_RECEIPT"},
    (ComplianceType.PENCOM, ComplianceMode.NEW): {"STAFF_LIST", "EMPLOYMENT_DETAILS"},
    (ComplianceType.PENCOM, ComplianceMode.RENEWAL): {"PENSION_REMITTANCE_RECORDS", "EMPLOYEE_PENSION_DETAILS"},
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.NEW): {"STAFF_SALARY_LIST", "CAC_DETAILS"},
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.RENEWAL): {
        "UPDATED_PAYROLL",
        "PREVIOUS_CERTIFICATE",
    },
    (ComplianceType.ACCOUNT_AUDITING, ComplianceMode.PROCESS): {
        "BANK_STATEMENTS",
        "TRANSACTION_RECORDS",
    },
    (ComplianceType.SCUML, ComplianceMode.REGISTRATION): {
        "CAC_CERTIFICATE",
        "CAC_STATUS_REPORT",
        "DIRECTOR_VALID_ID",
        "UTILITY_BILL",
        "TIN",
    },
}


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

    def _total_steps(self, compliance_type: ComplianceType, mode: ComplianceMode) -> int:
        return STEP_COUNTS.get((compliance_type, mode), 1)

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
                row = await compliance_repo.upsert_workflow(
                    conn,
                    company_id,
                    compliance_type.value,
                    mode.value,
                    self._total_steps(compliance_type, mode),
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
                await compliance_repo.upsert_step_completion(conn, wf["id"], step_number, step_name)
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
            steps = await compliance_repo.list_workflow_steps(conn, wf["id"])
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
