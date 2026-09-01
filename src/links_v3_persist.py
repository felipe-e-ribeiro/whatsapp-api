"""Step Functions task: writes the pipeline's final outcome for a request.

Called from three different points in the state machine — after a
successful Resolve, after Validate rejects a number, and after Retry/
Catch exhausts the Resolve step's attempts — each time with a different
`status` in its input.
"""
from datetime import datetime, timezone
from typing import Any

from src import links_store


def lambda_handler(event: dict, context: Any) -> dict:
    request_id = event["requestId"]
    status = event["status"]

    values = {
        "status": status,
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }
    if "result" in event:
        values["result"] = event["result"]
    if "lastError" in event:
        values["lastError"] = event["lastError"]

    links_store.update_item("LINKS_V3_TABLE_NAME", {"requestId": request_id}, values)

    return {"requestId": request_id, "status": status}
