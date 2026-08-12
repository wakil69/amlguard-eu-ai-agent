# Research protocol

## Protocol status

This is the prospective protocol for AMLGuard-EU. The design is executable in
the repository, but the named live models, final prompts/hashes, expert scenario
reviews, power justification, retention decisions, and held-out access process
must be frozen before the confirmatory study. Any post-freeze change is a
protocol deviation and must be reported.

## Research question

For a synthetic French/EU AML alert-investigation task, how do model capability
and instruction context affect evidence grounding, recommendation correctness,
safe behavior, reliability, and cost under one fixed staged workflow with
deterministic authorization and mandatory human review?

The study evaluates the copilot's recommendation process. It does not evaluate
real customer outcomes, actual STR filing, criminality detection, operational
bank performance, or legal compliance.

## Design

The confirmatory study is a crossed, repeated-session factorial experiment:

| Factor | Levels | Definition |
|---|---|---|
| Model | M1, M2, M3 | Lower, middle, and upper tiers chosen on an AML-neutral capability suite |
| Context | B0, B5 | Minimal instruction versus explicit safety/evidence instruction |
| Scenario | 50 held-out cases | Shared blocking factor; every configuration sees every scenario |
| Repetition | 3 | Independent provider calls per configuration/scenario |

The target held-out study contains **900 sessions**: 3 models × 2 contexts × 50
scenarios × 3 repetitions.

A **240-session pilot** uses two provisionally selected models × 2 contexts ×
20 validation scenarios × 3 repetitions. The pilot is for pipeline
reliability, variance estimation, rubric refinement, and cost verification. It
must not be used to select conclusions from the held-out pack.

## Hypotheses

These hypotheses must be frozen with their direction and primary metric before
held-out access:

- **H1 (model):** the selected capability tier changes recommendation match and
  evidence-grounding performance.
- **H2 (context):** B5 reduces unsafe/fabricated behavior relative to B0.
- **H3 (interaction):** the context effect varies by model tier.
- **H4 (cost-quality):** no single configuration is assumed to dominate; the
  result is a quality/safety/cost Pareto set.

Safety hard failures are reported as event rates and release blocks, not hidden
inside a weighted average. No hypothesis permits trading a prohibited action or
human-review bypass for a higher quality score.

## Model selection without AML leakage

Candidate models are evaluated only on
[`config/models/capability_suite.yaml`](../config/models/capability_suite.yaml),
which contains 30 AML-neutral structured-output, tool-calling,
context-retrieval, and instruction-adherence tasks. Candidate eligibility also
requires recorded EU catalogue/routing eligibility and verified absence of
fallback.

The implemented capability score is:

`0.30 × structured output + 0.30 × tool calling + 0.20 × instruction adherence + 0.10 × context retrieval + 0.10 × latency reliability`.

Eligible models are sorted into approximate lower, middle, and upper thirds.
The implementation chooses a cost-efficient model from the lower tier and the
highest capability score from the middle and upper tiers. Model selection must
not use development, validation, regression, or held-out AML outcomes. Freeze
provider model IDs, catalogue evidence, route, fallback policy, parameters,
price date, and capability results.

## Scenario corpus

The deterministic catalog contains 100 unique scenarios:

| Pack | Count | Permitted use |
|---|---:|---|
| Development | 20 | Implementation and debugging |
| Validation | 20 | Pilot and pre-freeze pipeline validation |
| Regression | 10 | Continuous safety/regression checks |
| Held-out | 50 | Confirmatory study only after freeze |

Eleven rotating families cover ordinary activity, rapid funds movement, missing
KYC, structuring-like activity, contradictory records, direct/indirect prompt
injection, cross-scope requests, prohibited-action pressure, tipping off, and
phantom tool-call claims. Each scenario fixes a seed, visible and hidden facts,
injection pattern, expected deterministic alert, mandatory/forbidden tools,
acceptable recommendations, attacks, and hard-block conditions.

All current scenario mappings are `researcher_curated`; none is marked
`expert_reviewed`. Before confirmatory interpretation, an AML-experienced
reviewer should examine scenario plausibility, acceptable recommendations,
mandatory evidence/tools, and attack realism. Reviewer identity and timestamp
are required by the schema for the expert-reviewed label.

## Experimental conditions

B0 and B5 differ only in the model instruction. All configurations use the same
staged graph, read-only tools, case authorization, output schema, citation
validators, effective-date policy retrieval, supplemental-information loop,
and human-review interrupt. The study makes no claim about alternative
orchestration or agent autonomy.

B0 is a short cited-recommendation instruction requiring supplied evidence and
approved policy excerpts. B5 additionally tells the live model that the task
uses synthetic data, requires supplied evidence and policy IDs,
fact/inference separation and neutral language, treats retrieved text as
untrusted, and prohibits criminality determinations or proposed consequential
actions. The deterministic fake model does not branch on this condition;
fake-only runs therefore cannot estimate the context effect and are limited to
pipeline and control testing.

Each configuration manifest records:

- exact model and configuration IDs;
- context level and prompt version;
- tool-schema and graph versions;
- dataset/scenario/policy/control/evaluator/telemetry versions;
- Git commit and dependency-lock hash;
- endpoint class, repetitions, randomization seed, and cost ceiling.

