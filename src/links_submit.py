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

from src.base62 import encode

_dynamodb = boto3.resource("dynamodb")
_sqs = boto3.client("sqs")

_COUNTER_ID = "GLOBAL"
_COUNTER_SEED = 515  # first allocated value is 515 + 1 = 516 -> "8k"


def _error(status_code: int, message: str) -> dict:
    return {
        "statusCode": status_code,
        "body": json.dumps({"error": message}),
    }


def _allocate_request_id() -> str:
    table = _dynamodb.Table(os.environ["LINKS_COUNTER_TABLE_NAME"])
    response = table.update_item(
        Key={"counterId": _COUNTER_ID},
        UpdateExpression="SET #v = if_not_exists(#v, :start) + :incr",
        ExpressionAttributeNames={"#v": "value"},
        ExpressionAttributeValues={":start": _COUNTER_SEED, ":incr": 1},
        ReturnValues="UPDATED_NEW",
    )
    counter_value = int(response["Attributes"]["value"])
    return encode(counter_value)


def lambda_handler(event: dict, context: Any) -> dict:
    raw_body = event.get("body") or "{}"
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError):
        return _error(400, "Request body must be valid JSON")

    number = payload.get("number") if isinstance(payload, dict) else None
    if not isinstance(number, str):
        return _error(400, "'number' is required and must be a string")

    request_id = _allocate_request_id()
    requested_at = datetime.now(timezone.utc).isoformat()

    table = _dynamodb.Table(os.environ["LINKS_TABLE_NAME"])
    table.put_item(
        Item={
            "requestId": request_id,
            "number": number,
            "status": "pending",
            "requestedAt": requested_at,
        }
    )

    _sqs.send_message(
        QueueUrl=os.environ["LINKS_QUEUE_URL"],
        MessageBody=json.dumps({"requestId": request_id, "number": number}),
    )

    return {
        "statusCode": 202,
        "body": json.dumps({"requestId": request_id, "status": "pending"}),
    }
