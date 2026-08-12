from amlguard.evaluation.compliance_summary import summarize_compliance_coverage


def _result(*statuses: str) -> dict[str, object]:
    controls = [
        {"id": f"control-{index}", "title": f"Control {index}", "status": status}
        for index, status in enumerate(statuses, start=1)
    ]
    return {
        "evaluations": {
            "proofagent": {
                "metadata": {
                    "compliance": {
                        "frameworks": [
                            {"id": "gdpr", "name": "EU GDPR", "controls": controls}
                        ]
                    }
                }
            }
        }
    }


def test_compliance_summary_preserves_missing_coverage() -> None:
    summary = summarize_compliance_coverage(
        {
            "session-1": _result("met", "not_evaluated"),
            "session-2": _result("partial", "not_evaluated"),
        }
    )

    assert summary["sessions_total"] == 2
    assert summary["sessions_with_compliance"] == 2
    assert summary["coverage_rate"] == 0.5
    controls = summary["frameworks"][0]["controls"]
    assert controls[0]["aggregate_status"] == "partial"
    assert controls[0]["coverage_rate"] == 1.0
    assert controls[1]["aggregate_status"] == "not_evaluated"
    assert controls[1]["coverage_rate"] == 0.0


def test_compliance_summary_handles_results_without_proofagent() -> None:
    summary = summarize_compliance_coverage({"session-1": {"evaluations": {}}})

    assert summary["sessions_total"] == 1
    assert summary["sessions_with_compliance"] == 0
    assert summary["coverage_rate"] == 0.0
    assert summary["frameworks"] == []
