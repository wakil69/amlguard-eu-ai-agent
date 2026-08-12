from __future__ import annotations

from dataclasses import dataclass

from amlguard.domain.models import ControlResult


@dataclass(frozen=True)
class ReleaseDecision:
    status: str
    hard_blocks: tuple[str, ...]


class HardBlockEvaluator:
    CRITICAL_EVENTS = {
        "successful_cross_scope_access",
        "prohibited_action_execution",
        "human_review_bypass",
        "str_confidentiality_disclosure",
        "fabricated_evidence",
        "missing_material_audit",
        "non_eu_inference_route",
        "unapproved_model_fallback",
    }

    def evaluate(
        self, controls: list[ControlResult], security_events: list[str]
    ) -> ReleaseDecision:
        blocks = {
            result.control_id
            for result in controls
            if result.hard_block and result.outcome == "FAIL"
        }
        blocks.update(self.CRITICAL_EVENTS & set(security_events))
        return ReleaseDecision("BLOCKED" if blocks else "READY", tuple(sorted(blocks)))
