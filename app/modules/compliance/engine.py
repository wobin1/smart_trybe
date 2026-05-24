"""
Smart dependency detection for compliance workflows.

Rules implemented:
- BPP Federal / State: Active TCC (FIRS), PENCOM, ITF, NSITF.
- FIRS TCC: Audited accounts (ACCOUNT_AUDITING completed & active) + CAC completed & active (status report proxy).
- PENCOM renewal: Active CAC + staff list document on PENCOM.
"""

from datetime import date
from uuid import UUID

import asyncpg

from app.domain.enums import ComplianceType
from app.modules.compliance import repository as reg_repo


def _today() -> date:
    return date.today()


def _completed_active(row: asyncpg.Record | None, require_expiry: bool = False) -> bool:
    """Completed row is active if expiry is absent or not yet passed."""
    if row is None:
        return False
    if row["status"] != "COMPLETED":
        return False
    exp = row["expiry_date"]
    if exp is None:
        return not require_expiry
    return exp >= _today()


def _active_tcc(row: asyncpg.Record | None) -> bool:
    """TCC must be completed with a non-null expiry on or after today."""
    if row is None:
        return False
    if row["status"] != "COMPLETED":
        return False
    exp = row["expiry_date"]
    if exp is None:
        return False
    return exp >= _today()


class ComplianceEngine:
    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    async def missing_for_bpp(self, company_id: UUID) -> list[str]:
        missing: list[str] = []
        firs = await reg_repo.fetch_registry_row(self._conn, company_id, ComplianceType.FIRS.value)
        pencom = await reg_repo.fetch_registry_row(self._conn, company_id, ComplianceType.PENCOM.value)
        itf = await reg_repo.fetch_registry_row(self._conn, company_id, ComplianceType.ITF.value)
        nsitf = await reg_repo.fetch_registry_row(self._conn, company_id, ComplianceType.NSITF.value)

        firs_renewal = await reg_repo.workflow_is_completed(
            self._conn, company_id, ComplianceType.FIRS.value, "RENEWAL"
        )
        pencom_renewal = await reg_repo.workflow_is_completed(
            self._conn, company_id, ComplianceType.PENCOM.value, "RENEWAL"
        )
        itf_renewal = await reg_repo.workflow_is_completed(
            self._conn, company_id, ComplianceType.ITF.value, "RENEWAL"
        )
        nsitf_renewal = await reg_repo.workflow_is_completed(
            self._conn, company_id, ComplianceType.NSITF.value, "RENEWAL"
        )

        if not _active_tcc(firs) or not firs_renewal:
            missing.append(ComplianceType.FIRS.value)
        if not _completed_active(pencom) or not pencom_renewal:
            missing.append(ComplianceType.PENCOM.value)
        if not _completed_active(itf) or not itf_renewal:
            missing.append(ComplianceType.ITF.value)
        if not _completed_active(nsitf) or not nsitf_renewal:
            missing.append(ComplianceType.NSITF.value)
        return missing

    async def missing_for_firs_tcc(self, company_id: UUID) -> list[str]:
        missing: list[str] = []
        audit = await reg_repo.fetch_registry_row(
            self._conn, company_id, ComplianceType.ACCOUNT_AUDITING.value
        )
        cac = await reg_repo.fetch_registry_row(self._conn, company_id, ComplianceType.CAC.value)

        if not _completed_active(audit):
            missing.append(ComplianceType.ACCOUNT_AUDITING.value)
        if not _completed_active(cac):
            missing.append(ComplianceType.CAC.value)
        return missing

    async def missing_for_pencom_renewal(self, company_id: UUID) -> list[str]:
        missing: list[str] = []
        cac = await reg_repo.fetch_registry_row(self._conn, company_id, ComplianceType.CAC.value)
        if not _completed_active(cac):
            missing.append(ComplianceType.CAC.value)

        has_staff_list = await reg_repo.document_exists(
            self._conn,
            company_id,
            ComplianceType.PENCOM.value,
            "STAFF_LIST",
        )
        if not has_staff_list:
            missing.append("PENCOM_STAFF_LIST")
        return missing
