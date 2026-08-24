"""HttpApi Lambda Request Authorizer for the v2 (event-driven) routes.

Compares the `x-api-key` request header against a secret value stored in
AWS Secrets Manager. Uses the API Gateway v2 "simple responses" format
(`{"isAuthorized": bool}`), configured via
`AuthorizerPayloadFormatVersion: "2.0"` / `EnableSimpleResponses: true` in
template.yaml.
"""
import json
import os
from typing import Any, Optional

import boto3

_secrets_client = boto3.client("secretsmanager")

# Cached across warm invocations of the same execution environment, so we
# don't call Secrets Manager on every request.
_cached_api_key: Optional[str] = None


def _get_expected_api_key() -> str:
    global _cached_api_key

    if _cached_api_key is None:
        secret_id = os.environ["API_KEY_SECRET_ID"]
        response = _secrets_client.get_secret_value(SecretId=secret_id)
        secret = json.loads(response["SecretString"])
        _cached_api_key = secret["apiKey"]

    return _cached_api_key


def lambda_handler(event: dict, context: Any) -> dict:
    headers = event.get("headers") or {}
    # API Gateway HttpApi lowercases header names before invoking the authorizer.
    provided_key = headers.get("x-api-key")

    is_authorized = bool(provided_key) and provided_key == _get_expected_api_key()

    return {"isAuthorized": is_authorized}
