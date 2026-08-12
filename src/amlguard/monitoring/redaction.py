from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "account_number",
    "document_number",
    "address",
    "raw_prompt",
    "raw_output",
}
TOKEN_PATTERNS = (
    re.compile(r"(?i)bearer\s+[a-z0-9._-]+"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)\S+"),
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        result = value
        for pattern in TOKEN_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result
    return value
