"""SQS-triggered Lambda: consumes `LinksV3DLQ` and records the final
`failed` outcome for a request whose Step Functions execution exhausted
its retries.

This is what actually empties the dead-letter queue: Lambda's SQS event
source deletes a message once its invocation returns without raising —
the same behavior `links_processor.py` already relies on for v2's
`LinksQueue`. There's no separate "delete" API call to make; letting a
dead-lettered failure sit in the queue forever isn't the goal here — the
goal is for it to be handled automatically and leave a durable record in
`LinksV3Table`, which is what `GET /v3/links/{requestId}` reads.
"""
import json
from datetime import datetime, timezone
from typing import Any

from src import links_store


def _process_record(record: dict) -> None:
    message = json.loads(record["body"])
    request_id = message["requestId"]
    error = message.get("error") or {}
    last_error = error.get("Cause") or error.get("Error") or "Unknown error"
    now = datetime.now(timezone.utc).isoformat()

    links_store.update_item(
        "LINKS_V3_TABLE_NAME",
        {"requestId": request_id},
        {
            "status": "failed",
            "lastError": last_error,
            "completedAt": now,
            "updatedAt": now,
        },
    )


def lambda_handler(event: dict, context: Any) -> None:
    for record in event.get("Records", []):
        _process_record(record)
