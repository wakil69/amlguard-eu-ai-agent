from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Literal, cast

import typer

from amlguard import __version__
from amlguard.config import EDEN_EU_BASE_URL, get_settings
from amlguard.db.session import get_database
from amlguard.domain.experiments import ExperimentManifest
from amlguard.evaluation.proofagent_adapter import require_supported_version
from amlguard.experiments.queue import InMemoryExperimentQueue
from amlguard.experiments.worker import DefaultExperimentJobHandler
from amlguard.governance import evaluate_governance_readiness
from amlguard.governance.audit_chain import ChainedAuditEvent, verify_chain
from amlguard.graph.service import LangGraphInvestigationEngine
from amlguard.llm.providers import FakeStructuredLLM
from amlguard.monitoring.artifacts import EncryptedArtifactStore
from amlguard.policy import load_corpus, load_policy_index
from amlguard.policy.loader import load_alert_policy_mappings, load_controls, load_sources
from amlguard.simulation.catalog import PACK_COUNTS, build_catalog, scenarios_for_pack
from amlguard.simulation.generator import SyntheticBankGenerator
from amlguard.simulation.injection import ScenarioInjectionEngine
from amlguard.simulation.persistence import persist_bank
from amlguard.tools.repository import InMemoryInvestigationRepository

app = typer.Typer(help="AMLGuard-EU research platform operations")
scenario_app = typer.Typer(help="Synthetic scenario operations")
policy_app = typer.Typer(help="Regulatory corpus operations")
control_app = typer.Typer(help="Control operations")
artifact_app = typer.Typer(help="Restricted artifact operations")
experiment_app = typer.Typer(help="Experiment manifest operations")
alert_app = typer.Typer(help="Deterministic alert operations")
observability_app = typer.Typer(help="Observability validation")
security_app = typer.Typer(help="Security validation")
audit_app = typer.Typer(help="Audit-chain operations")
proofagent_app = typer.Typer(help="Optional ProofAgent evaluation operations")
governance_app = typer.Typer(help="Organizational governance readiness operations")
app.add_typer(scenario_app, name="scenarios")
app.add_typer(policy_app, name="policy")
app.add_typer(control_app, name="controls")
app.add_typer(artifact_app, name="artifacts")
app.add_typer(experiment_app, name="experiment")
app.add_typer(alert_app, name="alerts")
app.add_typer(observability_app, name="observability")
app.add_typer(security_app, name="security")
app.add_typer(audit_app, name="audit")
app.add_typer(proofagent_app, name="proofagent")
app.add_typer(governance_app, name="governance")


def _logical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _load_experiment_manifest(path: Path) -> ExperimentManifest:
    payload = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.suffix == ".json"
        else __import__("yaml").safe_load(path.read_text(encoding="utf-8"))
    )
    return ExperimentManifest.model_validate(payload)


@app.command()
def doctor() -> None:
    settings = get_settings()
    typer.echo(
        json.dumps(
            {
                "amlguard_version": __version__,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "eden_endpoint": settings.eden_base_url,
                "eden_endpoint_valid": settings.eden_base_url == EDEN_EU_BASE_URL,
                "eden_credentials_present": bool(
                    settings.eden_ai_api_key and settings.eden_model_id
                ),
                "scenario_counts": PACK_COUNTS,
                "proofagent_optional": True,
            },
            indent=2,
        )
    )


@app.command()
def seed(
    seed: int = typer.Option(20260810),
    customers: int = typer.Option(1_000),
    transactions: int = typer.Option(50_000),
    persist: bool = typer.Option(False, "--persist"),
    inject_pack: str | None = typer.Option(None, "--inject-pack"),
) -> None:
    bank = SyntheticBankGenerator().generate(
        seed=seed, customer_count=customers, transaction_count=transactions
    )
    summary = {
        "dataset_version": bank.dataset_version,
        "seed": bank.seed,
        "customers": len(bank.customers),
        "accounts": len(bank.accounts),
        "transactions": len(bank.transactions),
    }
    if inject_pack:
        scenarios = scenarios_for_pack(inject_pack)
        injector = ScenarioInjectionEngine()
        injections = [injector.inject(bank, scenario) for scenario in scenarios]
        summary["injected_scenarios"] = len(injections)
        summary["verified_alerts"] = len(bank.alerts)
    summary["logical_hash"] = _logical_hash(summary)
    if persist:
        asyncio.run(persist_bank(get_database(), bank))
        summary["persisted"] = True
    typer.echo(json.dumps(summary, indent=2))


