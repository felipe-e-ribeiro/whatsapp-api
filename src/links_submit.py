"""Lambda entry point for POST /v2/links.

Validates the request body shape only — it does NOT decide whether the
number is a recognizable Brazilian phone number; that happens later in
`links_processor.py`. This function's job is just to accept the request,
assign it an id, record it as pending, and hand it off to the queue.
"""
import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

from src import links_store
from src.base62 import encode
from src.observability import emit_metric, get_logger, log_event, mask_phone_number

_sqs = boto3.client("sqs")
_logger = get_logger(__name__)

_COUNTER_ID = "GLOBAL"
_COUNTER_SEED = 515  # first allocated value is 515 + 1 = 516 -> "8k"


def _error(status_code: int, message: str) -> dict:
    return {
        "statusCode": status_code,
        "body": json.dumps({"error": message}),
    }


def _allocate_request_id() -> str:
    counter_value = links_store.increment(
        "LINKS_COUNTER_TABLE_NAME",
        {"counterId": _COUNTER_ID},
        "value",
        start=_COUNTER_SEED,
    )
    return encode(counter_value)


def lambda_handler(event: dict, context: Any) -> dict:
    raw_body = event.get("body") or "{}"
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError):
        log_event(_logger, "submit rejected", level="WARNING", step="submit", outcome="rejected", reason="invalid_json")
        emit_metric("LinksRejected", dimensions={"Version": "v2"})
        return _error(400, "Request body must be valid JSON")

    number = payload.get("number") if isinstance(payload, dict) else None
    if not isinstance(number, str):
        log_event(_logger, "submit rejected", level="WARNING", step="submit", outcome="rejected", reason="missing_number")
        emit_metric("LinksRejected", dimensions={"Version": "v2"})
        return _error(400, "'number' is required and must be a string")

    request_id = _allocate_request_id()
    requested_at = datetime.now(timezone.utc).isoformat()

    links_store.put_item(
        "LINKS_TABLE_NAME",
        {
            "requestId": request_id,
            "number": number,
            "status": "pending",
            "requestedAt": requested_at,
        },
    )

    _sqs.send_message(
        QueueUrl=os.environ["LINKS_QUEUE_URL"],
        MessageBody=json.dumps({"requestId": request_id, "number": number}),
    )

    log_event(
        _logger,
        "link submitted",
        step="submit",
        outcome="accepted",
        requestId=request_id,
        number=mask_phone_number(number),
    )
    emit_metric("LinksSubmitted", dimensions={"Version": "v2"}, requestId=request_id)

    return {
        "statusCode": 202,
        "body": json.dumps({"requestId": request_id, "status": "pending"}),
    }
