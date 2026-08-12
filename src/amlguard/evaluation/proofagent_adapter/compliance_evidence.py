from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from amlguard.domain.models import ControlResult, InvestigationRecommendation

MAX_PACKAGE_CHARS = 7_900


@dataclass(frozen=True)
class ComplianceEvidencePackage:
    text: str
    metadata: dict[str, Any]


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n[truncated by AMLGuard compliance-evidence budget]"
    return text[: max(0, limit - len(marker))] + marker


def _compact_json(value: object, limit: int) -> str:
    return _bounded(json.dumps(value, sort_keys=True, default=str), limit)


def _resolve_inside(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"compliance evidence path escapes repository root: {relative_path}"
        ) from exc
    return candidate


def _markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    )
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"compliance evidence section not found: {heading}")
    return match.group(1).strip()


def load_documentary_evidence(
    registry_path: Path, *, repository_root: Path
) -> list[dict[str, str]]:
    """Load only explicitly registered, bounded repository-document excerpts."""
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("compliance evidence registry must use schema_version 1.0")
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("compliance evidence registry requires a documents list")

    loaded: list[dict[str, str]] = []
    for item in documents:
        if not isinstance(item, dict):
            raise ValueError("compliance evidence document entries must be objects")
        document_id = str(item.get("document_id") or "").strip()
        relative_path = str(item.get("path") or "").strip()
        approval_status = str(item.get("approval_status") or "").strip()
        sections = item.get("sections")
        if not document_id or not relative_path or not approval_status:
            raise ValueError("document_id, path, and approval_status are required")
        if not isinstance(sections, list) or not sections:
            raise ValueError(f"document {document_id} requires at least one section")

        source = _resolve_inside(repository_root, relative_path)
        if not source.is_file():
            raise FileNotFoundError(f"registered compliance evidence does not exist: {source}")
        content = source.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        for section_item in sections:
            if not isinstance(section_item, dict):
                raise ValueError(f"document {document_id} section entries must be objects")
            heading = str(section_item.get("heading") or "").strip()
            max_chars = int(section_item.get("max_chars") or 0)
            if not heading or max_chars < 100 or max_chars > 1_500:
                raise ValueError(
                    f"document {document_id} sections require a heading and max_chars 100..1500"
                )
            excerpt = (
                content.strip()
                if heading == "$document"
                else _markdown_section(content, heading)
            )
            loaded.append(
                {
                    "document_id": document_id,
                    "source_path": relative_path,
                    "source_sha256": digest,
                    "approval_status": approval_status,
                    "section": heading,
                    "excerpt": _bounded(excerpt, max_chars),
                }
            )
    return loaded


def _documentary_block(items: list[dict[str, str]]) -> str:
    sources: dict[str, dict[str, str]] = {}
    excerpts: list[str] = []
    for item in items:
        document_id = item["document_id"]
        sources.setdefault(
            document_id,
            {
                "path": item["source_path"],
                "sha256": item["source_sha256"],
                "approval": item["approval_status"],
            },
        )
        excerpt = item["excerpt"].replace("\r", " ").replace("\n", " ")
        if len(excerpt) > 145:
            excerpt = excerpt[:141] + " [...]"
        excerpts.append(f"[{document_id} / {item['section']}] {excerpt}")
    source_lines = [
        f"- {document_id}: path={value['path']}; sha256={value['sha256']}; "
        f"approval={value['approval']}"
        for document_id, value in sources.items()
    ]
    return _bounded("\n".join([*source_lines, *excerpts]), 1_900)


def build_compliance_evidence_package(
    *,
    recommendation: InvestigationRecommendation,
    system_prompt: str,
    tool_calls: list[dict[str, Any]],
    control_results: list[ControlResult],
    hard_blocks: list[str],
    governance: dict[str, Any] | None,
    runtime_governance: dict[str, Any],
    governance_readiness: dict[str, Any],
    documentary_evidence: list[dict[str, str]],
) -> ComplianceEvidencePackage:
    """Build the bounded evidence excerpt consumed by ProofAgent 0.11 compliance.

    ProofAgent artifact mode gives its compliance assessor ``agent_trace`` in
    preference to the synthetic artifact turn. This package therefore includes
    both the actual agent output and the trace, while clearly separating runtime
    behavior from repository documentation.
    """
    sections = [
        "# AMLGuard compliance evidence package",
        (
            "This package separates agent behavior from documentary evidence. "
            "A document's presence or hash does not prove legal applicability, "
            "organizational approval, operational enforcement, or compliance."
        ),
        (
            "## Scope limitation\nControls requiring deployment records, contracts, "
            "approvals, organizational procedures, independent audits, or real-data "
            "operations remain not evaluated unless registered evidence demonstrates them."
        ),
        "## Agent output (verbatim structured recommendation)\n"
        + _compact_json(recommendation.model_dump(mode="json"), 2_300),
        "## Producing system instructions\n" + _bounded(system_prompt, 1_550),
        "## Native deterministic control results\n"
        + _compact_json(
            {
                "control_results": [item.model_dump(mode="json") for item in control_results],
                "hard_blocks": hard_blocks,
            },
            750,
        ),
        "## Runtime governance evidence\n" + _compact_json(runtime_governance, 850),
        "## Sanitized execution trace\n" + _compact_json(tool_calls, 700),
        "## Declared governance profile\n" + _compact_json(governance or {}, 450),
        "## Organizational governance readiness\n"
        + _compact_json(governance_readiness, 750),
        "## Registered documentary evidence\n"
        + _bounded(_documentary_block(documentary_evidence), 650),
    ]
    text = _bounded("\n\n".join(sections), MAX_PACKAGE_CHARS)
    metadata = {
        "schema_version": "1.0",
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "character_count": len(text),
        "document_sources": sorted(
            {
                item["source_path"]
                for item in documentary_evidence
                if item.get("source_path")
            }
        ),
        "document_hashes": {
            item["source_path"]: item["source_sha256"]
            for item in documentary_evidence
            if item.get("source_path") and item.get("source_sha256")
        },
        "document_sections": len(documentary_evidence),
        "includes_agent_output": True,
        "includes_system_prompt": True,
        "includes_native_controls": True,
        "includes_execution_trace": True,
        "includes_runtime_governance": True,
        "includes_governance_readiness": True,
    }
    return ComplianceEvidencePackage(text=text, metadata=metadata)
