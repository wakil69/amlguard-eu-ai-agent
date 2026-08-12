from importlib.metadata import PackageNotFoundError, version

SUPPORTED_VERSION = "0.11.0"


def require_supported_version() -> str:
    try:
        installed = version("proofagent-harness")
    except PackageNotFoundError as exc:
        raise RuntimeError("ProofAgent is optional; install the 'proofagent' extra") from exc
    if installed != SUPPORTED_VERSION:
        raise RuntimeError(
            f"ProofAgent adapter supports {SUPPORTED_VERSION}; installed version is {installed}"
        )
    return installed
