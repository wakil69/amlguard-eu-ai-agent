"""Optional, version-pinned ProofAgent adapter boundary."""

from amlguard.evaluation.proofagent_adapter.evaluator import (
    ProofAgentArtifactEvaluator,
    ProofAgentExecution,
)
from amlguard.evaluation.proofagent_adapter.result_normalizer import normalize_report
from amlguard.evaluation.proofagent_adapter.version_check import require_supported_version

__all__ = [
    "ProofAgentArtifactEvaluator",
    "ProofAgentExecution",
    "normalize_report",
    "require_supported_version",
]
