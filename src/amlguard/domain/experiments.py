from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from amlguard.domain.enums import JobStatus


class ExperimentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SystemConfiguration(ExperimentModel):
    configuration_id: str
    model_id: str
    context_condition: Literal["B0", "B5"]
    prompt_version: str
    tool_schema_version: str
    graph_version: str
    estimated_session_cost_eur: Decimal = Field(default=Decimal("0"), ge=0)


ProofAgentMetric = Literal[
    "task_success",
    "hallucination_resistance",
    "safety",
    "instruction_following",
    "tool_use",
]

PROOFAGENT_COMPLIANCE_FRAMEWORKS = frozenset(
    {
        "au_privacy",
        "canada_aida",
        "ccpa",
        "china_genai",
        "colorado_ai_act",
        "dpdp_india",
        "eu_ai_act",
        "faa",
        "fda_samd",
        "fedramp",
        "finra_sec",
        "gdpr",
        "glba",
        "hipaa",
        "iso_27001",
        "iso_42001",
        "lgpd",
        "nist_ai_rmf",
        "nyc_ll144",
        "pci_dss",
        "pdpa_sg",
        "pipeda",
        "popia",
        "soc2",
        "uk_gdpr",
    }
)


def default_proofagent_metrics() -> list[ProofAgentMetric]:
    return [
        "task_success",
        "hallucination_resistance",
        "safety",
        "instruction_following",
    ]


class ProofAgentGovernanceProfileConfig(ExperimentModel):
    """Risk intake used by ProofAgent's deterministic governance classifier."""

    name: str = Field(min_length=1)
    use_case: Literal[
        "social_scoring",
        "manipulation",
        "biometric_categorization",
        "emotion_recognition_work",
        "creditworthiness",
        "insurance",
        "hiring",
        "healthcare",
        "essential_services",
        "education_scoring",
        "law_enforcement",
        "critical_infrastructure",
        "customer_support",
        "virtual_assistant",
        "content_generation",
        "recommendations",
        "coding_assistant",
        "internal_productivity",
        "data_analysis",
        "research",
        "other",
        "ide_assistant",
        "autonomous_coding",
        "devops_automation",
        "data_pipeline_agent",
    ] = "other"
    autonomy_level: Literal["L0", "L1", "L2", "L3", "L4"] = "L2"
    data_sensitivity: Literal["none", "internal", "confidential", "pii", "phi"] = "pii"
    region: Literal["eu", "us", "global"] = "eu"
    human_oversight: bool = True
    takes_consequential_actions: bool = False
    fail_on: Literal["pass", "review", "block"] = "block"


class ProofAgentEvaluationConfig(ExperimentModel):
    """Frozen configuration for the optional ProofAgent artifact evaluator."""

    harness_version: Literal["0.11.0"] = "0.11.0"
    harness_llm: str = Field(min_length=1)
    fallback_llm: str | None = None
    consensus: Literal["independent", "delphi", "debate"] = "delphi"
    metrics: list[ProofAgentMetric] = Field(
        default_factory=default_proofagent_metrics, min_length=1
    )
    seed: int = 42
    max_tokens: int = Field(default=8192, ge=512, le=65536)
    context_budget_tokens: int | None = Field(default=None, ge=2048)
    assess_context: bool = False
    assess_compliance: bool = False
    compliance_frameworks: list[str] = Field(default_factory=list)
    compliance_evidence_registry: str | None = None
    governance_profile: ProofAgentGovernanceProfileConfig | None = None
    estimated_evaluation_cost_eur: Decimal = Field(default=Decimal("0"), ge=0)
    failure_policy: Literal["fail_job", "record_error"] = "fail_job"

    @model_validator(mode="after")
    def configuration_is_coherent(self) -> ProofAgentEvaluationConfig:
        if len(self.metrics) != len(set(self.metrics)):
            raise ValueError("ProofAgent metrics must be unique")
        if self.assess_compliance and not self.compliance_frameworks:
            raise ValueError(
                "ProofAgent compliance assessment requires at least one framework"
            )
        if not self.assess_compliance and self.compliance_frameworks:
            raise ValueError(
                "ProofAgent compliance frameworks require assess_compliance=true"
            )
        if not self.assess_compliance and self.compliance_evidence_registry:
            raise ValueError(
                "ProofAgent compliance evidence requires assess_compliance=true"
            )
        if self.compliance_evidence_registry:
            registry = self.compliance_evidence_registry.replace("\\", "/")
            if registry.startswith("/") or ":" in registry or ".." in registry.split("/"):
                raise ValueError(
                    "ProofAgent compliance evidence registry must be a repository-relative path"
                )
        unknown_frameworks = sorted(
            set(self.compliance_frameworks) - PROOFAGENT_COMPLIANCE_FRAMEWORKS
        )
        if unknown_frameworks:
            raise ValueError(
                "unsupported ProofAgent compliance frameworks: "
                + ", ".join(unknown_frameworks)
            )
        return self


class ExperimentManifest(ExperimentModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: UUID = Field(default_factory=uuid4)
    name: str
    git_commit: str
    dependency_lock_hash: str
    dataset_version: str
    dataset_seed: int
    scenario_pack: Literal["development", "validation", "regression", "held_out"]
    scenario_version: str
    policy_version: str
    control_version: str
    endpoint_class: Literal["EU"] = "EU"
    configurations: list[SystemConfiguration] = Field(min_length=1)
    repetitions: int = Field(ge=1, le=20)
    evaluator_version: str
    juror_mode: Literal["none", "single", "three"] = "single"
    proofagent: ProofAgentEvaluationConfig | None = None
    telemetry_version: str
    randomization_seed: int
    cost_ceiling_eur: Decimal = Field(gt=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def configurations_are_unique(self) -> ExperimentManifest:
        ids = [item.configuration_id for item in self.configurations]
        if len(ids) != len(set(ids)):
            raise ValueError("configuration IDs must be unique")
        return self


class ExperimentJob(ExperimentModel):
    job_id: UUID = Field(default_factory=uuid4)
    experiment_id: UUID
    session_key: str
    configuration_id: str
    scenario_id: str
    repetition: int = Field(ge=1)
    status: JobStatus = JobStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    not_before: datetime = Field(default_factory=lambda: datetime.now(UTC))
    estimated_cost_eur: Decimal = Field(default=Decimal("0"), ge=0)


class EvaluationResult(ExperimentModel):
    evaluation_id: UUID = Field(default_factory=uuid4)
    session_key: str
    evaluator_type: Literal["deterministic", "llm_assisted", "proofagent"]
    evaluator_version: str
    metrics: dict[str, float]
    evidence_references: list[str] = Field(default_factory=list)
    hard_blocks: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityResult(ExperimentModel):
    model_id: str
    structured_output_reliability: float = Field(ge=0, le=1)
    tool_call_correctness: float = Field(ge=0, le=1)
    instruction_adherence: float = Field(ge=0, le=1)
    context_retrieval: float = Field(ge=0, le=1)
    latency_reliability: float = Field(ge=0, le=1)
    eu_catalogue_eligible: bool
    no_fallback_verified: bool
    cost_per_million_tokens_eur: Decimal | None = None

    @property
    def capability_score(self) -> float:
        return (
            0.30 * self.structured_output_reliability
            + 0.30 * self.tool_call_correctness
            + 0.20 * self.instruction_adherence
            + 0.10 * self.context_retrieval
            + 0.10 * self.latency_reliability
        )
