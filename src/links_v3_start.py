"""Lambda entry point for POST /v3/links.

Thin submit handler: accepts the request, resolves an idempotency key,
records a pending row, and hands off to the Step Functions state machine
that orchestrates the rest of the pipeline (`links_v3_validate.py` ->
`links_v3_resolve.py` -> `links_v3_persist.py`). Mirrors v2's
accept-then-poll shape (`links_submit.py`), but here the pipeline itself
runs inside a Step Functions state machine instead of being choreographed
through an SQS queue.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src import links_store
from src.observability import emit_metric, get_logger, log_event, mask_phone_number

_sfn = boto3.client("stepfunctions")
_logger = get_logger(__name__)


def _error(status_code: int, message: str) -> dict:
    return {
        "statusCode": status_code,
        "body": json.dumps({"error": message}),
    }


def _idempotency_key(event: dict) -> str:
    """An `Idempotency-Key` header controls deduplication explicitly; if
    the client doesn't supply one, generate a fresh key (no dedup
    guarantee for that call — the usual HTTP idempotency-key convention).
    """
    headers = event.get("headers") or {}
    return headers.get("idempotency-key") or headers.get("Idempotency-Key") or uuid.uuid4().hex


def lambda_handler(event: dict, context: Any) -> dict:
    raw_body = event.get("body") or "{}"
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError):
        log_event(_logger, "start rejected", level="WARNING", step="start", outcome="rejected", reason="invalid_json")
        emit_metric("LinksRejected", dimensions={"Version": "v3"})
        return _error(400, "Request body must be valid JSON")

    number = payload.get("number") if isinstance(payload, dict) else None
    if not isinstance(number, str):
        log_event(_logger, "start rejected", level="WARNING", step="start", outcome="rejected", reason="missing_number")
        emit_metric("LinksRejected", dimensions={"Version": "v3"})
        return _error(400, "'number' is required and must be a string")

    simulate_failures = payload.get("simulateFailures") if isinstance(payload, dict) else None

    request_id = _idempotency_key(event)
    now = datetime.now(timezone.utc).isoformat()

    links_store.put_item(
        "LINKS_V3_TABLE_NAME",
        {
            "requestId": request_id,
            "number": number,
            "status": "pending",
            "createdAt": now,
            "updatedAt": now,
        },
        if_not_exists_key="requestId",
    )

    execution_input = {"requestId": request_id, "number": number}
    if simulate_failures is not None:
        execution_input["simulateFailures"] = simulate_failures

    replayed = False
    try:
        _sfn.start_execution(
            stateMachineArn=os.environ["LINKS_V3_STATE_MACHINE_ARN"],
            name=request_id,
            input=json.dumps(execution_input),
        )
    except ClientError as exc:
        # A resubmission carrying the same Idempotency-Key lands here —
        # treat it as the successful idempotent replay it is, not an
        # error, so the client just gets the same requestId back.
        if exc.response["Error"]["Code"] != "ExecutionAlreadyExists":
            raise
        replayed = True

    log_event(
        _logger,
        "pipeline execution started",
        step="start",
        outcome="replayed" if replayed else "accepted",
        requestId=request_id,
        number=mask_phone_number(number),
    )
    if not replayed:
        emit_metric("LinksSubmitted", dimensions={"Version": "v3"}, requestId=request_id)

    return {
        "statusCode": 202,
        "body": json.dumps({"requestId": request_id, "status": "pending"}),
    }
