from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from amlguard.evaluation.proofagent_adapter.version_check import require_supported_version


@dataclass(frozen=True)
class CanonicalAgentResponse:
    text: str
    tools_called: list[dict[str, Any]]
    retrievals: list[dict[str, Any]]
    memory_snapshot: dict[str, Any]

    def to_proofagent(self) -> object:
        require_supported_version()
        from proofagent_harness import AgentResponse

        return AgentResponse(
            text=self.text,
            tools_called=self.tools_called,
            retrievals=self.retrievals,
            memory_snapshot=self.memory_snapshot,
        )
