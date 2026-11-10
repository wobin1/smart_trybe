"""Admins create and edit compliances; clients file them."""

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.test_admin_catalog import _admin_headers

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


def _client_with_company(client: TestClient) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": f"cmp_{uuid4().hex}@example.com", "password": "securepassword123"},
    )
    assert reg.status_code == 201
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "Builder Ltd", "rc_number": "RC4242", "registration_type": "EXISTING"},
    )
    assert company.status_code == 201
    return headers, company.json()["id"]


def _new_compliance(code: str, **overrides) -> dict:
    body = {
        "display_name": f"Test Agency {code}",
        "code": code,
        "category_slug": "data_regulatory",
        "description": "Created by a test",
        "regulator_name": "the Test Agency",
        "base_price_ngn": 12500,
        "is_active": True,
        "steps": [
            {
                "step_name": "Tell us about the business",
                "fields": [
                    {"label": "CAC RC number", "key": "cac_rc_number", "type": "text", "required": True},
                    {"label": "Sector", "type": "select", "options": ["Tech", "Retail"], "required": True},
                    {"label": "Year founded", "type": "number"},
                ],
            },
            {"step_name": "Confirm", "fields": [{"label": "I confirm", "type": "boolean", "required": True}]},
        ],
        "required_documents": [{"label": "Operating licence"}],
        "depends_on": [],
    }
    body.update(overrides)
    return body


def _code() -> str:
    return f"T{uuid4().hex[:10].upper()}"


def test_only_admins_can_manage_compliances(client: TestClient):
    headers, _ = _client_with_company(client)
    assert client.get("/api/v1/admin/compliances", headers=headers).status_code == 403
    assert (
        client.post("/api/v1/admin/compliances", headers=headers, json=_new_compliance(_code())).status_code
        == 403
    )


def test_admin_creates_compliance_and_client_files_it(client: TestClient):
    admin = _admin_headers(client)
    code = _code()

    created = client.post("/api/v1/admin/compliances", headers=admin, json=_new_compliance(code))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["compliance_type"] == code
    assert body["mode"] == "REGISTRATION"
    assert body["is_system"] is False
    # The payment step is always appended and always last.
    assert [s["step_name"] for s in body["steps"]] == [
        "Tell us about the business",
        "Confirm",
        "Make payment",
    ]
    # Keys are derived from labels when not given.
    assert [f["key"] for f in body["steps"][0]["fields"]] == ["cac_rc_number", "sector", "year_founded"]
    assert body["required_documents"] == [{"doc_type": "OPERATING_LICENCE", "label": "Operating licence"}]

    headers, company_id = _client_with_company(client)

    # It is on sale: in the catalog, in the templates, and addable to a cart.
    catalog = client.get("/api/v1/catalog/items", headers=headers).json()["items"]
    item = next(i for i in catalog if i["compliance_type"] == code)
    assert item["base_price_ngn"] == 12500
    assert item["regulator_name"] == "the Test Agency"
    templates = client.get("/api/v1/workflow/templates", headers=headers).json()
    assert any(t["compliance_type"] == code for t in templates)

    add = client.post(
        f"/api/v1/cart/companies/{company_id}/items",
        headers=headers,
        json={"compliance_type": code, "mode": "REGISTRATION"},
    )
    assert add.status_code == 201, add.text

    base = f"/api/v1/workflow/{code}/REGISTRATION/companies/{company_id}"
    assert client.post(f"{base}/start", headers=headers).status_code == 200

    # Shared company data prefills the admin-defined field, and required fields are enforced.
    form = client.get(f"{base}/steps/form", headers=headers, params={"step_number": 1}).json()
    rc = next(f for f in form["fields"] if f["key"] == "cac_rc_number")
    assert rc["value"] == "RC4242"
    assert "sector" in form["missing_required"]

    incomplete = client.post(
        f"{base}/steps/1/complete",
        headers=headers,
        json={"step_name": "Tell us about the business", "data": {}},
    )
    assert incomplete.status_code == 400
    assert "sector" in incomplete.json()["detail"]

    done = client.post(
        f"{base}/steps/1/complete",
        headers=headers,
        json={"step_name": "Tell us about the business", "data": {"sector": "Tech"}},
    )
    assert done.status_code == 200, done.text

    # Submission is blocked until the admin-required document is uploaded.
    submit = client.post(f"{base}/submit", headers=headers)
    assert submit.status_code == 403
    assert "DOCUMENT:OPERATING_LICENCE" in submit.json()["detail"]["missing"]


