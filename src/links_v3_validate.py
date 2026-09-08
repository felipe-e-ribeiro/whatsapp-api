"""Step Functions task: validates and normalizes the submitted number.

Pure business validation reuses `src/phone.py`, unchanged from v1/v2 — v3
never redefines what counts as a valid Brazilian number. This step does
NOT raise on an invalid number: an invalid number is a client input
problem, not a transient failure, so it must not consume the pipeline's
retry budget. The state machine routes on the `valid` field instead of on
a caught exception.
"""
from typing import Any

from src.observability import emit_metric, get_logger, log_event, mask_phone_number
from src.phone import is_valid_br_number, normalize, strip_country_code

_logger = get_logger(__name__)


def lambda_handler(event: dict, context: Any) -> dict:
    request_id = event.get("requestId") or ""
    number = event.get("number") or ""
    digits = strip_country_code(normalize(number))
    valid = is_valid_br_number(digits)

    outcome = "valid" if valid else "invalid"
    log_event(
        _logger,
        "number validated",
        step="validate",
        outcome=outcome,
        requestId=request_id,
        number=mask_phone_number(number),
    )
    emit_metric("LinksV3Validated", dimensions={"Outcome": outcome}, requestId=request_id)

    return {"valid": valid, "digits": digits if valid else None}
