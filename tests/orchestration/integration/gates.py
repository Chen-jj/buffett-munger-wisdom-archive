"""One explicit allowlist for all optional expensive integration scenarios."""

import os


def enabled(scenario):
    scenarios = {value.strip() for value in os.environ.get("ORCHESTRATION_INTEGRATION_SCENARIOS", "").split(",")}
    return os.environ.get("RUN_ORCHESTRATION_INTEGRATION") == "1" and scenario in scenarios
