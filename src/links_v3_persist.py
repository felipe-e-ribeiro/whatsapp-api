"""Step Functions task: writes the pipeline's final outcome for a request.

Called from the two success paths in the state machine: after Validate
rejects a number (`status: invalid`), and after a successful Resolve
(`status: completed`). A `failed` outcome — retries exhausted — is
NOT persisted here: it's handled by `links_v3_dlq_consumer.py`, once the
failure payload reaches `LinksV3DLQ`, so the record only ever reflects
`failed` once the dead-letter path has actually run.

Any leftover `lastError` from a previous failed attempt (before a
reprocess — see `links_v3_reprocess.py`) is cleared here, so a request
that eventually succeeds doesn't keep showing a stale error.
"""
from datetime import datetime, timezone
from typing import Any

from src import links_store
from src.observability import emit_metric, get_logger, log_event

_logger = get_logger(__name__)


def lambda_handler(event: dict, context: Any) -> dict:
    request_id = event["requestId"]
    status = event["status"]
    now = datetime.now(timezone.utc).isoformat()

    values = {"status": status, "completedAt": now, "updatedAt": now}
    if "result" in event:
        values["result"] = event["result"]

    links_store.update_item(
        "LINKS_V3_TABLE_NAME",
        {"requestId": request_id},
        values,
        remove=["lastError"],
    )

    log_event(_logger, "pipeline outcome persisted", step="persist", outcome=status, requestId=request_id)
    emit_metric("LinksV3Outcome", dimensions={"Status": status}, requestId=request_id)

    return {"requestId": request_id, "status": status}
