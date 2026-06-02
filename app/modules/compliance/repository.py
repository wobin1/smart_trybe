from datetime import date
from uuid import UUID

import asyncpg


async def fetch_registry_row(
    conn: asyncpg.Connection,
    company_id: UUID,
    compliance_type: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT company_id, compliance_type::text AS compliance_type,
               status::text AS status, expiry_date, last_updated
        FROM compliance_registry
        WHERE company_id = $1 AND compliance_type = $2::compliance_type
        """,
        company_id,
        compliance_type,
    )


async def upsert_registry_status(
    conn: asyncpg.Connection,
    company_id: UUID,
    compliance_type: str,
    status: str,
    expiry_date: date | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO compliance_registry (company_id, compliance_type, status, expiry_date, last_updated)
        VALUES ($1, $2::compliance_type, $3::compliance_status, $4, NOW())
        ON CONFLICT (company_id, compliance_type)
        DO UPDATE SET
            status = EXCLUDED.status,
            expiry_date = EXCLUDED.expiry_date,
            last_updated = NOW()
        """,
        company_id,
        compliance_type,
        status,
        expiry_date,
    )


async def insert_document(
    conn: asyncpg.Connection,
    company_id: UUID,
    compliance_type: str,
    doc_type: str,
    s3_url: str,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO documents (company_id, compliance_type, doc_type, s3_url)
        VALUES ($1, $2::compliance_type, $3, $4)
        RETURNING id
        """,
        company_id,
        compliance_type,
        doc_type,
        s3_url,
    )
    assert row is not None
    return row["id"]


async def document_exists(
    conn: asyncpg.Connection,
    company_id: UUID,
    compliance_type: str,
    doc_type: str,
) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM documents
        WHERE company_id = $1
          AND compliance_type = $2::compliance_type
          AND doc_type = $3
        LIMIT 1
        """,
        company_id,
        compliance_type,
        doc_type,
    )
    return row is not None


async def fetch_document_for_company(
    conn: asyncpg.Connection,
    document_id: UUID,
    company_id: UUID,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, company_id, compliance_type::text AS compliance_type,
               doc_type, s3_url, uploaded_at
        FROM documents
        WHERE id = $1 AND company_id = $2
        """,
        document_id,
        company_id,
    )


async def list_documents_for_company(
    conn: asyncpg.Connection,
    company_id: UUID,
    *,
    compliance_type: str | None = None,
    doc_type: str | None = None,
) -> list[asyncpg.Record]:
    clauses = ["company_id = $1"]
    args: list[object] = [company_id]
    idx = 2
    if compliance_type is not None:
        clauses.append(f"compliance_type = ${idx}::compliance_type")
        args.append(compliance_type)
        idx += 1
    if doc_type is not None:
        clauses.append(f"doc_type = ${idx}")
        args.append(doc_type)
        idx += 1
    where = " AND ".join(clauses)
    return await conn.fetch(
        f"""
        SELECT id, company_id, compliance_type::text AS compliance_type,
               doc_type, s3_url, uploaded_at
        FROM documents
        WHERE {where}
        ORDER BY uploaded_at DESC
        """,
        *args,
    )


async def list_document_types(
    conn: asyncpg.Connection,
    company_id: UUID,
    compliance_type: str,
) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT doc_type
        FROM documents
        WHERE company_id = $1 AND compliance_type = $2::compliance_type
        """,
        company_id,
        compliance_type,
    )
    return [r["doc_type"] for r in rows]


async def upsert_workflow(
    conn: asyncpg.Connection,
    company_id: UUID,
    compliance_type: str,
    mode: str,
    total_steps: int,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO compliance_workflows (company_id, compliance_type, mode, total_steps)
        VALUES ($1, $2::compliance_type, $3::compliance_mode, $4)
        ON CONFLICT (company_id, compliance_type, mode)
        DO UPDATE SET total_steps = EXCLUDED.total_steps, last_updated = NOW()
        RETURNING id, company_id, compliance_type::text AS compliance_type, mode::text AS mode,
                  status::text AS status, current_step, total_steps, last_updated
        """,
        company_id,
        compliance_type,
        mode,
        total_steps,
    )


async def upsert_workflow_template(
    conn: asyncpg.Connection,
    compliance_type: str,
    mode: str,
    total_steps: int,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO workflow_templates (compliance_type, mode, total_steps, updated_at)
        VALUES ($1::compliance_type, $2::compliance_mode, $3, NOW())
        ON CONFLICT (compliance_type, mode)
        DO UPDATE SET
            total_steps = EXCLUDED.total_steps,
            is_active = TRUE,
            updated_at = NOW()
        RETURNING id, compliance_type::text AS compliance_type, mode::text AS mode, total_steps
        """,
        compliance_type,
        mode,
        total_steps,
    )


async def replace_template_steps(
    conn: asyncpg.Connection,
    template_id: UUID,
    steps: list[str],
) -> None:
    await conn.execute(
        """
        DELETE FROM workflow_template_steps
        WHERE template_id = $1
        """,
        template_id,
    )
    for idx, step_name in enumerate(steps, start=1):
        await conn.execute(
            """
            INSERT INTO workflow_template_steps (template_id, step_number, step_name)
            VALUES ($1, $2, $3)
            """,
            template_id,
            idx,
            step_name,
        )


