from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from amlguard.domain.enums import ReviewStatus
from amlguard.policy.models import (
    AlertPolicyMapping,
    PolicyChunk,
    PolicyControl,
    PolicySource,
)

if TYPE_CHECKING:
    from amlguard.policy.retrieval import PolicyIndex


def load_sources(path: Path) -> list[PolicySource]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [PolicySource.model_validate(item) for item in payload["sources"]]


def load_chunks(path: Path) -> list[PolicyChunk]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    chunks = []
    for item in payload["chunks"]:
        if not item.get("content_hash"):
            item["content_hash"] = hashlib.sha256(item["text"].encode()).hexdigest()
        chunks.append(PolicyChunk.model_validate(item))
    return chunks


def load_controls(path: Path) -> list[PolicyControl]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [PolicyControl.model_validate(item) for item in payload["controls"]]


def load_alert_policy_mappings(
    path: Path,
    chunks: list[PolicyChunk],
) -> list[AlertPolicyMapping]:
    if not path.is_file():
        raise FileNotFoundError(f"alert policy mapping file not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    mappings = [AlertPolicyMapping.model_validate(item) for item in payload["mappings"]]
    rule_ids = [mapping.alert_rule_id for mapping in mappings]
    duplicate_rules = sorted(
        rule_id for rule_id in set(rule_ids) if rule_ids.count(rule_id) > 1
    )
    if duplicate_rules:
        raise ValueError(f"duplicate alert rule IDs in policy mappings: {duplicate_rules}")
    known_policy_ids = {chunk.policy_id for chunk in chunks}
    mapped_rules = [
        rule
        for mapping in mappings
        for rule in [*mapping.always_policy_rules, *mapping.conditional_policy_rules]
    ]
    unknown_policy_ids = sorted(
        {
            rule.policy_id for rule in mapped_rules if rule.policy_id not in known_policy_ids
        }
    )
    if unknown_policy_ids:
        raise ValueError(f"alert mappings reference unknown policy IDs: {unknown_policy_ids}")
    unapproved_policy_ids = sorted(
        {
            rule.policy_id
            for rule in mapped_rules
            if not next(chunk for chunk in chunks if chunk.policy_id == rule.policy_id).approved
        }
    )
    if unapproved_policy_ids:
        raise ValueError(
            f"alert mappings reference unapproved policy IDs: {unapproved_policy_ids}"
        )
    rejected_mappings = sorted(
        mapping.alert_rule_id
        for mapping in mappings
        if mapping.review_status is ReviewStatus.REJECTED
    )
    if rejected_mappings:
        raise ValueError(f"rejected alert policy mappings cannot be loaded: {rejected_mappings}")
    for mapping in mappings:
        if any(rule.when_all or rule.when_any for rule in mapping.always_policy_rules):
            raise ValueError(
                f"always policy rules cannot have conditions: {mapping.alert_rule_id}"
            )
        if any(
            not rule.when_all and not rule.when_any
            for rule in mapping.conditional_policy_rules
        ):
            raise ValueError(
                f"conditional policy rules require conditions: {mapping.alert_rule_id}"
            )
    from amlguard.policy.applicability import POLICY_FACT_IDS

    unknown_fact_ids = sorted(
        {
            fact_id
            for mapping in mappings
            for rule in mapping.conditional_policy_rules
            for fact_id in [*rule.when_all, *rule.when_any]
            if fact_id not in POLICY_FACT_IDS
        }
    )
    if unknown_fact_ids:
        raise ValueError(f"alert mappings reference unknown policy facts: {unknown_fact_ids}")
    return mappings


def load_corpus(root: Path) -> list[PolicyChunk]:
    """Load and validate every policy excerpt in a configured corpus root."""
    source_path = root / "source_register.yaml"
    excerpt_root = root / "approved_excerpts"
    if not source_path.is_file():
        raise FileNotFoundError(f"policy source register not found: {source_path}")
    excerpt_paths = sorted(excerpt_root.glob("*.yaml"))
    if not excerpt_paths:
        raise FileNotFoundError(f"no policy excerpt files found in: {excerpt_root}")

    sources = load_sources(source_path)
    source_ids = [source.source_id for source in sources]
    duplicate_sources = sorted(
        source_id for source_id in set(source_ids) if source_ids.count(source_id) > 1
    )
    if duplicate_sources:
        raise ValueError(f"duplicate policy source IDs: {duplicate_sources}")
    known_sources = {source.source_id for source in sources}
    chunks = [chunk for path in excerpt_paths for chunk in load_chunks(path)]
    if not chunks:
        raise ValueError("policy corpus contains no excerpts")
    unknown_sources = sorted({chunk.source_id for chunk in chunks} - known_sources)
    if unknown_sources:
        raise ValueError(f"policy excerpts reference unknown sources: {unknown_sources}")
    policy_ids = [chunk.policy_id for chunk in chunks]
    duplicate_ids = sorted(
        policy_id for policy_id in set(policy_ids) if policy_ids.count(policy_id) > 1
    )
    if duplicate_ids:
        raise ValueError(f"duplicate policy IDs: {duplicate_ids}")
    rejected_sources = {
        source.source_id for source in sources if source.review_status is ReviewStatus.REJECTED
    }
    approved_from_rejected_sources = sorted(
        chunk.policy_id
        for chunk in chunks
        if chunk.approved and chunk.source_id in rejected_sources
    )
    if approved_from_rejected_sources:
        raise ValueError(
            "approved policy excerpts reference rejected sources: "
            f"{approved_from_rejected_sources}"
        )
    return chunks


def load_policy_index(root: Path) -> PolicyIndex:
    from amlguard.policy.retrieval import PolicyIndex

    chunks = load_corpus(root)
    mappings = load_alert_policy_mappings(root / "alert_policy_mappings.yaml", chunks)
    return PolicyIndex(chunks, mappings)
