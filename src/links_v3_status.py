"""Lambda entry point for GET /v3/links/{requestId}.

Read-only lookup of a submitted request's current pipeline status,
including retry evidence (`attempts`, `lastError`) so it's inspectable
without needing access to the Step Functions console/execution history.
"""
import json
from typing import Any

from src import links_store


def lambda_handler(event: dict, context: Any) -> dict:
    path_params = event.get("pathParameters") or {}
    request_id = path_params.get("requestId") or ""

    item = links_store.get_item("LINKS_V3_TABLE_NAME", {"requestId": request_id})

    if item is None:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "requestId not found"}),
        }

    body = {"requestId": item["requestId"], "status": item["status"]}
    if "result" in item:
        body["result"] = item["result"]
    if "attempts" in item:
        body["attempts"] = int(item["attempts"])
    if "lastError" in item:
        body["lastError"] = item["lastError"]

    return {
        "statusCode": 200,
        "body": json.dumps(body),
    }
