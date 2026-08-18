"""Lambda entry point for GET /v2/links/{requestId}.

Read-only lookup of a previously submitted request's current status and
(once processed) its result.
"""
import json
import os
from typing import Any

import boto3

_dynamodb = boto3.resource("dynamodb")


def lambda_handler(event: dict, context: Any) -> dict:
    path_params = event.get("pathParameters") or {}
    request_id = path_params.get("requestId") or ""

    table = _dynamodb.Table(os.environ["LINKS_TABLE_NAME"])
    response = table.get_item(Key={"requestId": request_id})
    item = response.get("Item")

    if item is None:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "requestId not found"}),
        }

    body = {"requestId": item["requestId"], "status": item["status"]}
    if item["status"] == "completed":
        body["result"] = item["result"]

    return {
        "statusCode": 200,
        "body": json.dumps(body),
    }