def test_edits_only_affect_new_filings(client: TestClient):
    admin = _admin_headers(client)
    code = _code()
    assert client.post("/api/v1/admin/compliances", headers=admin, json=_new_compliance(code)).status_code == 201

    headers, company_id = _client_with_company(client)
    base = f"/api/v1/workflow/{code}/REGISTRATION/companies/{company_id}"
    assert client.post(f"{base}/start", headers=headers).status_code == 200

    updated = client.put(
        f"/api/v1/admin/compliances/{code}/REGISTRATION",
        headers=admin,
        json={
            "base_price_ngn": 20000,
            "steps": [
                {"step_name": "One new step", "fields": [{"label": "Anything", "type": "text"}]},
                {"step_name": "Second new step", "fields": []},
                {"step_name": "Third new step", "fields": []},
            ],
            "required_documents": [],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["total_steps"] == 4
    assert updated.json()["open_filings"] == 1

    # The filing already in progress keeps the steps and documents it started with.
    status = client.get(f"{base}/status", headers=headers).json()
    assert [s["step_name"] for s in status["steps"]] == [
        "Tell us about the business",
        "Confirm",
        "Make payment",
    ]
    assert status["required_documents"] == ["OPERATING_LICENCE"]

    # A filing started afterwards gets the new definition.
    headers2, company2 = _client_with_company(client)
    base2 = f"/api/v1/workflow/{code}/REGISTRATION/companies/{company2}"
    assert client.post(f"{base2}/start", headers=headers2).status_code == 200
    status2 = client.get(f"{base2}/status", headers=headers2).json()
    assert [s["step_name"] for s in status2["steps"]][0] == "One new step"
    assert status2["workflow"]["total_steps"] == 4
    assert status2["required_documents"] == []


def test_switching_off_hides_from_clients_but_keeps_existing_filings(client: TestClient):
    admin = _admin_headers(client)
    code = _code()
    assert client.post("/api/v1/admin/compliances", headers=admin, json=_new_compliance(code)).status_code == 201

    headers, company_id = _client_with_company(client)
    base = f"/api/v1/workflow/{code}/REGISTRATION/companies/{company_id}"
    assert client.post(f"{base}/start", headers=headers).status_code == 200

    off = client.put(
        f"/api/v1/admin/compliances/{code}/REGISTRATION", headers=admin, json={"is_active": False}
    )
    assert off.status_code == 200 and off.json()["is_active"] is False

    # Gone for someone new...
    headers2, company2 = _client_with_company(client)
    templates = client.get("/api/v1/workflow/templates", headers=headers2).json()
    assert not any(t["compliance_type"] == code for t in templates)
    assert (
        client.post(
            f"/api/v1/workflow/{code}/REGISTRATION/companies/{company2}/start", headers=headers2
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/cart/companies/{company2}/items",
            headers=headers2,
            json={"compliance_type": code, "mode": "REGISTRATION"},
        ).status_code
        == 404
    )

    # ...but the company that already started still sees and can continue its filing.
    assert client.get(f"{base}/status", headers=headers).status_code == 200
    progress = client.get(f"/api/v1/workflow/companies/{company_id}/progress", headers=headers).json()
    assert any(w["compliance_type"] == code and w["started"] for w in progress["workflows"])
    progress2 = client.get(f"/api/v1/workflow/companies/{company2}/progress", headers=headers2).json()
    assert not any(w["compliance_type"] == code for w in progress2["workflows"])


def test_retired_variant_is_not_on_sale(client: TestClient):
    """Each agency has one application: ITF Renewal was retired in favour of ITF."""
    headers, company_id = _client_with_company(client)
    templates = client.get("/api/v1/workflow/templates", headers=headers).json()
    keys = {(t["compliance_type"], t["mode"]) for t in templates}
    assert ("ITF", "NEW") in keys
    assert ("ITF", "RENEWAL") not in keys
    assert (
        client.post(
            f"/api/v1/workflow/ITF/RENEWAL/companies/{company_id}/start", headers=headers
        ).status_code
        == 404
    )


def test_validation_of_admin_input(client: TestClient):
    admin = _admin_headers(client)

    def post(**overrides):
        code = overrides.pop("code", None) or _code()
        return client.post("/api/v1/admin/compliances", headers=admin, json=_new_compliance(code, **overrides))

    # Cannot be put on sale for free: payment is what unlocks submission.
    assert post(base_price_ngn=0).status_code == 422
    assert post(base_price_ngn=0, is_active=False).status_code == 201
    # A dropdown needs options.
    assert post(steps=[{"step_name": "S", "fields": [{"label": "Pick", "type": "select"}]}]).status_code == 422
    # Unknown field type.
    assert post(steps=[{"step_name": "S", "fields": [{"label": "X", "type": "signature"}]}]).status_code == 422
    # Duplicate field keys in a step.
    assert (
        post(steps=[{"step_name": "S", "fields": [{"label": "Name"}, {"label": "name"}]}]).status_code == 422
    )
    # Unknown category and unknown dependency.
    assert post(category_slug="nope").status_code == 422
    assert post(depends_on=[{"compliance_type": "DOES_NOT_EXIST", "mode": "NEW"}]).status_code == 422
    # Codes are unique.
    assert post(code="CAC").status_code == 409
    assert post(code="not valid!").status_code == 422


def test_dependencies_are_enforced_and_cannot_loop(client: TestClient):
    admin = _admin_headers(client)
    first, second = _code(), _code()
    assert client.post("/api/v1/admin/compliances", headers=admin, json=_new_compliance(first)).status_code == 201
    created = client.post(
        "/api/v1/admin/compliances",
        headers=admin,
        json=_new_compliance(second, depends_on=[{"compliance_type": first, "mode": "REGISTRATION"}]),
    )
    assert created.status_code == 201, created.text

    # first -> second would close the loop.
    loop = client.put(
        f"/api/v1/admin/compliances/{first}/REGISTRATION",
        headers=admin,
        json={"depends_on": [{"compliance_type": second, "mode": "REGISTRATION"}]},
    )
    assert loop.status_code == 422

    headers, company_id = _client_with_company(client)
    blocked = client.post(
        f"/api/v1/workflow/{second}/REGISTRATION/companies/{company_id}/start", headers=headers
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["missing_compliance"] == [first]
    prereq = client.get(
        f"/api/v1/workflow/{second}/REGISTRATION/companies/{company_id}/prerequisites", headers=headers
    ).json()
    assert prereq["depends_on"] == [{"compliance_type": first, "mode": "REGISTRATION", "satisfied": False}]


def test_builtin_placeholders_can_be_priced_and_switched_on(client: TestClient):
    admin = _admin_headers(client)
    nitda = client.get("/api/v1/admin/compliances/NITDA/REGISTRATION", headers=admin)
    assert nitda.status_code == 200
    assert nitda.json()["is_system"] is True
    assert nitda.json()["steps"][-1]["step_name"] == "Make payment"

    original = nitda.json()
    try:
        # Still at its placeholder price of zero, so it cannot go on sale yet.
        if original["base_price_ngn"] == 0:
            refused = client.put(
                "/api/v1/admin/compliances/NITDA/REGISTRATION", headers=admin, json={"is_active": True}
            )
            assert refused.status_code == 422
        on = client.put(
            "/api/v1/admin/compliances/NITDA/REGISTRATION",
            headers=admin,
            json={"is_active": True, "base_price_ngn": 60000},
        )
        assert on.status_code == 200, on.text
        headers, _ = _client_with_company(client)
        templates = client.get("/api/v1/workflow/templates", headers=headers).json()
        assert any(t["compliance_type"] == "NITDA" for t in templates)
    finally:
        client.put(
            "/api/v1/admin/compliances/NITDA/REGISTRATION",
            headers=admin,
            json={"is_active": False, "base_price_ngn": original["base_price_ngn"]},
        )


def test_schema_and_migrations_are_idempotent():
    """Booting twice must not change anything (the app does this on every restart)."""
    import asyncpg

    from app.db.bootstrap import run_schema
    from app.db.migrations import run_migrations

    async def run() -> list[str]:
        conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
        try:
            await run_schema(conn)
            return await run_migrations(conn)
        finally:
            await conn.close()

    assert asyncio.run(run()) == []
