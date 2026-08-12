from pydantic import BaseModel, ValidationError

from amlguard.monitoring.failures import sanitized_failure_details


class _StructuredOutput(BaseModel):
    recommendation: str
    findings: list[str]


def test_validation_diagnostics_exclude_values_and_exception_messages() -> None:
    sensitive_value = "synthetic-sensitive-model-output"
    try:
        _StructuredOutput.model_validate(
            {"recommendation": 123, "findings": [sensitive_value, 42]}
        )
    except ValidationError as error:
        details = sanitized_failure_details(error)
    else:
        raise AssertionError("invalid structured output was unexpectedly accepted")

    assert details["error_code"] == "SCHEMA_VALIDATION_FAILED"
    assert details["validation_issue_count"] == 2
    assert details["validation_issues"] == [
        {"location": "recommendation", "issue_type": "string_type"},
        {"location": "findings.1", "issue_type": "string_type"},
    ]
    assert sensitive_value not in str(details)


def test_upstream_status_is_retained_without_exception_text() -> None:
    error = RuntimeError("raw upstream response must remain private")
    error.status_code = 429  # type: ignore[attr-defined]

    details = sanitized_failure_details(error)

    assert details["upstream_status"] == 429
    assert "raw upstream" not in str(details)
