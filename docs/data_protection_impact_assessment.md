# DPIA-style research assessment

## Status and decision

**Assessment date:** 10 August 2026  
**Scope:** repository version `0.1.0`, synthetic research use only  
**Decision:** acceptable for controlled synthetic-data research after local
secrets and access controls are configured; **not approved for personal banking
data or production use**.

This is a DPIA-style engineering assessment, not a completed Article 35 GDPR
data protection impact assessment. A formal DPIA requires an identified
controller, purposes and legal bases, data-subject analysis, processor terms,
DPO advice where applicable, retention decisions, residual-risk acceptance,
and organizational sign-off. Those decisions are not present in the repository.

The current synthetic records are generated rather than derived from real
people. That sharply reduces privacy impact, but the service can still process
personal data about users through OIDC claims, actor/reviewer identifiers,
free-text rationales, network telemetry, and provider/account metadata.

## Processing description

The platform creates a deterministic synthetic bank, injects research scenarios,
runs read-only case investigations, sends selected evidence to either a local
fake model or an explicitly configured Eden EU inference endpoint, records
recommendations and human reviews, and evaluates experiment sessions.

| Data class | Examples | Source | Location/recipient | Current protection |
|---|---|---|---|---|
| Synthetic bank and supplemental case data | Customer tokens, KYC, transactions, alerts, user-supplied information | Generator/injector/user | Memory or PostgreSQL checkpoint; optional model payload | Case scope, input bounds and content hash; no application-level field encryption; database encryption and access controls are deployment-owned |
| Identity/access data | OIDC subject, username, roles, tenant, and ID token | Keycloak/user | Signed browser session cookie and audit records | PKCE, signed tokens, role checks, `HttpOnly` cookie, and `Secure` cookie in research mode; the cookie is integrity-protected but not encrypted |
| Review data | Reviewer ID, rationale, edited output | Reviewer | PostgreSQL and trajectory | Role gate; artifact encryption; free text is not automatically scrubbed |
| Model inputs/outputs | Complete evidence payload and recommendation | Graph | Model provider and restricted trajectory | EU base URL lock; schema validation; AES-256-GCM artifacts |
| Operational telemetry | Service/environment, counters, spans | Application | OTLP stack | Collector attribute deletion; partial redaction helper |
| Experiment metadata | Model/config IDs, result metrics, costs, errors | Scheduler/worker | PostgreSQL | Researcher or administrator role; provider errors truncated to 500 characters |

No production bank connector or TRACFIN connection exists. The system cannot
submit an STR, mutate KYC, freeze an account, block a transaction, or contact a
customer.

## Purpose, necessity, and proportionality

The purpose is to compare model and instruction-context configurations for
accuracy, evidence grounding, safety, reliability, and cost. Synthetic data is
appropriate and less intrusive than real customer data for this stage. The
system retrieves only the customer bound to the case, caps a transaction tool
response at 500 records (250 by default), uses advisory outputs, and requires a
human decision.

The following are not necessary for ordinary analyst operation and should stay
restricted:

- full raw trajectories;
- hidden scenario ground truth;
- researcher or administrator trace access;
- complete model/provider payloads;
- cross-experiment linkage through stable identifiers.

No necessity finding in this document authorizes later substitution of real,
pseudonymized, or production-derived data. Pseudonymized data remains personal
data; a new assessment is required before such a change.

## Roles and recipients

| Role | Intended access |
|---|---|
| Analyst | Synthetic alert list and investigations they initiate, including evidence and supplemental-information continuation |
| Reviewer | Same-tenant cases explicitly claimed for review; cannot claim a case they initiated |
| Researcher | Experiment scheduling/results plus tenant-wide case/evidence/trace reads |
| Administrator | Full application access across investigations, human review, traces, and experiments; intended for a simple single-user workflow |
| Model provider | Evidence and instructions for live inference when enabled |
| Infrastructure operators | PostgreSQL, artifact volume, telemetry, backups, and Keycloak as operationally assigned |

