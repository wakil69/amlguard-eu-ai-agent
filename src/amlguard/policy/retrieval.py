from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from amlguard.policy.models import (
    AlertPolicyMapping,
    MappedPolicyRule,
    PolicyApplicabilityFact,
    PolicyChunk,
    PolicyRetrievalReason,
    PolicyRetrievalRecord,
    PolicyStage,
)


@dataclass(frozen=True)
class PolicyMatch:
    chunk: PolicyChunk
    score: float
    reason: PolicyRetrievalReason
    stage: PolicyStage | None
    matched_fact_ids: tuple[str, ...]
    explanation: str

    def to_record(self) -> PolicyRetrievalRecord:
        return PolicyRetrievalRecord(
            policy_id=self.chunk.policy_id,
            score=self.score,
            reason=self.reason,
            stage=self.stage,
            matched_fact_ids=list(self.matched_fact_ids),
            explanation=self.explanation,
        )


class PolicyIndex:
    """Approved, effective-date-first retrieval with deterministic keyword scoring."""

    def __init__(
        self,
        chunks: list[PolicyChunk],
        alert_mappings: list[AlertPolicyMapping] | None = None,
    ) -> None:
        self.chunks = chunks
        mappings = alert_mappings or []
        self.alert_mappings = {item.alert_rule_id: item for item in mappings}
        if len(self.alert_mappings) != len(mappings):
            raise ValueError("duplicate alert rule IDs in policy mappings")

        known_policy_ids = {chunk.policy_id for chunk in chunks}
        unknown_policy_ids = sorted(
            {
                rule.policy_id
                for mapping in mappings
                for rule in [
                    *mapping.always_policy_rules,
                    *mapping.conditional_policy_rules,
                ]
                if rule.policy_id not in known_policy_ids
            }
        )
        if unknown_policy_ids:
            raise ValueError(f"alert mappings reference unknown policy IDs: {unknown_policy_ids}")

    def search(
        self,
        query: str,
        *,
        jurisdiction: str,
        as_of_date: date,
        limit: int = 5,
    ) -> list[tuple[PolicyChunk, float]]:
        if not 1 <= limit <= 20:
            raise ValueError("policy result limit must be between 1 and 20")
        tokens = set(re.findall(r"[a-zA-ZÀ-ÿ0-9]+", query.lower()))
        eligible = [
            chunk
            for chunk in self.chunks
            if chunk.approved
            and chunk.jurisdiction in {jurisdiction, "EU", "INTL"}
            and (chunk.effective_from is None or chunk.effective_from <= as_of_date)
            and (chunk.effective_to is None or chunk.effective_to >= as_of_date)
        ]
        scored = []
        for chunk in eligible:
            searchable = " ".join(
                [chunk.policy_id, chunk.provision, chunk.text, *chunk.topics]
            )
            haystack = set(re.findall(r"[a-zA-ZÀ-ÿ0-9]+", searchable.lower()))
            score = len(tokens & haystack) / max(1, len(tokens))
            if score:
                scored.append((chunk, score))
        return sorted(scored, key=lambda item: (-item[1], item[0].policy_id))[:limit]

    def search_for_alert(
        self,
        query: str,
        *,
        alert_rule_id: str,
        jurisdiction: str,
        as_of_date: date,
        applicability_facts: list[PolicyApplicabilityFact] | None = None,
        limit: int = 5,
    ) -> list[PolicyMatch]:
        if not 1 <= limit <= 20:
            raise ValueError("policy result limit must be between 1 and 20")
        mapping = self.alert_mappings.get(alert_rule_id)
        if mapping is None:
            raise ValueError(f"no policy mapping for alert rule {alert_rule_id}")
        facts_by_id = {fact.fact_id: fact for fact in applicability_facts or []}
        fact_ids = set(facts_by_id)
        selected_rules = [
            *mapping.always_policy_rules,
            *(
                rule
                for rule in mapping.conditional_policy_rules
                if self._rule_applies(rule, fact_ids)
            ),
        ]
        eligible = {
            chunk.policy_id: chunk
            for chunk in self.chunks
            if chunk.approved
            and chunk.jurisdiction in {jurisdiction, "EU", "INTL"}
            and (chunk.effective_from is None or chunk.effective_from <= as_of_date)
            and (chunk.effective_to is None or chunk.effective_to >= as_of_date)
        }
        eligible_rules = [rule for rule in selected_rules if rule.policy_id in eligible]
        if limit < len(eligible_rules):
            raise ValueError(
                f"policy result limit {limit} is smaller than the "
                f"{len(eligible_rules)} applicable mapped policies for {alert_rule_id}"
            )
        mapped: list[PolicyMatch] = []
        always_ids = {rule.policy_id for rule in mapping.always_policy_rules}
        for rule in eligible_rules:
            chunk = eligible[rule.policy_id]
            matched_fact_ids = tuple(
                [
                    *rule.when_all,
                    *(fact_id for fact_id in rule.when_any if fact_id in facts_by_id),
                ]
            )
            mapped.append(
                PolicyMatch(
                    chunk=chunk,
                    score=1.0,
                    reason=(
                        "alert_mapping"
                        if rule.policy_id in always_ids
                        else "conditional_mapping"
                    ),
                    stage=rule.stage,
                    matched_fact_ids=matched_fact_ids,
                    explanation=rule.rationale,
                )
            )
        mapped_ids = {match.chunk.policy_id for match in mapped}
        contextual = [
            PolicyMatch(
                chunk=chunk,
                score=score,
                reason="contextual_keyword",
                stage=None,
                matched_fact_ids=(),
                explanation="The policy shares terms with the bounded investigation query.",
            )
            for chunk, score in self.search(
                query,
                jurisdiction=jurisdiction,
                as_of_date=as_of_date,
                limit=20,
            )
            if chunk.policy_id not in mapped_ids
        ]
        return [*mapped, *contextual[: limit - len(mapped)]]

    @staticmethod
    def _rule_applies(rule: MappedPolicyRule, fact_ids: set[str]) -> bool:
        return set(rule.when_all) <= fact_ids and (
            not rule.when_any or bool(set(rule.when_any) & fact_ids)
        )


def validate_policy_citations(cited_ids: list[str], retrieved: list[PolicyChunk]) -> list[str]:
    available = {item.policy_id for item in retrieved}
    return sorted(set(cited_ids) - available)
