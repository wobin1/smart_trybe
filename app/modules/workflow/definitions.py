"""Compliance definitions stored in the database.

A *definition* is everything that describes how a compliance is filed:

    {
        "steps": [{"step_number": 1, "step_name": "...", "fields": [...]}, ...],
        "required_documents": [{"doc_type": "CAC_CERTIFICATE", "label": "CAC Certificate"}, ...],
        "depends_on": [{"compliance_type": "FIRS", "mode": "RENEWAL"}, ...],
    }

The template tables hold the current definition, which admins edit. When a filing
starts, its steps and required documents are copied onto the workflow row
(`compliance_workflows.definition`) so later edits never reshape a filing that is
already in progress. Dependencies are always read live from the template.

The dictionaries in catalog.py / step_schemas.py are only defaults used to seed
built-in compliances and to fill in templates created before this module existed.
"""

import json
import re
from typing import Any
from uuid import UUID

import asyncpg

from app.domain.enums import COMPLIANCE_CODE_RE, ComplianceMode, ComplianceType
from app.modules.workflow.catalog import (
    DEPENDENCY_TYPES,
    MAKE_PAYMENT_STEP_NAME,
    REQUIRED_DOCS,
    WORKFLOW_STEP_DEFINITIONS,
)
from app.modules.workflow.step_schemas import get_step_field_schema

# Field kinds an admin can put on a step. "json" is only used by built-in steps
# that have a bespoke screen (directors, shareholders, employees).
FIELD_TYPES = ("text", "textarea", "number", "date", "email", "boolean", "select", "json")
ADMIN_FIELD_TYPES = tuple(t for t in FIELD_TYPES if t != "json")

PAYMENT_STEP_FIELDS: list[dict[str, Any]] = [
    {"key": "payment_reference", "label": "Payment reference", "type": "text", "required": False},
    {"key": "payment_amount", "label": "Payment amount (NGN)", "type": "number", "required": False},
]

_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,59}")
_DOC_TYPE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,59}")

MAX_STEPS = 20
MAX_FIELDS_PER_STEP = 30
MAX_REQUIRED_DOCUMENTS = 30


class DefinitionError(ValueError):
    """An admin-supplied definition is not valid."""


def slugify_key(label: str) -> str:
    """`Contact e-mail` -> `contact_e_mail` (a field key)."""
    key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    if not key:
        return ""
    if not key[0].isalpha():
        key = f"f_{key}"
    return key[:60]


def slugify_code(label: str) -> str:
    """`Tax Clearance (State)` -> `TAX_CLEARANCE_STATE` (a compliance code / doc type)."""
    code = re.sub(r"[^A-Z0-9]+", "_", label.strip().upper()).strip("_")
    if not code:
        return ""
    if not code[0].isalpha():
        code = f"C_{code}"
    return code[:40]


def doc_label(doc_type: str) -> str:
    return doc_type.replace("_", " ").title()


