# Limitations

## How to read this register

This page records what AMLGuard-EU `0.1.0` does **not** establish. “Implemented”
means a narrow code property is present; it does not imply production assurance,
legal compliance, or effectiveness on real cases.

## Scope and validity

- All customer, account, KYC, transaction, counterparty, and alert records are
  generated. Results do not demonstrate performance on real bank data,
  languages, institutions, products, typologies, customer populations, or
  operational workflows.
- Scenarios are deterministic templates rotating through eleven families. They
  do not represent a measured prevalence distribution or the full diversity of
  AML/CFT behavior.
- Every scenario mapping is researcher-curated. None currently carries the
  schema's AML-expert-reviewed provenance.
- The fake model is designed for reproducible plumbing tests and primarily
  follows deterministic alert rule IDs. Its results are not evidence of LLM
  quality. It does not branch on B0 versus B5, so fake-model results cannot
  measure the instruction-context effect.
- Live model behavior, provider routing, catalogue availability, latency, price,
  and evaluator behavior can change outside a frozen manifest.
- Three repetitions characterize limited run variation; they cannot capture
  long-term provider/model drift.
- The target 900 sessions have not been justified by a completed power or
  precision simulation.

## Investigation behavior

- The active runtime validation proves that a cited evidence ID was retrieved;
  it does not prove that the cited content entails the claim, that all important
  evidence was used, or that the recommendation is legally/policy correct.
- Evidence content hashes provide fingerprints for later integrity and
  reproducibility checks, and the ledger rejects reuse of an evidence ID with a
  different hash. The active graph does not automatically recompute each hash
  against an independently protected reference. Hashing neither validates the
  source's truth nor prevents an actor who can replace both content and hash
  from concealing a change.
- `mandatory_evidence_ids` are empty in the generated catalog, making mandatory-
  evidence recall uninformative until curated.
- Policy retrieval evaluates governed always/conditional rules against bounded
  evidence-derived facts, then fills remaining slots using deterministic
  keyword overlap. The facts are limited by the synthetic data fields, and
  untrusted evidence descriptions can still influence contextual slots.
  Neither a curated mapping nor citation validation proves legal relevance,
  correct interpretation, or complete coverage of applicable obligations.
- Supplemental information is accepted only as bounded JSON, not as a verified
  source document. It becomes case-scoped evidence and can influence the next
  model draft, but the system does not verify its truth, authorship, or
  completeness. Repeated requests for information have no case-level round or
  cost ceiling yet.
- The investigation graph now aggregates citation failures and trusted
  critical security events into a non-reviewable hard-block decision. Evidence
  scope and prohibited authorized tool execution have local invariant checks;
  several other event types still depend on a trusted monitoring component to
  detect and record them. Experiment and ProofAgent hard blocks remain separate
  evaluation results rather than case-state transitions.
- The experiment worker stops at the first information or human-review
  interrupt. It does not supply requested information or measure reviewer
  decisions, analyst time, edit burden, inter-reviewer variance, or downstream
  case outcomes.
- The graph uses one fixed staged workflow. The study does not compare agent
  autonomy, model-directed tool selection, alternative graph topologies, or
  multi-step planning strategies.

## Security and access control

- Case, evidence, information, trace, and review APIs enforce tenant and
  investigator/reviewer assignment in the application. This is not PostgreSQL
  row-level security: researchers retain tenant-wide reads, administrators
  retain global application access, and infrastructure/database operators
  remain outside the application authorization boundary.
- Development authentication bypass trusts headers and is unsafe on an
  untrusted network.
- Mutation endpoints require an idempotency header, but only investigation start
  uses a process-local response cache. Idempotency is neither complete nor
  durable.
- There is no application rate limiter, request quota, API body-size policy,
  user-level cost budget, or full denial-of-service protection.
- The hash-chained audit is tamper-evident only while the chain survives; it is
  not immutable, externally anchored, signed, or independently witnessed.
- Artifact files are authenticated and encrypted, but key lifecycle, rotation,
  revocation, access logs, backup, retention, and deletion are not implemented.
- Redaction is a helper and collector configuration, not a proof that every log,
  trace, metric, error, or trajectory is free of sensitive values.
- Database TLS, at-rest encryption, least-privilege roles, row-level security,
  network policy, backup protection, host hardening, and penetration testing are
  outside the repository. There is no application-level encryption of
  individual evidence values in source tables or LangGraph checkpoints;
  AES-256-GCM currently protects restricted artifact files only.
