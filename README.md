# AMLGuard-EU

AMLGuard-EU is a research platform for designing and evaluating a
human-supervised AML (Anti-Money Laundering) investigation agent using
synthetic banking data. Given a transaction-monitoring alert, the agent gathers
case evidence, retrieves policy excerpts for the relevant jurisdiction and
date, and drafts a traceable recommendation for human review.

The current policy corpus contains 27 researcher-curated excerpts from the
French *Code monétaire et financier*, TRACFIN reporting guidance, the 2025
joint ACPR–TRACFIN guidelines on transaction monitoring and reporting,
Regulation (EU) 2023/1113 on information accompanying transfers, and the
future-dated Regulation (EU) 2024/1624. They cover subjects such as KYC and
beneficial-owner checks, ongoing and enhanced monitoring, unusual
transactions, PEP and high-risk-country risks, suspicious-report obligations,
record retention, and transfer traceability. Here, a policy is an approved
excerpt, not the complete legal text. Retrieval filters these excerpts by the
case jurisdiction, investigation date, alert type, and applicability facts.
The complete source list is in
[`regulatory_corpus/source_register.yaml`](regulatory_corpus/source_register.yaml).

The platform is designed to study whether an investigation agent is grounded,
auditable, secure, and appropriately governed. It records evidence provenance,
tool activity, policy citations, control results, and reviewer decisions.
Missing or invented evidence and policy citations can hard-block a
recommendation instead of allowing an unsupported conclusion to proceed.

The system deliberately cannot submit suspicious transaction reports, freeze
accounts, block transactions, update KYC records, or contact customers. Every
case disposition requires a human reviewer.

AMLGuard-EU is a synthetic research prototype. It is not legal advice, a
compliance certification, or a production banking system.

New to AML or this project? See the [sector and project vocabulary](docs/vocabulary.md)
for concise definitions of alerts, triggering transactions, KYC, rationale,
policy retrieval, hard blocks, trajectories, OIDC, and evaluation terms.

## Documentation

- [Architecture](docs/architecture.md) — system components, investigation
  workflow, roles, authorization, policy retrieval, controls, and failure states.
- [Vocabulary](docs/vocabulary.md) — plain-language definitions of AML and
  project-specific terms.
- [Regulatory scope](docs/regulatory_scope.md) — covered jurisdictions,
  policy sources, assumptions, and legal limitations.
- [Research protocol](docs/research_protocol.md) — research questions,
  experimental design, datasets, and evaluation procedure.
- [Statistical analysis plan](docs/statistical_analysis_plan.md) — metrics,
  hypotheses, comparisons, and reporting approach.
- [ProofAgent evaluation](docs/proofagent.md) — harness integration,
  manifests, commands, scoring, current results, and known limitations. The
  latest example output is available as
  [JSON](docs/proofagent-result-auto.json).
- [Observability](docs/observability.md) — logs, metrics, traces, alerts, and
  operational monitoring.
- [Threat model](docs/threat_model.md) — protected assets, trust boundaries,
  threats, and mitigations.
- [Data-protection assessment](docs/data_protection_impact_assessment.md) —
  DPIA-style privacy analysis and safeguards.
- [Limitations](docs/limitations.md) — known technical, research, regulatory,
  and deployment constraints.

## Local development without Docker

Prerequisites: Python 3.12+, `uv`, and a local PostgreSQL installation with
`pgvector`. Local development uses PostgreSQL on port 5432, the deterministic
fake model, and development authentication bypass; Keycloak and Docker are not
required.

Copy `.env.dev.example` to `.env.dev`, replace `CHANGE_ME` in both database
URLs, and create the `amlguard` database. Create `secrets/artifact_key.dev` as
32 random bytes or 64 hexadecimal characters.

For the example configuration, create the database before running Alembic
(replace `postgres` if `.env.dev` uses another PostgreSQL user):

```powershell
createdb --host localhost --port 5432 --username postgres amlguard
```

The equivalent `psql` command is:

```powershell
psql --host localhost --port 5432 --username postgres --dbname postgres --command "CREATE DATABASE amlguard;"
```

On Windows, if PowerShell says that `psql` is not recognized, invoke the
installed executable directly (adjust the PostgreSQL version and username):

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" --host localhost --port 5432 --username postgres --dbname postgres --command "CREATE DATABASE amlguard;"
```

Alternatively, add `C:\Program Files\PostgreSQL\18\bin` to `PATH` before using
the shorter `psql` and `createdb` commands.

`alembic upgrade head` creates schemas and tables inside an existing database;
it does not create the PostgreSQL database itself.

```text
# Install the application and all optional development, research, and ProofAgent dependencies.
uv sync --all-extras