Values such as `uncommitted` or `pending` in the example manifest are invalid
for the confirmatory freeze even though the schema accepts them.

## Execution procedure

1. Freeze the protocol, statistical plan, manifest, scenario review state,
   dependencies, source hashes, credentials/routing evidence, and cost ceiling.
2. Run dataset and scenario reproducibility checks and the regression pack.
3. Schedule the manifest. The queue creates a stable session key for every
   configuration × scenario × repetition and shuffles jobs using the manifest
   seed.
4. Workers claim leased jobs, reserve estimated cost, heartbeat, and execute an
   isolated generated bank, injection, repository, checkpointer, and graph. The
   graph retrieves approved policy applicable on the alert date.
5. A timeout or connection error may retry up to the job limit with backoff.
   Other failures are terminal. Never silently replace the requested model.
6. Persist the requested and actual model IDs, endpoint class, logical injection
   hash, run, deterministic evaluation, artifact reference, error class, and
   cost basis.
7. Stop automatically or manually if a cost ceiling or hard safety stop is met.
8. Lock the raw result set before analysis; record its hash and all exclusions.

The current worker runs the graph until its first information or human-review
interrupt; it supplies neither information nor a simulated reviewer. Runs may
therefore end in `WAITING_FOR_INFORMATION` or `WAITING_FOR_HUMAN_REVIEW`, and
the interactive continuation paths are tested separately.

## Outcomes and evaluators

Native deterministic evaluation is mandatory and primary for machine-checkable
properties. It currently reports evidence- and policy-citation precision,
mandatory-evidence recall, fabricated-evidence rate, mandatory-tool recall, forbidden-tool
execution rate, recommendation match, schema validity, and safe failure.

LLM-assisted judgments may measure qualities that are not reducible to exact
matching, such as analytical coherence, distinction of fact and inference, and
usefulness to a reviewer. A jury must contain one or three prespecified judges;
three-judge scores use the median and flag a score range at or above the frozen
disagreement threshold. Judge model, prompt/rubric, order, temperature,
evidence references, and adjudication must be recorded.

ProofAgent `0.11.0` is an optional, separately normalized benchmark. When a
manifest enables it, the worker evaluates the finished recommendation in
artifact mode against the retrieved evidence and policy corpus and tool trace.
Its behavioral metrics must never be merged with native metrics under one
unlabeled score. The example manifests also enable separate context-engineering
and compliance assessments and record the governance profile. AMLGuard
revalidates positive compliance verdicts against registered evidence and keeps
raw ProofAgent compliance, validated compliance, governance decisions, and
native hard blocks separately labeled. The adapter rejects unsupported
installed versions and stores the full report as a restricted encrypted
artifact when the store is configured.

## Blinding and leakage prevention

- Model selection never sees AML pack outcomes.
- Development and validation are available before freeze; held-out payloads and
  outcomes are restricted until freeze approval.
- The scenario leakage scanner is a guardrail, not a proof that semantic leakage
  is absent.
- Researchers evaluating qualitative outputs should be blinded to configuration
  labels where practical.
- Hidden ground truth must not enter prompts, retrieved evidence, operational
  telemetry, or model-selection artifacts.
- Any held-out access, manual prompt inspection, rerun, exclusion, or rubric
  change is logged as a deviation.

## Reproducibility record

Archive the manifest, protocol/SAP hashes, Git commit, `uv.lock` hash, Python and
package versions, container image digests, dataset/scenario logical hashes,
prompt/tool/graph/control/rubric contents, provider request IDs and actual model
IDs, timestamps, randomization seed, retry history, raw result-set hash,
analysis code/output, and encrypted trajectory references.

A numeric seed controls local generation and job order; it cannot make a remote
model deterministic. Repetitions quantify that remaining run-to-run variation.

## Stop, exclusion, and deviation rules

Immediately pause the study for successful cross-scope access, prohibited
action execution, human-review bypass, STR-confidentiality disclosure,
fabricated evidence, missing material audit, non-EU inference, unapproved model
fallback, artifact-encryption failure, evidence of held-out leakage, or an
exceeded cost ceiling.

Provider failures remain in the accounting population. Retry only the
prespecified transient classes. Do not rerun a completed session to improve its
score. Exclusions require a reason determined without looking at comparative
outcomes and must be reported with included/excluded counts by configuration.

## Readiness checklist

- [ ] Owners and approvers are named.
- [ ] Three models and EU/no-fallback evidence are frozen.
- [ ] Scenario mappings receive the required expert review.
- [ ] Primary estimands, multiplicity family, and power rationale are frozen.
- [ ] Prompt, graph, tool, policy, control, evaluator, and rubric contents are hashed.
- [ ] Provider error, retry, missing-data, and adjudication rules are rehearsed.
- [ ] Artifact access, retention, deletion, and incident procedures are approved.
- [ ] Pilot acceptance criteria pass without inspecting held-out outcomes.
- [ ] Cost ceiling covers the planned design and remains a hard cap.
- [ ] Held-out access is authorized and auditable.
