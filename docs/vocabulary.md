# Vocabulary

This glossary explains the main terms used by AMLGuard-EU. The definitions
describe this research prototype and are not legal advice. Regulatory meanings
can vary by jurisdiction and institution.

## AML and investigation terms

| Term | Meaning in this project |
|---|---|
| AML | Anti-Money Laundering: controls intended to detect, assess, and report potentially suspicious financial activity. |
| Alert | A signal created by a deterministic monitoring rule when transactions match a defined pattern. An alert is a reason to investigate, not proof of wrongdoing. |
| Case | The durable investigation record created from an alert. It contains status, assignment, recommendation versions, and reviews. |
| Customer | The synthetic person or organization whose activity is investigated. The displayed customer ID is an identifier, not an authentication token. |
| Causal records / triggering transactions | The transactions that caused the monitoring rule to create the alert. They explain why the investigation started. |
| KYC | Know Your Customer: identity, business-purpose, risk, and related customer information used during due diligence. |
| Evidence | Case-scoped information retrieved for the investigation, such as the alert, customer profile, KYC profile, transactions, or supplemental information. |
| Material finding | An important factual or inferred statement in the recommendation, linked to supporting evidence and applicable policy IDs. |
| Counter-indicator | Evidence that reduces, contradicts, or provides an innocent explanation for the concern raised by the alert. |
| Recommendation | The agent's advisory draft: request more information, close with rationale, or escalate to a human AML analyst. It is not a final regulatory decision. |
| Rationale | The reviewer's case-specific explanation of why they approve or reject the recommendation, including relevant evidence, policy, limitations, or unresolved concerns. |
| Human review | The mandatory step in which an authorized person evaluates the agent's recommendation before the case can be completed. |
| Rework | A reviewer rejects the current draft and asks the agent to generate a new version using the review feedback. |
| Reset investigation | A deliberate deletion of the active case, its recommendations, reviews, authorization rows, and checkpoint so the alert can be investigated again with a new case ID. Historical audit and trajectory records remain. |
| STR / SAR | Suspicious transaction/activity report. AMLGuard can discuss escalation but cannot submit one. Terminology depends on the jurisdiction. |
| Tipping off | Improperly informing a customer or another person about a confidential suspicion or report. The agent has no customer-contact capability. |

## Policy and control terms

| Term | Meaning in this project |
|---|---|
| Policy corpus | The 27 locally approved regulatory excerpts that policy retrieval may supply to the agent. Internal controls are stored and executed separately. |
| Policy source | An official instrument or guidance page registered as the origin of one or more local policy excerpts. |
| Policy excerpt | The approved text stored locally under a policy ID. It may be shorter than the complete official article or instrument. |
| Policy retrieval | Selection of potentially relevant policy excerpts using alert type, jurisdiction, date, applicability facts, configured mappings, and text relevance. Retrieval does not itself prove legal applicability. |
| Applicability fact | A structured case fact used to select policy, such as customer type, KYC status, risk level, or transaction characteristics. |
| Policy citation | A policy ID attached to a finding so a reviewer can see which approved excerpt supports it. |
| Control | A deterministic check applied to the generated recommendation, such as verifying evidence and policy citations. |
| Hard block | A safety failure that prevents the recommendation from proceeding to approval, for example an invented evidence citation or critical security event. |
| B0 | The minimal live-model prompt condition used as the experimental baseline. |
| B5 | The live-model prompt condition containing explicit safeguards, including grounded citations, neutral language, and prohibited actions. |

## Security, audit, and system terms

| Term | Meaning in this project |
|---|---|
| OIDC | OpenID Connect: the login protocol used to establish who the user is and obtain role and tenant claims. Object authorization still decides which cases they may access. |
| Role | A set of permitted actions. AMLGuard retains analyst, reviewer, researcher, and full-access administrator roles. |
| Actor ID | The stable OIDC subject identifier used for authorization and audit. The frontend may show a friendlier username without changing this identifier. |
| Tenant | An organizational boundary used to prevent users from one organization accessing another organization's cases. |
| Evidence hash | A SHA-256 fingerprint used to detect whether evidence content changed. It does not encrypt evidence or prove that its source is true. |
| Audit event | A chained record of an accountable action or state change, such as starting, reviewing, or failing an investigation. |
| Trajectory | The chronological research record of an agent run, including retrieval, tool, model, validation, and review events. It is more detailed and sensitive than an operational log. |
| Checkpoint | Saved LangGraph execution state used to resume an interrupted investigation. |
| `OPEN` | A case has been created but graph execution has not yet started. |
| `RUNNING` | The graph is actively retrieving, drafting, validating, or redrafting. |
| `WAITING_FOR_INFORMATION` | The graph has paused until an authorized user supplies required information. |
| `WAITING_FOR_HUMAN_REVIEW` | Analysis and controls have completed, and the case is waiting for a reviewer decision. |
| `REWORK_REQUIRED` | A reviewer rejected the current version and requested a new draft. |
| `COMPLETED` | An authorized reviewer or administrator approved the exact recommendation version. |
| `HARD_BLOCKED` | A non-reviewable safety or integrity failure prevents approval. |
| `FAILED` | An unexpected graph-stage error stopped the investigation. Sanitized diagnostics are retained. |
| AES-256-GCM | Authenticated encryption available for restricted trajectory files. Database and checkpoint encryption are deployment responsibilities. |

## Research and evaluation terms

| Term | Meaning in this project |
|---|---|
| Synthetic data | Artificial customers and transactions created for research. They must not be treated as real banking records. |
| Deterministic | The same declared inputs and seed are intended to produce the same result, supporting repeatable tests. |
| Eden AI | The supported live-model gateway. It provides an OpenAI-compatible API, multiple model families, capability metadata, and an EU endpoint. |
| Fake model | The deterministic local recommendation provider used for development and tests when live Eden settings are absent. It does not measure live-model behavior. |
| ProofAgent harness | An optional external evaluation framework used to assess completed AMLGuard agent artifacts and trajectories. |
| Manifest | A versioned experiment configuration that fixes the dataset, scenario, model, prompt condition, evaluators, and related parameters. |
| Provenance | Metadata explaining where evidence or policy content came from and how it was retrieved. |

For the full workflow and implementation boundaries, see
[Architecture](architecture.md). For monitoring terminology, see
[Observability](observability.md).
