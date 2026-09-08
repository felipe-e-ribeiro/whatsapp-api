"""Step Functions task: resolves a validated number to its WhatsApp link.

Every invocation — whether triggered by a genuine transient failure and
the state machine's native `Retry`, or by the optional `simulateFailures`
test hook — increments a persisted `attempts` counter first, so retry
evidence is inspectable via `GET /v3/links/{requestId}` alone, not only
through the Step Functions console/execution history.
"""
from datetime import datetime, timezone
from typing import Any

from src import links_store
from src.observability import emit_metric, get_logger, log_event
from src.phone import build_whatsapp_url

_logger = get_logger(__name__)


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
    links_store.update_item(
        "LINKS_V3_TABLE_NAME",
        {"requestId": request_id},
        {"updatedAt": datetime.now(timezone.utc).isoformat()},
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
        log_event(
            _logger,
            "resolution attempt failed",
            level="WARNING",
            step="resolve",
            outcome="retry",
            requestId=request_id,
            attempts=attempts,
        )
        emit_metric("LinksV3ResolveRetried", requestId=request_id, attempts=attempts)
        raise TransientResolutionError(error_message)

    digits = event["validation"]["Payload"]["digits"]
    log_event(
        _logger,
        "number resolved",
        step="resolve",
        outcome="resolved",
        requestId=request_id,
        attempts=attempts,
    )
    return {"result": build_whatsapp_url(digits)}
