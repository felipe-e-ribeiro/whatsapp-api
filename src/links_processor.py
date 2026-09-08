"""SQS-triggered Lambda: resolves a queued link request and stores the
result.

Reuses the exact same validation/formatting rules as v1 (`src/phone.py`),
so the two API surfaces never disagree on what counts as a valid Brazilian
number.

Any exception here propagates, so SQS redelivers the message per the
queue's redrive policy instead of silently dropping a failed request.
"""
import json
from datetime import datetime, timezone
from typing import Any

from src import links_store
from src.observability import emit_metric, get_logger, log_event, mask_phone_number, timer
from src.phone import (
    build_whatsapp_url,
    is_valid_br_number,
    normalize,
    strip_country_code,
)

_logger = get_logger(__name__)


def _resolve(number: str) -> Any:
    digits = strip_country_code(normalize(number))
    if is_valid_br_number(digits):
        return build_whatsapp_url(digits)
    return False


def _process_record(record: dict) -> None:
    message = json.loads(record["body"])
    request_id = message["requestId"]
    number = message["number"]

    try:
        with timer() as elapsed:
            result = _resolve(number)
            completed_at = datetime.now(timezone.utc).isoformat()

            links_store.update_item(
                "LINKS_TABLE_NAME",
                {"requestId": request_id},
                {"status": "completed", "result": result, "completedAt": completed_at},
            )
    except Exception:
        # Let the exception propagate unchanged — SQS must still redeliver
        # per the queue's redrive policy. Logging first just means the
        # failure shows up in CloudWatch with full context before that
        # happens.
        log_event(
            _logger,
            "link processing failed",
            level="ERROR",
            exc_info=True,
            step="process",
            requestId=request_id,
            number=mask_phone_number(number),
        )
        raise

    result_outcome = "valid" if result else "invalid"
    log_event(
        _logger,
        "link processed",
        step="process",
        outcome="completed",
        result=result_outcome,
        requestId=request_id,
        number=mask_phone_number(number),
        durationMs=round(elapsed["ms"], 2),
    )
    emit_metric("LinksProcessed", dimensions={"Result": result_outcome}, requestId=request_id)


def lambda_handler(event: dict, context: Any) -> None:
    for record in event.get("Records", []):
        _process_record(record)