async def fetch_workflow_template(
    conn: asyncpg.Connection,
    compliance_type: str,
    mode: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, compliance_type::text AS compliance_type, mode::text AS mode, total_steps
        FROM workflow_templates
        WHERE compliance_type = $1::compliance_type
          AND mode = $2::compliance_mode
          AND is_active = TRUE
        """,
        compliance_type,
        mode,
    )


async def fetch_template_step(
    conn: asyncpg.Connection,
    compliance_type: str,
    mode: str,
    step_number: int,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT s.step_number, s.step_name
        FROM workflow_templates t
        JOIN workflow_template_steps s ON s.template_id = t.id
        WHERE t.compliance_type = $1::compliance_type
          AND t.mode = $2::compliance_mode
          AND t.is_active = TRUE
          AND s.step_number = $3
        """,
        compliance_type,
        mode,
        step_number,
    )


async def list_workflow_templates(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT id, compliance_type::text AS compliance_type, mode::text AS mode, total_steps
        FROM workflow_templates
        WHERE is_active = TRUE
        ORDER BY compliance_type::text ASC, mode::text ASC
        """
    )


async def list_template_steps(conn: asyncpg.Connection, template_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT step_number, step_name
        FROM workflow_template_steps
        WHERE template_id = $1
        ORDER BY step_number ASC
        """,
        template_id,
    )


async def list_workflows_for_company(
    conn: asyncpg.Connection,
    company_id: UUID,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT id, company_id, compliance_type::text AS compliance_type, mode::text AS mode,
               status::text AS status, current_step, total_steps, last_updated
        FROM compliance_workflows
        WHERE company_id = $1
        ORDER BY compliance_type::text ASC, mode::text ASC
        """,
        company_id,
    )


async def list_registry_for_company(
    conn: asyncpg.Connection,
    company_id: UUID,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT company_id, compliance_type::text AS compliance_type,
               status::text AS status, expiry_date, last_updated
        FROM compliance_registry
        WHERE company_id = $1
        ORDER BY compliance_type::text ASC
        """,
        company_id,
    )


async def fetch_workflow(
    conn: asyncpg.Connection,
    company_id: UUID,
    compliance_type: str,
    mode: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, company_id, compliance_type::text AS compliance_type, mode::text AS mode,
               status::text AS status, current_step, total_steps, last_updated
        FROM compliance_workflows
        WHERE company_id = $1
          AND compliance_type = $2::compliance_type
          AND mode = $3::compliance_mode
        """,
        company_id,
        compliance_type,
        mode,
    )


async def mark_workflow_status(
    conn: asyncpg.Connection,
    workflow_id: UUID,
    status: str,
    current_step: int,
) -> None:
    await conn.execute(
        """
        UPDATE compliance_workflows
        SET status = $2::compliance_status, current_step = $3, last_updated = NOW()
        WHERE id = $1
        """,
        workflow_id,
        status,
        current_step,
    )


async def upsert_step_completion(
    conn: asyncpg.Connection,
    workflow_id: UUID,
    step_number: int,
    step_name: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO compliance_step_progress (workflow_id, step_number, step_name, is_completed, completed_at)
        VALUES ($1, $2, $3, TRUE, NOW())
        ON CONFLICT (workflow_id, step_number)
        DO UPDATE SET
            step_name = EXCLUDED.step_name,
            is_completed = TRUE,
            completed_at = NOW()
        """,
        workflow_id,
        step_number,
        step_name,
    )


async def list_workflow_steps(conn: asyncpg.Connection, workflow_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT step_number, step_name, is_completed, completed_at
        FROM compliance_step_progress
        WHERE workflow_id = $1
        ORDER BY step_number ASC
        """,
        workflow_id,
    )


async def list_template_steps_with_progress(
    conn: asyncpg.Connection,
    workflow_id: UUID,
    compliance_type: str,
    mode: str,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT
            s.step_number,
            s.step_name,
            COALESCE(p.is_completed, FALSE) AS is_completed,
            p.completed_at
        FROM workflow_templates t
        JOIN workflow_template_steps s ON s.template_id = t.id
        LEFT JOIN compliance_step_progress p
          ON p.workflow_id = $1
         AND p.step_number = s.step_number
        WHERE t.compliance_type = $2::compliance_type
          AND t.mode = $3::compliance_mode
          AND t.is_active = TRUE
        ORDER BY s.step_number ASC
        """,
        workflow_id,
        compliance_type,
        mode,
    )


async def count_completed_steps(conn: asyncpg.Connection, workflow_id: UUID) -> int:
    row = await conn.fetchrow(
        """
        SELECT COUNT(*)::int AS c
        FROM compliance_step_progress
        WHERE workflow_id = $1 AND is_completed = TRUE
        """,
        workflow_id,
    )
    assert row is not None
    return row["c"]


async def insert_workflow_output(
    conn: asyncpg.Connection,
    workflow_id: UUID,
    output_type: str,
    output_value: str,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO compliance_outputs (workflow_id, output_type, output_value)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        workflow_id,
        output_type,
        output_value,
    )
    assert row is not None
    return row["id"]


async def list_workflow_outputs(conn: asyncpg.Connection, workflow_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT id, output_type, output_value, issued_at
        FROM compliance_outputs
        WHERE workflow_id = $1
        ORDER BY issued_at DESC
        """,
        workflow_id,
    )


async def workflow_is_completed(
    conn: asyncpg.Connection,
    company_id: UUID,
    compliance_type: str,
    mode: str,
) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM compliance_workflows
        WHERE company_id = $1
          AND compliance_type = $2::compliance_type
          AND mode = $3::compliance_mode
          AND status = 'COMPLETED'::compliance_status
        LIMIT 1
        """,
        company_id,
        compliance_type,
        mode,
    )
    return row is not None
