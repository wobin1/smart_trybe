"""Step schema coverage tests."""

from app.domain.enums import ComplianceMode, ComplianceType
from app.modules.workflow.step_schemas import get_step_field_schema


def test_itf_new_step_fields_are_structured():
    fields = get_step_field_schema(ComplianceType.ITF, ComplianceMode.NEW, 1)
    keys = {f["key"] for f in fields}
    assert "employee_count" in keys
    assert "notes" not in keys or len(fields) > 1


def test_pencom_new_has_employee_json():
    fields = get_step_field_schema(ComplianceType.PENCOM, ComplianceMode.NEW, 2)
    assert any(f["key"] == "employees" for f in fields)


def test_scuml_registration_step_4_questionnaire():
    fields = get_step_field_schema(ComplianceType.SCUML, ComplianceMode.REGISTRATION, 4)
    keys = {f["key"] for f in fields}
    assert "transaction_volume" in keys
    assert "client_types" in keys


def test_bpp_state_step_2_includes_state():
    fields = get_step_field_schema(ComplianceType.BPP_STATE, ComplianceMode.REGISTRATION, 2)
    keys = {f["key"] for f in fields}
    assert "state_of_operation" in keys