# Create or update the PostgreSQL schemas and tables using the configured .env.dev database.
uv run alembic upgrade head

# Generate reproducible synthetic bank data, inject 20 development scenarios, and save it to PostgreSQL.
uv run amlguard seed --seed 20260810 --inject-pack development --persist

# Start the local API with automatic reload when source files change.
uv run uvicorn amlguard.api.app:create_app --factory --reload
```

The API is available at `http://localhost:8000`. To use a different environment
file, set `AMLGUARD_ENV_FILE` before running a command. Live Eden calls require
an explicit API key and model identifier.

## Live inference with Eden AI

Use [Eden AI](https://www.edenai.co/) for live investigation-agent inference.
The project uses it because one OpenAI-compatible API can provide several model
families, allowing researchers to change the declared model without rewriting
the investigation graph. Its model catalog exposes capabilities needed here,
including system messages and JSON-schema responses, while the dedicated EU
endpoint supports the project's regional-routing requirement. Provider-side
regional and subprocessor claims still require contractual verification before
real regulated data could be used.

Create an Eden API key, select an EU-available model from its `/v3/models`
catalog that supports system messages and JSON-schema responses, and configure:

```text
AMLGUARD_EDEN_AI_API_KEY=<your Eden API key>
AMLGUARD_EDEN_MODEL_ID=google/gemini-2.5-flash-lite
```

Put these values in `.env.dev` for a local launch or `.env.docker` for Docker,
then restart the application. Never commit or paste the API key into logs or
documentation. AMLGuard pins live inference to Eden's EU endpoint and rejects a
different base URL. If either Eden setting is absent, the application uses the
deterministic fake model; that mode is useful for tests but does not evaluate
live-model behavior or the B0/B5 prompt contrast.

The home page is also the investigation frontend. Select `B5 safeguards` or
`B0 baseline` beside an alert and click **Investigate**. The workspace shows the
current graph step while the analysis runs, then shows the recommendation,
material findings, evidence inventory, retrieved policy, and control results.
The investigation opens on a dedicated page so the results are not hidden below
the alert table. The home page shows each saved case status and replaces
**Investigate** with **See results** once a case exists. An initiating
investigator or administrator can use the confirmation-protected **Reset
investigation** action to discard active case state and start again. It also
displays the appropriate form when the case needs
supplemental information or human review. A narrow reviewer must claim the case
before reviewing; the development administrator can perform the whole workflow
directly. After a decision, the investigation page displays the review action,
reviewer, date, recommendation version, and case-specific rationale.

## Full Docker deployment

Copy `.env.docker.example` to `.env.docker`. Docker PostgreSQL is exposed on
host port 55432 by default, while containers use port 5432 internally.

```text
docker compose --env-file .env.docker up -d --build postgres keycloak app
```

The Compose `app` service runs `alembic upgrade head` before starting the web
server. This safely applies pending schema migrations to new or existing local
PostgreSQL volumes and prevents the application code from querying an older
table layout.

Seed the Docker PostgreSQL database separately, after migrations have
completed:

```powershell
docker compose --env-file .env.docker --profile seed run --rm seed
docker compose --env-file .env.docker restart app
```

The first command generates the deterministic development dataset and writes
it to the PostgreSQL container. The app loads its alert list at startup, so the
second command refreshes the homepage after seeding. This is separate from
`uv run --env-file .env.dev amlguard seed ...`, which uses the local PostgreSQL
connection declared in `.env.dev` rather than the Docker database.

The Docker API is available at `http://localhost:8000`; Keycloak is available
at `http://localhost:8081`.

Opening `http://localhost:8000` without a session displays a sign-in page.
Select **Sign in with Keycloak**, then use
`administrator` / `administrator-dev` for the simplest local workflow.
Keycloak authenticates the account using OIDC and redirects the browser back to
`http://localhost:8000/auth/callback`; AMLGuard then creates a session cookie
and applies the account's role and tenant permissions. Protected JSON API
routes instead expect an OIDC bearer access token and continue to return HTTP
401 when no token or browser session is supplied.

If the homepage reports that an authenticated account has no AMLGuard role,
select **Sign out and try again**. This requests a fresh token after a local
Keycloak role or mapper change; an older browser session retains its old token
claims.

Every authenticated page shows the active role and a **Sign out** button in the
header. Signing out clears the AMLGuard browser session and ends the Keycloak
session. The next sign-in asks for credentials again, allowing another local
role to be selected.

The local Keycloak client accepts callbacks from both `localhost:8000` and
`127.0.0.1:8000`. Keep the same hostname throughout a browser session because
cookies created for one hostname are not available to the other. Keycloak
imports the realm only when it does not already exist; after changing
`config/keycloak/realm.json`, update the existing realm or recreate the local
development database volume before expecting imported settings to change.

The imported development realm includes an `administrator` account with the
development-only password `administrator-dev`. This role can use every
application route for a simple single-user workflow. The narrower `analyst`,
`reviewer`, and `researcher` accounts remain available to demonstrate a more
realistic separation of responsibilities. Replace all seeded credentials
outside local development.

Narrow-role identities are tenant-scoped. The initiating analyst owns the case;
a different same-tenant reviewer must claim it through
`POST /investigations/{case_id}/claim-review` before reviewing. Researchers
have tenant-wide read/trace access, while the administrator remains global.

When the local authentication bypass is enabled, it defaults to the
`administrator` role. Set `X-Roles` explicitly to exercise a narrower role.

The API only schedules experiments. Run the durable worker separately:

```text
docker compose --env-file .env.docker --profile experiments up -d worker
```

## Monitoring

Start the local observability stack with the application:

```text
docker compose --env-file .env.docker --profile observability up -d --build
```

Prometheus is available on port `9090`, Alertmanager on `9093`, and Grafana on
`3000`. The API exposes `/metrics`, `/health/live`, and dependency-aware
`/health/ready` endpoints. Grafana provisions six dashboards, while Prometheus
loads safety and availability alerts from
`config/observability/alerts.yaml`. The local Alertmanager does not contact an
external destination; configure an approved receiver before deployment. See
[`docs/observability.md`](docs/observability.md) for the signal flow, metric
catalogue, dashboards, alerts, redaction boundary, and remaining deployment
work.

## Optional ProofAgent evaluation

ProofAgent complements AMLGuard's deterministic controls and human review with
artifact-based **Evaluation, Context, Compliance, and Governance** analysis.
Its optional Context assessment evaluates context engineering independently of
the final recommendation, which is useful in a sensitive financial-crime use
case.

```powershell
# Install the optional, pinned ProofAgent harness dependency.
uv sync --extra proofagent

# Confirm that the supported ProofAgent version is installed.
uv run amlguard proofagent check

# Validate the deterministic and live experiment manifests without calling a model.
uv run amlguard experiment validate --manifest experiments/manifests/proofagent.fake.example.yaml
uv run amlguard experiment validate --manifest experiments/manifests/proofagent.auto.example.yaml

# Cheap smoke test: deterministic AMLGuard agent, live ProofAgent evaluator.
uv run --env-file .env.dev amlguard proofagent evaluate `
  --manifest experiments/manifests/proofagent.fake.example.yaml `
  --scenario REG-001 `
  --provider fake

# Live evaluation: Eden AMLGuard agent and live ProofAgent evaluator.
uv run --env-file .env.dev amlguard proofagent evaluate `
  --manifest experiments/manifests/proofagent.auto.example.yaml `
  --scenario REG-001 `
  --provider auto
```

Each successful command prints the result and saves it to
`docs/proofagent-result.json`; use `--output <path>` to keep a separate copy.

Set both `AMLGUARD_EDEN_AI_API_KEY` and `OPENAI_API_KEY` in `.env.dev`; the Eden
agent and `gpt-4.1-mini` evaluator may incur cost. Use `--provider fake` only for
a deterministic integration test that overrides the manifest's live agent.

See [`docs/proofagent.md`](docs/proofagent.md) for evaluation scope, run counts,
configuration, context assessment, costs, privacy, and failure behavior.

For the underlying production-readiness framework, see Fouad Bousetouane's
paper [*Stop Shipping AI Agents on Faith: Capability Is Not Production
Readiness*](https://arxiv.org/abs/2607.27677), which introduces the ProofAgent
Index across Evaluation, Context, Compliance, and Governance.

## Safety boundary

Regulatory mappings in this repository are research interpretations for testing
software controls. They are not legal advice and do not establish that the
system or an organization is compliant. Production use requires review by
qualified French AML, privacy, security, and legal professionals.

## License

This project is licensed under the [Apache License 2.0](LICENSE). It permits
commercial and private use, modification, and redistribution subject to the
license terms, and includes an explicit patent grant.
#   a m l g u a r d - e u - a i - a g e n t  
 #   a m l g u a r d - e u - a i - a g e n t  
 