"""Lambda entry point for the WhatsApp link API.

Thin wiring layer: extracts the `number` path parameter from the API
Gateway event and delegates all validation/formatting to `src.phone`.
"""
import json
from typing import Any

from src.phone import (
    build_whatsapp_url,
    is_valid_br_number,
    normalize,
    strip_country_code,
)


def lambda_handler(event: dict, context: Any) -> dict:
    path_params = event.get("pathParameters") or {}
    raw_number = path_params.get("number") or ""

    digits = strip_country_code(normalize(raw_number))

    if is_valid_br_number(digits):
        result: Any = build_whatsapp_url(digits)
    else:
        result = False

    return {
        "statusCode": 200,
        "body": json.dumps({"result": result}),
    }
