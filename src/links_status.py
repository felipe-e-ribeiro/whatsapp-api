"""Lambda entry point for GET /v2/links/{requestId}.

Read-only lookup of a previously submitted request's current status and
(once processed) its result.
"""
import json
from typing import Any

from src import links_store


def lambda_handler(event: dict, context: Any) -> dict:
    path_params = event.get("pathParameters") or {}
    request_id = path_params.get("requestId") or ""

    item = links_store.get_item("LINKS_TABLE_NAME", {"requestId": request_id})

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