The controller, joint-controller (if any), processors, authorized operator
groups, and data-protection contacts are **TBD** in
[`config/governance/profile.yaml`](../config/governance/profile.yaml). This is a
release blocker for any processing beyond controlled synthetic research.

## Data flow and trust boundaries

1. A user authenticates through Keycloak or, only in development, supplies
   bypass headers.
2. FastAPI maps the subject, display name, required tenant claim, and realm
   roles to an actor. The display name is for the UI; authorization and audit
   use the stable subject identifier.
3. Case APIs compare the actor tenant and subject with the stored tenant and
   investigator/reviewer assignments; administrators bypass this application
   scope and researchers have tenant-wide read access.
4. The case determines the only customer ID permitted to read-only tools.
5. Evidence is serialized into the model request. Live calls are allowed only
   at the configured Eden EU API hostname.
6. The response is schema- and citation-validated, then checkpointed for human
   review.
7. Recommendations, reviews, job results, and audit events are stored in
   PostgreSQL when that backend is active.
8. Complete trajectories may be retained in process memory and as encrypted,
   content-addressed artifact files.
9. Operational traces and metrics are exported to the observability stack.

An EU hostname is a technical routing constraint, not proof of data residency,
subprocessor location, absence of provider fallback, deletion, non-training,
or international-transfer compliance. Those require contractual and operational
evidence.

## Risk method

Likelihood and impact are rated low, medium, or high for the current controlled
research environment. Residual ratings assume the documented controls are
enabled. A production assessment must use the controller's approved risk method.

| ID | Risk | Inherent | Existing controls | Residual | Required action |
|---|---|---:|---|---:|---|
| DP-01 | Real or copied bank data enters a synthetic-only system | High | Generator-based dataset; no bank connector | Medium | Enforce input provenance, DLP/canaries, and a documented prohibition at ingress |
| DP-02 | Cross-case disclosure through an object identifier | High | Required tenant claim; participant assignment; reviewer claim; tenant-scoped researcher reads; concealed/audited denials | Low/Medium | Add PostgreSQL row-level security, periodic access review, successful-read audit, and authorization property tests |
| DP-03 | Live model provider retains, trains on, transfers, or reroutes payloads | High | Exact Eden EU base URL; no automatic client retries | Medium/High | Record DPA, subprocessors, region/model route, fallback, retention, training-use, deletion, and incident terms |
| DP-04 | Raw trajectories expose complete records or free text | High | AES-256-GCM artifact encryption; researcher or administrator role | Medium | Use managed keys, least privilege, access logs, retention/deletion jobs, and separate trace authorization |
| DP-05 | Operational telemetry leaks secrets or payloads | High | Redaction helper; collector deletes authorization and end-user attributes | Medium | Centralize redaction before every exporter and test all log/span attributes with canaries |
| DP-06 | Development bypass is enabled outside an isolated environment | High | Explicit setting; disabled in Docker example | Medium | Fail closed when `environment=research`; network-isolate development instances |
| DP-07 | Artifact key is copied, weakly managed, or reused too broadly | High | Exactly 32-byte key required; Docker secret mount | Medium | KMS/HSM-backed rotation, per-environment keys, access audit, backup/recovery procedure |
| DP-08 | Data is retained indefinitely | High | Loki configured for seven days | High | Approve and implement schedules for database, checkpoints, artifacts, backups, and audit records |
| DP-09 | Tampering hides access or changes research evidence | High | Hash-chained audit and authenticated artifact encryption | Medium | External immutable anchoring, monitoring, periodic verification, and incident response |
| DP-10 | Reviewer or supplemental content includes personal or STR-confidential information | High | Synthetic-use policy; role gate; supplemental JSON size/field limits; audit excludes submitted values | Medium | UI warning, field minimization, validation/redaction, training, and access restrictions |
| DP-11 | Re-identification if production-derived “synthetic” data is introduced | High | Current generator does not ingest real records | Low now | Prohibit derivation until anonymization and membership/linkage testing are approved |
| DP-12 | Availability or cost attack disrupts review or causes excessive processing | Medium | Worker cost ceiling and kill switches | Medium | API quotas, rate limiting, workload budgets, alerting, and tested recovery |
| DP-13 | Full-access administrator account is compromised or used without a need to know | High | OIDC validation and centralized role gate; application safety controls still apply | High | Limit assignment, require MFA/step-up authentication, alert on use, review access regularly, and prefer narrower roles for multi-user research |