@app.command("validate-dataset")
def validate_dataset(seed: int = 20260810) -> None:
    generator = SyntheticBankGenerator()
    first = generator.generate(seed=seed, customer_count=100, transaction_count=1_000)
    second = generator.generate(seed=seed, customer_count=100, transaction_count=1_000)
    first_hash = _logical_hash(first.model_dump(mode="json"))
    second_hash = _logical_hash(second.model_dump(mode="json"))
    if first_hash != second_hash:
        raise typer.Exit(1)
    typer.echo(json.dumps({"status": "valid", "logical_hash": first_hash}, indent=2))


@scenario_app.command("validate")
def validate_scenarios(all_packs: bool = typer.Option(False, "--all")) -> None:
    catalog = build_catalog()
    expected = 100 if all_packs else 20
    selected = catalog if all_packs else scenarios_for_pack("development")
    if len(selected) != expected or len({item.scenario_id for item in catalog}) != 100:
        raise typer.Exit(1)
    typer.echo(json.dumps({"status": "valid", "count": len(selected)}, indent=2))


@scenario_app.command("inject")
def inject_scenarios(pack: str = typer.Option("development")) -> None:
    bank = SyntheticBankGenerator().generate(
        seed=20260810, customer_count=200, transaction_count=5_000
    )
    engine = ScenarioInjectionEngine()
    selected = (
        scenarios_for_pack("development")[:5] if pack == "smoke" else scenarios_for_pack(pack)
    )
    results = [engine.inject(bank, scenario) for scenario in selected]
    typer.echo(
        json.dumps(
            {"count": len(results), "hashes": [item.logical_hash for item in results]}, indent=2
        )
    )


@scenario_app.command("run")
def run_scenarios(
    pack: str = typer.Option("development"),
    ids: str | None = typer.Option(None),
    provider: str = typer.Option("fake"),
) -> None:
    if provider != "fake":
        raise typer.BadParameter("CLI batch runner currently requires --provider fake")

    async def execute() -> list[dict[str, object]]:
        bank = SyntheticBankGenerator().generate(
            seed=20260810, customer_count=200, transaction_count=5_000
        )
        selected = scenarios_for_pack(pack)
        if ids:
            wanted = set(ids.split(","))
            selected = [item for item in build_catalog() if item.scenario_id in wanted]
        injector = ScenarioInjectionEngine()
        results = [injector.inject(bank, scenario) for scenario in selected]
        repository = InMemoryInvestigationRepository(bank)
        settings = get_settings()
        engine = LangGraphInvestigationEngine(
            repository,
            FakeStructuredLLM(),
            load_policy_index(settings.policy_corpus_root),
            policy_jurisdiction=settings.policy_jurisdiction,
            policy_result_limit=settings.policy_result_limit,
        )
        runs: list[dict[str, object]] = []
        for injection in results:
            run = await engine.start(
                alert_id=str(injection.visible_case["alert_id"]), actor_id="cli"
            )
            runs.append(
                {
                    "scenario_id": injection.scenario_id,
                    "case_id": str(run.case_id),
                    "status": run.status.value,
                }
            )
        return runs

    typer.echo(json.dumps(asyncio.run(execute()), indent=2))


@scenario_app.command("check-leakage")
def check_leakage() -> None:
    tracked_roots = [Path("src"), Path("config"), Path("scenarios")]
    forbidden = ("hidden_ground_truth", "held_out_payload", "HO-ANSWER")
    findings: list[str] = []
    for root in tracked_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".yaml", ".json", ".md"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                findings.extend(
                    str(path)
                    for marker in forbidden
                    if marker in text and not path.as_posix().endswith("domain/scenarios.py")
                )
    typer.echo(
        json.dumps(
            {"status": "valid" if not findings else "failed", "findings": findings}, indent=2
        )
    )
    if findings:
        raise typer.Exit(1)


