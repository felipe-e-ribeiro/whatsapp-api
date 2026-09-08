"""Lambda entry point for the WhatsApp link API.

Thin wiring layer: extracts the `number` path parameter from the API
Gateway event and delegates all validation/formatting to `src.phone`.
"""
import json
from typing import Any

from src.observability import emit_metric, get_logger, log_event, mask_phone_number, timer
from src.phone import (
    build_whatsapp_url,
    is_valid_br_number,
    normalize,
    strip_country_code,
)

_logger = get_logger(__name__)


def lambda_handler(event: dict, context: Any) -> dict:
    path_params = event.get("pathParameters") or {}
    raw_number = path_params.get("number") or ""

    with timer() as elapsed:
        digits = strip_country_code(normalize(raw_number))
        is_valid = is_valid_br_number(digits)
        result: Any = build_whatsapp_url(digits) if is_valid else False

    outcome = "valid" if is_valid else "invalid"
    log_event(
        _logger,
        "v1 link lookup",
        step="v1_lookup",
        outcome=outcome,
        number=mask_phone_number(raw_number),
        durationMs=round(elapsed["ms"], 2),
    )
    emit_metric("LinksV1Resolved", dimensions={"Outcome": outcome})

    return {
        "statusCode": 200,
        "body": json.dumps({"result": result}),
    }