## Security and privacy controls

Implemented controls include strict input/output schemas, OIDC signature,
issuer, audience, tenant, and role validation; development-bypass isolation
setting; case-tenant/assignment and case-customer authorization; read-only
tools; no consequential tool bindings;
human review; versioned recommendations; citation integrity; audit hashes;
artifact authenticated encryption; an EU endpoint allowlist; kill switches;
bounded worker concurrency; and test coverage for authorization, redaction,
encryption, and audit tampering.

Important qualifications:

- `raw_research_capture=false` disables the artifact store in memory mode, but
  the PostgreSQL application path currently constructs a recorder with a store
  unconditionally.
- The browser session cookie is signed and `HttpOnly`, and becomes `Secure` in
  research mode, but it is not encrypted. It contains OIDC information needed
  for the application session and must be protected by
  HTTPS, short sessions, and appropriate identity-provider controls.
- Trajectory events remain in process memory even when no artifact store is
  configured.
- The redaction function is tested but is not applied automatically to all
  trajectory, logging, or OpenTelemetry values.
- Database encryption, backup encryption, network policy, TLS termination,
  malware protection, and host hardening are deployment responsibilities not
  configured by this repository.

## Retention and deletion

| Store | Current behavior | Required decision before broader use |
|---|---|---|
| Loki | Seven-day configured retention | Confirm logs contain no case payload and approve the period |
| Tempo/Prometheus | Local configuration has no documented retention decision | Set and test retention/deletion |
| PostgreSQL case/audit/experiment data | No automatic deletion | Define per-table purpose and retention; preserve legally required audit separately |
| LangGraph checkpoints | No automatic deletion | Delete after review/experiment retention unless justified |
| Encrypted artifacts | Content-addressed, no automatic deletion | Define research retention, legal hold, key destruction, and verifiable deletion |
| Backups | Not defined | Document location, encryption, retention, restore, and deletion propagation |

## Data-subject rights and incidents

For the current generated customers there are no real customer data subjects.
Real platform users may still be identifiable in identity, audit, and review
records. Before use by staff, document the notice, access/correction process,
applicable limitations for security/audit logs, contact route, and response
times.

An incident procedure must cover secret exposure, unauthorized case/trace
access, misrouted model traffic, artifact-key compromise, provider incidents,
and accidental use of real data. It must identify triage owners and the process
for assessing notification duties; none is implemented in this repository.

## Approval gates

The assessment must be reopened if any of the following occurs:

- real, pseudonymized, production-derived, or externally sourced personal data;
- a new inference provider, model route, fallback, or subprocessor;
- removal of the human-review gate or addition of a consequential action;
- new linkage, scoring, profiling, or customer-facing use;
- material changes to retention, telemetry, identity, or artifact storage;
- production deployment or a change in controller/purpose/jurisdiction.

Before any such use, obtain recorded product, AML control, privacy/DPO, security,
legal, and model-risk decisions. If residual high risk cannot be mitigated, the
controller must determine whether prior supervisory-authority consultation is
required.

## References

- [GDPR, Article 35 (DPIA)](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [CNIL: when an AI DPIA is necessary](https://www.cnil.fr/fr/realiser-une-analyse-dimpact-si-necessaire)
- [CNIL: anonymisation is not pseudonymisation](https://www.cnil.fr/fr/technologies/lanonymisation-de-donnees-personnelles)
- [CNIL: generative-AI user questions](https://www.cnil.fr/fr/les-questions-reponses-de-la-cnil-sur-lutilisation-dun-systeme-dia-generative)