- Dependency locks and version constraints do not replace SBOMs, image pinning,
  signature verification, vulnerability management, or supply-chain review.

## Data protection and governance

- Synthetic customer data lowers privacy risk but does not eliminate personal
  data about users/reviewers in identity claims, actor IDs, free text, network
  logs, or provider account records.
- No controller, processor, DPO, product owner, AML control owner, privacy owner,
  or technical owner is assigned in the governance profile.
- No approved legal basis, privacy notice, rights process, retention schedule,
  deletion job, breach workflow, record of processing, or formal DPIA exists.
- An Eden EU hostname does not prove processing location, no fallback,
  subprocessor geography, transfer compliance, retention, deletion, or absence
  of training use.
- PostgreSQL records, LangGraph checkpoints, and encrypted artifacts have no
  automated retention. Only Loki declares a seven-day retention period.
- Raw trajectories contain complete synthetic evidence and recommendations and
  remain available in process memory to the researcher trace route.

## Regulatory and policy coverage

- Regulatory mappings are research interpretations and do not establish
  compliance with French AML/CFT law, GDPR, the EU AI Act, DORA, or any
  institution-specific obligation.
- The policy corpus contains 27 focused, researcher-curated chunks covering core
  French AML investigation themes. It remains incomplete, uses paraphrases, and
  has not received legal or AML-expert approval; source document hashes are also
  unset.
- Regulation (EU) 2024/1624 is a future-readiness target at the 11 August 2026
  baseline because it generally applies from 10 July 2027.
- AI Act timing/classification changed with Regulation (EU) 2026/1744; any
  production decision must re-check the consolidated law at that time.
- The system neither connects to TRACFIN nor implements the institution's full
  vigilance, reporting, confidentiality, governance, recordkeeping, or
  supervisory obligations.

## Experiment and statistics

- The worker records estimated session cost, not actual tokens, invoices, or
  provider-billed cost.
- Deterministic metric zero-denominator behavior returns 1.0 and can make empty
  requirements look perfect; this must be frozen or revised before inference.
- Provider errors are retried only for `TimeoutError` and `ConnectionError`;
  provider SDK exception taxonomies may not map cleanly to those classes.
- Guarded graph stages emit `FAILED` with sanitized error metadata. Audit and
  trajectory failure events are best effort after the status update; a
  repository outage can prevent durable status and audit persistence entirely.
- The current analysis helper fits one linear mixed model to a generic score. It
  does not implement the full statistical plan, binary models, bootstrap,
  multiplicity control, effect sizes, diagnostics, or missing-data sensitivity.
- Optional native LLM juries are not part of the default worker run. ProofAgent
  artifact evaluation is integrated but runs only when explicitly frozen in an
  experiment manifest; it does not test multi-turn manipulation resistance.
- The leakage scanner searches a few literal markers. It cannot detect semantic,
  memorized, indirect, or human leakage.
- Random seeds make local generation/job order reproducible, not remote model
  output or distributed scheduling timing.

## Operational maturity

- The readiness endpoint now checks PostgreSQL, OIDC discovery, artifact-store
  writability, telemetry health, initialized policy/runtime components, and
  configured live-inference reachability. These are shallow dependency probes,
  not synthetic end-to-end transactions through every provider operation.
- The application and worker are separate, but there is no production scheduler,
  autoscaling policy, dead-letter workflow, operator runbook, SLO, incident
  response, disaster recovery, or tested restore process.
- Artifact metadata has an ORM model but the recorder does not insert it.
- The migration creates a `policy` schema but no policy tables are modeled.
- Dashboard metric names and Prometheus alert definitions are tested. The local
  Alertmanager has no external receiver, so production notification routing,
  credentials, escalation policy, and delivery testing remain deployment work.
- Structured operational events are centrally redacted, and the collector
  drops additional sensitive attributes. Arbitrary third-party instrumentation
  could introduce new attribute names, so exported telemetry still requires
  continuous canary scanning and access controls.
- The local/Docker examples use development defaults and must not be treated as a
  hardened deployment blueprint.

## Consequence for interpretation

The platform is suitable for testing architecture, deterministic controls,
synthetic scenario execution, and research-pipeline mechanics. It is not ready
to support real investigations, customer decisions, suspicious reporting,
production security, regulatory assurance, or claims about improved AML
outcomes. Any publication should report these limitations next to results and
avoid generalizing beyond the frozen synthetic design.
