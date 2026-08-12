from enum import StrEnum


class RecommendationKind(StrEnum):
    CLOSE_WITH_RATIONALE = "CLOSE_WITH_RATIONALE"
    REQUEST_MORE_INFORMATION = "REQUEST_MORE_INFORMATION"
    ESCALATE_TO_HUMAN_AML_ANALYST = "ESCALATE_TO_HUMAN_AML_ANALYST"


class CaseStatus(StrEnum):
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    WAITING_FOR_INFORMATION = "WAITING_FOR_INFORMATION"
    WAITING_FOR_HUMAN_REVIEW = "WAITING_FOR_HUMAN_REVIEW"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    HARD_BLOCKED = "HARD_BLOCKED"


class ReviewAction(StrEnum):
    APPROVE = "APPROVE"
    EDIT_AND_APPROVE = "EDIT_AND_APPROVE"
    REJECT_AND_REQUEST_REWORK = "REJECT_AND_REQUEST_REWORK"


class NormativeType(StrEnum):
    LAW = "law"
    REGULATION = "regulation"
    REGULATORY_GUIDANCE = "regulatory_guidance"
    FATF_STANDARD = "fatf_standard"
    INTERNAL_POLICY = "internal_policy"
    RESEARCH_INTERPRETATION = "research_interpretation"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReviewStatus(StrEnum):
    RESEARCHER_CURATED = "researcher_curated"
    EXPERT_REVIEWED = "expert_reviewed"
    REJECTED = "rejected"