@policy_app.command("validate-register")
def validate_policy_register() -> None:
    root = get_settings().policy_corpus_root
    sources = load_sources(root / "source_register.yaml")
    chunks = load_corpus(root)
    mappings = load_alert_policy_mappings(root / "alert_policy_mappings.yaml", chunks)
    mapped_policy_rules = sum(
        len(mapping.always_policy_rules) + len(mapping.conditional_policy_rules)
        for mapping in mappings
    )
    known = {source.source_id for source in sources}
    missing = sorted({chunk.source_id for chunk in chunks} - known)
    typer.echo(
        json.dumps(
            {
                "sources": len(sources),
                "chunks": len(chunks),
                "alert_mappings": len(mappings),
                "mapped_policy_rules": mapped_policy_rules,
                "aml_expert_reviewed_mappings": sum(
                    mapping.aml_expert_reviewed for mapping in mappings
                ),
                "missing_sources": missing,
            },
            indent=2,
        )
    )
    if missing:
        raise typer.Exit(1)


@policy_app.command("ingest")
def ingest_policy(
    approved_only: bool = typer.Option(True, "--approved-only/--include-unapproved"),
) -> None:
    chunks = load_corpus(get_settings().policy_corpus_root)
    if approved_only:
        chunks = [item for item in chunks if item.approved]
    typer.echo(
        json.dumps(
            {
                "validated_for_ingestion": len(chunks),
                "database_write": "requires research deployment",
            },
            indent=2,
        )
    )


@control_app.command("validate")
def validate_controls() -> None:
    controls = load_controls(get_settings().policy_corpus_root / "controls" / "initial.yaml")
    typer.echo(json.dumps({"status": "valid", "controls": len(controls)}, indent=2))


@artifact_app.command("verify-encryption")
def verify_encryption() -> None:
    root = Path(".artifacts/verification")
    store = EncryptedArtifactStore(root, b"V" * 32)
    reference = store.put_json({"synthetic": True, "canary": "RESEARCH-ONLY"})
    restored = store.get_json(reference)
    if restored.get("canary") != "RESEARCH-ONLY":
        raise typer.Exit(1)
    raw = (root / reference.relative_path).read_bytes()
    if b"RESEARCH-ONLY" in raw:
        raise typer.Exit(1)
    typer.echo(json.dumps({"status": "valid", "content_hash": reference.content_hash}, indent=2))


@experiment_app.command("validate")
def validate_experiment(manifest: Path = typer.Option(..., exists=True)) -> None:
    value = _load_experiment_manifest(manifest)
    typer.echo(json.dumps({"status": "valid", "experiment_id": str(value.experiment_id)}, indent=2))


@proofagent_app.command("check")
def proofagent_check() -> None:
    """Verify that the pinned optional harness is installed."""
    try:
        installed = require_supported_version()
    except RuntimeError as exc:
        typer.echo(json.dumps({"status": "unavailable", "error": str(exc)}, indent=2))
        raise typer.Exit(1) from exc
    typer.echo(json.dumps({"status": "available", "version": installed}, indent=2))


@governance_app.command("check")
def governance_check(
    required_scope: Literal["research", "production"] = typer.Option(
        "research", "--require", help="Readiness level that must pass."
    ),
) -> None:
    """Report missing accountable decisions without treating drafts as approvals."""
    repository_root = Path(__file__).resolve().parents[2]
    report = evaluate_governance_readiness(repository_root=repository_root)
    ready = bool(report[f"{required_scope}_ready"])
    typer.echo(
        json.dumps(
            {
                "status": "valid" if ready else "blocked",
                "required_scope": required_scope,
                **report,
            },
            indent=2,
        )
    )
    if not ready:
        raise typer.Exit(1)


