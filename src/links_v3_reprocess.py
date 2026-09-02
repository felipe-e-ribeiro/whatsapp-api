"""Lambda entry point for POST /v3/links/{requestId}/reprocess.

Manually re-runs the pipeline for a request that ended up `failed`
(after `simulateFailures` exhausted its retry budget, or after a real
transient issue that has since been fixed). Only a `failed` request can
be reprocessed — resubmitting a `pending`/`completed`/`invalid` one here
is rejected, since those aren't stuck.

The stored record is flipped back to `pending` (and its stale `lastError`
cleared) *before* the new execution starts, so a client polling
`GET /v3/links/{requestId}` sees the retry in progress rather than a
permanent `failed` result — the point of this endpoint is that an
operator fixing a bug and reprocessing doesn't leave affected users stuck
looking at a dead end.

`reprocessCount` is tracked (and used to build a unique Step Functions
execution name) because a Standard Workflow execution name can't be
reused once closed — the original `requestId` is already a closed
(failed) execution name at this point.
"""
import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

from src import links_store

_sfn = boto3.client("stepfunctions")


def _error(status_code: int, message: str) -> dict:
    return {
        "statusCode": status_code,
        "body": json.dumps({"error": message}),
    }


def lambda_handler(event: dict, context: Any) -> dict:
    path_params = event.get("pathParameters") or {}
    request_id = path_params.get("requestId") or ""

    item = links_store.get_item("LINKS_V3_TABLE_NAME", {"requestId": request_id})
    if item is None:
        return _error(404, "requestId not found")

    if item.get("status") != "failed":
        return _error(
            409,
            f"requestId '{request_id}' has status '{item.get('status')}'; "
            "only a 'failed' request can be reprocessed",
        )

    reprocess_count = links_store.increment(
        "LINKS_V3_TABLE_NAME", {"requestId": request_id}, "reprocessCount"
    )
    now = datetime.now(timezone.utc).isoformat()
    links_store.update_item(
        "LINKS_V3_TABLE_NAME",
        {"requestId": request_id},
        {"status": "pending", "updatedAt": now},
        remove=["lastError"],
    )

    execution_input = {"requestId": request_id, "number": item["number"]}
    _sfn.start_execution(
        stateMachineArn=os.environ["LINKS_V3_STATE_MACHINE_ARN"],
        name=f"{request_id}-r{reprocess_count}",
        input=json.dumps(execution_input),
    )

    return {
        "statusCode": 202,
        "body": json.dumps(
            {
                "requestId": request_id,
                "status": "pending",
                "reprocessCount": reprocess_count,
            }
        ),
    }