def _parse_json(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw


# ── Validation of admin input ─────────────────────────────────────────────────


def normalise_fields(raw: Any, *, allow_json: bool = False) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DefinitionError("fields must be a list")
    if len(raw) > MAX_FIELDS_PER_STEP:
        raise DefinitionError(f"A step can have at most {MAX_FIELDS_PER_STEP} fields")

    allowed = FIELD_TYPES if allow_json else ADMIN_FIELD_TYPES
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise DefinitionError("Each field must be an object")
        label = str(item.get("label") or "").strip()
        if not label:
            raise DefinitionError("Every field needs a label")
        key = str(item.get("key") or "").strip() or slugify_key(label)
        if not _KEY_RE.fullmatch(key):
            raise DefinitionError(
                f"Field key {key!r} must be lowercase letters, digits and underscores, starting with a letter"
            )
        if key in seen:
            raise DefinitionError(f"Field key {key!r} is used twice in the same step")
        seen.add(key)

        field_type = str(item.get("type") or "text").strip().lower()
        if field_type not in allowed:
            raise DefinitionError(
                f"Field {label!r} has unknown type {field_type!r}. Use one of: {', '.join(allowed)}"
            )

        field: dict[str, Any] = {
            "key": key,
            "label": label,
            "type": field_type,
            "required": bool(item.get("required")),
        }
        if field_type == "select":
            options = item.get("options")
            if not isinstance(options, list):
                raise DefinitionError(f"Dropdown field {label!r} needs a list of options")
            cleaned = [str(o).strip() for o in options if str(o).strip()]
            if len(cleaned) < 2:
                raise DefinitionError(f"Dropdown field {label!r} needs at least two options")
            field["options"] = list(dict.fromkeys(cleaned))
        description = str(item.get("description") or "").strip()
        if description:
            field["description"] = description[:500]
        fields.append(field)
    return fields


def normalise_steps(raw: Any, *, allow_json: bool = False) -> list[dict[str, Any]]:
    """Validate admin steps and return them numbered, always ending with the payment step.

    Every compliance ends with exactly one "Make payment" step: paying is what
    creates the entitlement that submission requires, so it is not optional and
    the admin does not manage it.
    """
    if not isinstance(raw, list):
        raise DefinitionError("steps must be a list")

    steps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise DefinitionError("Each step must be an object")
        name = str(item.get("step_name") or "").strip()
        if not name:
            raise DefinitionError("Every step needs a name")
        if len(name) > 200:
            raise DefinitionError("Step names can be at most 200 characters")
        if name.lower() == MAKE_PAYMENT_STEP_NAME.lower():
            continue  # re-added below, always last
        if name.lower() in seen:
            raise DefinitionError(f"Step name {name!r} is used twice")
        seen.add(name.lower())
        steps.append({"step_name": name, "fields": normalise_fields(item.get("fields"), allow_json=allow_json)})

    if not steps:
        raise DefinitionError("Add at least one step before the payment step")
    if len(steps) + 1 > MAX_STEPS:
        raise DefinitionError(f"A compliance can have at most {MAX_STEPS} steps")

    steps.append({"step_name": MAKE_PAYMENT_STEP_NAME, "fields": list(PAYMENT_STEP_FIELDS)})
    return [{"step_number": n, **step} for n, step in enumerate(steps, start=1)]


def normalise_required_documents(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DefinitionError("required_documents must be a list")
    if len(raw) > MAX_REQUIRED_DOCUMENTS:
        raise DefinitionError(f"A compliance can require at most {MAX_REQUIRED_DOCUMENTS} documents")

    docs: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            item = {"doc_type": item}
        if not isinstance(item, dict):
            raise DefinitionError("Each required document must be an object")
        label = str(item.get("label") or "").strip()
        doc_type = str(item.get("doc_type") or "").strip().upper() or slugify_code(label)
        if not _DOC_TYPE_RE.fullmatch(doc_type):
            raise DefinitionError(
                f"Document type {doc_type!r} must be capital letters, digits and underscores"
            )
        if doc_type in seen:
            raise DefinitionError(f"Document {doc_type!r} is listed twice")
        seen.add(doc_type)
        docs.append({"doc_type": doc_type, "label": label or doc_label(doc_type)})
    return docs


def normalise_depends_on(raw: Any, *, own: tuple[str, str] | None = None) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DefinitionError("depends_on must be a list")

    deps: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise DefinitionError("Each dependency must be an object")
        code = str(item.get("compliance_type") or "").strip().upper()
        if not COMPLIANCE_CODE_RE.fullmatch(code):
            raise DefinitionError(f"Dependency {code!r} is not a valid compliance code")
        try:
            mode = ComplianceMode(str(item.get("mode") or "").strip().upper()).value
        except ValueError as exc:
            raise DefinitionError(f"Dependency {code} has an unknown mode") from exc
        if own is not None and code == own[0]:
            raise DefinitionError("A compliance cannot depend on itself")
        if code in seen:
            raise DefinitionError(f"Dependency {code} is listed twice")
        seen.add(code)
        deps.append({"compliance_type": code, "mode": mode})
    return deps


# ── Code defaults (seed data for built-ins) ───────────────────────────────────


def default_steps(compliance_type: str, mode: str) -> list[dict[str, Any]] | None:
    key = (ComplianceType(compliance_type), ComplianceMode(mode))
    names = WORKFLOW_STEP_DEFINITIONS.get(key)
    if names is None:
        return None
    return [
        {
            "step_number": n,
            "step_name": name,
            "fields": [dict(f) for f in get_step_field_schema(key[0], key[1], n)],
        }
        for n, name in enumerate(names, start=1)
    ]


def default_step_fields(compliance_type: str, mode: str, step_number: int) -> list[dict[str, Any]]:
    return [
        dict(f)
        for f in get_step_field_schema(ComplianceType(compliance_type), ComplianceMode(mode), step_number)
    ]


def default_required_documents(compliance_type: str, mode: str) -> list[dict[str, str]]:
    docs = REQUIRED_DOCS.get((ComplianceType(compliance_type), ComplianceMode(mode)), set())
    return [{"doc_type": d, "label": doc_label(d)} for d in sorted(docs)]


def default_depends_on(compliance_type: str, mode: str) -> list[dict[str, str]]:
    deps = DEPENDENCY_TYPES.get((ComplianceType(compliance_type), ComplianceMode(mode)), [])
    return [{"compliance_type": t.value, "mode": m.value} for t, m in deps]


# ── Reading ───────────────────────────────────────────────────────────────────


def _template_definition(
    template: asyncpg.Record, step_rows: list[asyncpg.Record]
) -> dict[str, Any]:
    ct, mode = template["compliance_type"], template["mode"]
    steps = []
    for row in step_rows:
        fields = _parse_json(row["fields"])
        if not isinstance(fields, list):
            # Template created before fields were stored: use the code default.
            fields = default_step_fields(ct, mode, row["step_number"])
        steps.append({"step_number": row["step_number"], "step_name": row["step_name"], "fields": fields})

    required = _parse_json(template["required_documents"])
    if not isinstance(required, list):
        required = default_required_documents(ct, mode)
    depends = _parse_json(template["depends_on"])
    if not isinstance(depends, list):
        depends = default_depends_on(ct, mode)

    return {
        "template_id": template["id"],
        "compliance_type": ct,
        "mode": mode,
        "is_active": template["is_active"],
        "total_steps": len(steps),
        "steps": steps,
        "required_documents": required,
        "depends_on": depends,
    }


_TEMPLATE_COLUMNS = """
    id, compliance_type::text AS compliance_type, mode::text AS mode, total_steps,
    is_active, required_documents, depends_on
"""


async def _fetch_steps(conn: asyncpg.Connection, template_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT step_number, step_name, fields
        FROM workflow_template_steps
        WHERE template_id = $1
        ORDER BY step_number ASC
        """,
        template_id,
    )


async def load_template_definition(
    conn: asyncpg.Connection,
    compliance_type: str,
    mode: str,
    *,
    include_inactive: bool = False,
) -> dict[str, Any] | None:
    template = await conn.fetchrow(
        f"""
        SELECT {_TEMPLATE_COLUMNS}
        FROM workflow_templates
        WHERE compliance_type = $1::compliance_type AND mode = $2::compliance_mode
        """,
        str(compliance_type),
        str(getattr(mode, "value", mode)),
    )
    if template is None or (not template["is_active"] and not include_inactive):
        return None
    return _template_definition(template, await _fetch_steps(conn, template["id"]))


async def list_template_definitions(
    conn: asyncpg.Connection, *, include_inactive: bool = False
) -> list[dict[str, Any]]:
    templates = await conn.fetch(
        f"""
        SELECT {_TEMPLATE_COLUMNS}
        FROM workflow_templates
        {"" if include_inactive else "WHERE is_active = TRUE"}
        ORDER BY compliance_type::text ASC, mode::text ASC
        """
    )
    return [_template_definition(t, await _fetch_steps(conn, t["id"])) for t in templates]


def workflow_definition(
    workflow: asyncpg.Record | dict[str, Any] | None, template_definition: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The definition a filing runs on: its own snapshot if it has one, else the template."""
    snapshot = _parse_json(workflow["definition"]) if workflow is not None else None
    if isinstance(snapshot, dict) and isinstance(snapshot.get("steps"), list):
        return {
            "steps": snapshot["steps"],
            "required_documents": snapshot.get("required_documents") or [],
            "total_steps": len(snapshot["steps"]),
        }
    return template_definition


def find_step(
    definition: dict[str, Any], *, step_number: int | None = None, step_name: str | None = None
) -> dict[str, Any] | None:
    for step in definition["steps"]:
        if step_number is not None and step["step_number"] == step_number:
            return step
        if (
            step_number is None
            and step_name is not None
            and str(step["step_name"]).strip().lower() == step_name.strip().lower()
        ):
            return step
    return None


def required_doc_types(definition: dict[str, Any]) -> list[str]:
    return sorted(d["doc_type"] for d in definition.get("required_documents") or [])


# ── Writing ───────────────────────────────────────────────────────────────────


def snapshot_payload(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "steps": definition["steps"],
        "required_documents": definition.get("required_documents") or [],
    }


async def save_template_definition(
    conn: asyncpg.Connection,
    compliance_type: str,
    mode: str,
    *,
    steps: list[dict[str, Any]],
    required_documents: list[dict[str, str]],
    depends_on: list[dict[str, str]],
    is_active: bool = True,
) -> UUID:
    """Create or replace a template. Callers pass already-normalised values."""
    template = await conn.fetchrow(
        """
        INSERT INTO workflow_templates (
            compliance_type, mode, total_steps, is_active, required_documents, depends_on, updated_at
        )
        VALUES ($1::compliance_type, $2::compliance_mode, $3, $4, $5::jsonb, $6::jsonb, NOW())
        ON CONFLICT (compliance_type, mode) DO UPDATE SET
            total_steps = EXCLUDED.total_steps,
            is_active = EXCLUDED.is_active,
            required_documents = EXCLUDED.required_documents,
            depends_on = EXCLUDED.depends_on,
            updated_at = NOW()
        RETURNING id
        """,
        compliance_type,
        mode,
        len(steps),
        is_active,
        json.dumps(required_documents),
        json.dumps(depends_on),
    )
    assert template is not None
    await conn.execute("DELETE FROM workflow_template_steps WHERE template_id = $1", template["id"])
    await conn.executemany(
        """
        INSERT INTO workflow_template_steps (template_id, step_number, step_name, fields)
        VALUES ($1, $2, $3, $4::jsonb)
        """,
        [
            (template["id"], s["step_number"], s["step_name"], json.dumps(s["fields"]))
            for s in steps
        ],
    )
    return template["id"]


async def set_template_active(
    conn: asyncpg.Connection, compliance_type: str, mode: str, is_active: bool
) -> None:
    await conn.execute(
        """
        UPDATE workflow_templates SET is_active = $3, updated_at = NOW()
        WHERE compliance_type = $1::compliance_type AND mode = $2::compliance_mode
        """,
        compliance_type,
        mode,
        is_active,
    )


async def snapshot_workflow(
    conn: asyncpg.Connection, workflow_id: UUID, definition: dict[str, Any]
) -> None:
    """Freeze the definition onto a filing (no-op if it already has one)."""
    await conn.execute(
        """
        UPDATE compliance_workflows
        SET definition = $2::jsonb, total_steps = $3
        WHERE id = $1 AND definition IS NULL
        """,
        workflow_id,
        json.dumps(snapshot_payload(definition)),
        len(definition["steps"]),
    )
