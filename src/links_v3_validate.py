"""Step Functions task: validates and normalizes the submitted number.

Pure business validation reuses `src/phone.py`, unchanged from v1/v2 — v3
never redefines what counts as a valid Brazilian number. This step does
NOT raise on an invalid number: an invalid number is a client input
problem, not a transient failure, so it must not consume the pipeline's
retry budget. The state machine routes on the `valid` field instead of on
a caught exception.
"""
from typing import Any

from src.phone import is_valid_br_number, normalize, strip_country_code


def lambda_handler(event: dict, context: Any) -> dict:
    number = event.get("number") or ""
    digits = strip_country_code(normalize(number))
    valid = is_valid_br_number(digits)
    return {"valid": valid, "digits": digits if valid else None}
