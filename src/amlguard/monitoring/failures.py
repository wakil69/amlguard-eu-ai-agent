from __future__ import annotations

from typing import Any

from pydantic import ValidationError

_ERROR_CODES = {
    "InferenceConfigurationError": (
        "INFERENCE_CONFIGURATION_REJECTED",
        "The model or structured-output configuration was rejected.",
    ),
    "InferenceAuthenticationError": (
        "INFERENCE_AUTHENTICATION_REJECTED",
        "The inference credential was rejected or lacks permission.",
    ),
    "InferenceRateLimitError": (
        "INFERENCE_RATE_LIMITED",
        "The inference account or provider is rate limited.",
    ),
    "InferenceServiceError": (
        "INFERENCE_SERVICE_UNAVAILABLE",
        "The inference service timed out or returned a service error.",
    ),
    "TimeoutError": ("EXECUTION_TIMEOUT", "The graph stage exceeded its time limit."),
    "ConnectionError": (
        "DEPENDENCY_UNAVAILABLE",
        "A required dependency could not be reached.",
    ),
}


def sanitized_failure_details(error: Exception) -> dict[str, Any]:
    """Return useful diagnostics without exception text, values, or model output."""
    if isinstance(error, ValidationError):
        issues = [
            {
                "location": ".".join(str(part) for part in item.get("loc", ())) or "root",
                "issue_type": str(item.get("type", "validation_error")),
            }
            for item in error.errors(include_input=False, include_url=False)
        ][:20]
        return {
            "error_code": "SCHEMA_VALIDATION_FAILED",
            "safe_message": "Structured model output did not match the required schema.",
            "validation_issues": issues,
            "validation_issue_count": error.error_count(),
        }

    error_code, safe_message = _ERROR_CODES.get(
        type(error).__name__,
        ("UNEXPECTED_EXECUTION_ERROR", "The graph stage failed unexpectedly."),
    )
    details: dict[str, Any] = {
        "error_code": error_code,
        "safe_message": safe_message,
        "validation_issues": [],
        "validation_issue_count": 0,
    }
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and 400 <= status_code <= 599:
        details["upstream_status"] = status_code
    return details