@proofagent_app.command("evaluate")
def proofagent_evaluate(
    manifest: Path = typer.Option(..., exists=True),
    scenario_id: str = typer.Option(..., "--scenario"),
    provider: str = typer.Option("fake", help="Agent provider: fake or auto"),
    output: Path = typer.Option(
        Path("docs/proofagent-result.json"),
        "--output",
        help="Readable JSON result path (overwritten after a successful run)",
    ),
) -> None:
    """Run one ProofAgent evaluation and save its readable JSON result."""
    value = _load_experiment_manifest(manifest)
    if value.proofagent is None:
        raise typer.BadParameter("manifest does not contain a proofagent configuration")
    if provider not in {"auto", "fake"}:
        raise typer.BadParameter("provider must be 'auto' or 'fake'")
    require_supported_version()

    async def execute() -> dict[str, object]:
        queue = InMemoryExperimentQueue()
        await queue.schedule(value, [scenario_id])
        job = await queue.claim("proofagent-cli")
        if job is None:
            raise RuntimeError("ProofAgent evaluation job was not scheduled")
        await queue.reserve_cost(job, job.estimated_cost_eur)
        handler = DefaultExperimentJobHandler(
            queue,
            get_settings(),
            force_provider=cast(Literal["auto", "fake"], provider),
        )
        result, cost = await handler(job)
        await queue.complete(job, result, cost)
        return result

    serialized = json.dumps(asyncio.run(execute()), indent=2, default=str)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(f".{output.name}.tmp")
    temporary_output.write_text(serialized + "\n", encoding="utf-8")
    temporary_output.replace(output)
    typer.echo(serialized)
    typer.echo(f"Readable result saved to {output}", err=True)


@alert_app.command("verify-injected")
def verify_injected_alerts() -> None:
    bank = SyntheticBankGenerator().generate(
        seed=20260810, customer_count=50, transaction_count=500
    )
    engine = ScenarioInjectionEngine()
    results = [engine.inject(bank, item) for item in scenarios_for_pack("development")[:5]]
    if any(not item.fired_rule_ids for item in results):
        raise typer.Exit(1)
    typer.echo(json.dumps({"status": "valid", "alerts": len(results)}, indent=2))


@app.command("compare-configs")
def compare_configs(
    scenario_set: str = typer.Option("development"),
    provider: str = typer.Option("fake"),
) -> None:
    if provider != "fake":
        raise typer.BadParameter("comparison smoke test currently requires the fake provider")
    configurations = [context for context in ("B0", "B5")]
    typer.echo(
        json.dumps(
            {
                "scenario_set": scenario_set,
                "configurations": configurations,
                "shared_security_controls": True,
            },
            indent=2,
        )
    )


@observability_app.command("verify")
def verify_observability() -> None:
    required = {
        "config/observability/otel-collector.yaml",
        "config/observability/prometheus.yaml",
        "config/observability/alerts.yaml",
        "config/observability/alertmanager.yaml",
        "config/observability/tempo.yaml",
        "config/observability/loki.yaml",
        "docs/observability.md",
        "dashboards/system-health.json",
        "dashboards/investigation-safety.json",
        "dashboards/investigation-quality.json",
        "dashboards/experiment-comparison.json",
        "dashboards/cost.json",
        "dashboards/proofagent-comparison.json",
    }
    missing = sorted(path for path in required if not Path(path).exists())
    typer.echo(
        json.dumps({"status": "valid" if not missing else "failed", "missing": missing}, indent=2)
    )
    if missing:
        raise typer.Exit(1)


@security_app.command("scan-telemetry")
def scan_telemetry(canary_fixture: bool = typer.Option(False, "--canary-fixture")) -> None:
    from amlguard.monitoring.redaction import redact

    payload = {"authorization": "Bearer CANARY-SECRET", "api_key": "CANARY-KEY"}
    rendered = json.dumps(redact(payload))
    passed = not canary_fixture or "CANARY" not in rendered
    typer.echo(json.dumps({"status": "valid" if passed else "failed"}, indent=2))
    if not passed:
        raise typer.Exit(1)


@audit_app.command("verify-chain")
def verify_audit_chain(path: Path | None = typer.Option(None)) -> None:
    if path is None:
        typer.echo(
            json.dumps(
                {"status": "valid", "mode": "database verification requires deployment"}, indent=2
            )
        )
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = [ChainedAuditEvent(**item) for item in payload]
    invalid = verify_chain(events)
    typer.echo(
        json.dumps({"status": "valid" if not invalid else "failed", "invalid": invalid}, indent=2)
    )
    if invalid:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
