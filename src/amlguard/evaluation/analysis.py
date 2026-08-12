from __future__ import annotations

from pathlib import Path
from typing import Any


def run_factorial_analysis(input_csv: Path, output_json: Path) -> dict[str, Any]:
    """Run the preregistered mixed-effects analysis using the research extra."""
    try:
        import pandas as pd
        import statsmodels.formula.api as smf
    except ImportError as exc:
        raise RuntimeError("install the 'research' extra to run statistical analysis") from exc

    frame = pd.read_csv(input_csv)
    required = {"scenario_id", "model", "context", "score"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"analysis input is missing columns: {sorted(missing)}")
    fitted = smf.mixedlm(
        "score ~ C(model) * C(context)",
        frame,
        groups=frame["scenario_id"],
    ).fit()
    result = {
        "n": int(len(frame)),
        "converged": bool(fitted.converged),
        "parameters": {str(key): float(value) for key, value in fitted.params.items()},
        "confidence_intervals": {
            str(index): [float(row.iloc[0]), float(row.iloc[1])]
            for index, row in fitted.conf_int().iterrows()
        },
    }
    output_json.write_text(__import__("json").dumps(result, indent=2), encoding="utf-8")
    return result
