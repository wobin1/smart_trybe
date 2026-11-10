"""
Smart dependency detection for compliance workflows.

A compliance's dependencies are stored on its template (`depends_on`) and edited
by admins. A dependency is satisfied when the company's registry entry for that
compliance is COMPLETED and not expired. Two built-in refinements remain:
- FIRS as a dependency means an active TCC, so it must carry an expiry date.
- PENCOM renewal additionally needs a staff list document on PENCOM.
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

    async def missing_dependencies(self, company_id: UUID, depends_on: list[dict]) -> list[str]:
        """Codes of the dependencies this company has not completed (or let expire)."""
        missing: list[str] = []
        for dep in depends_on:
            code = str(dep["compliance_type"])
            row = await reg_repo.fetch_registry_row(self._conn, company_id, code)
            satisfied = _active_tcc(row) if code == ComplianceType.FIRS else _completed_active(row)
            if not satisfied:
                missing.append(code)
        return missing

    async def missing_pencom_staff_list(self, company_id: UUID) -> list[str]:
        has_staff_list = await reg_repo.document_exists(
            self._conn, company_id, ComplianceType.PENCOM.value, "STAFF_LIST"
        )
        return [] if has_staff_list else ["PENCOM_STAFF_LIST"]

    # The three methods below are the original hard-coded rules. They are no longer
    # called by the workflow service (see missing_dependencies) and are kept only
    # for reference until the data-driven rules have been through a release.
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
