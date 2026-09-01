"""Step Functions task: resolves a validated number to its WhatsApp link.

Every invocation — whether triggered by a genuine transient failure and
the state machine's native `Retry`, or by the optional `simulateFailures`
test hook — increments a persisted `attempts` counter first, so retry
evidence is inspectable via `GET /v3/links/{requestId}` alone, not only
through the Step Functions console/execution history.
"""
from typing import Any

from src import links_store
from src.phone import build_whatsapp_url


class TransientResolutionError(Exception):
    """Raised only by the `simulateFailures` test hook, to deliberately
    exercise the state machine's Retry/Catch behavior on demand — see
    `statemachine/links_pipeline.asl.yaml` and the README for how to use
    it to demonstrate retry/DLQ handling.
    """


def lambda_handler(event: dict, context: Any) -> dict:
    request_id = event["requestId"]
    simulate_failures = event.get("simulateFailures") or 0

    attempts = links_store.increment(
        "LINKS_V3_TABLE_NAME", {"requestId": request_id}, "attempts"
    )

    if attempts <= simulate_failures:
        error_message = (
            f"Simulated transient failure (attempt {attempts} of "
            f"{simulate_failures} requested)"
        )
        links_store.update_item(
            "LINKS_V3_TABLE_NAME",
            {"requestId": request_id},
            {"lastError": error_message},
        )
        raise TransientResolutionError(error_message)

    digits = event["validation"]["Payload"]["digits"]
    return {"result": build_whatsapp_url(digits)}
