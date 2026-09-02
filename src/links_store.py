"""Shared DynamoDB access helpers for the WhatsApp Link API's Lambda
handlers (v2 and v3).

Deliberately thin: each function wraps a single DynamoDB operation so
handler modules don't each repeat their own
`boto3.resource("dynamodb").Table(os.environ[...])` boilerplate. No
business logic lives here — see `phone.py`/`base62.py` for that.
"""
import os
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

_dynamodb = boto3.resource("dynamodb")


def _table(table_name_env_var: str):
    return _dynamodb.Table(os.environ[table_name_env_var])


def get_item(table_name_env_var: str, key: dict) -> Optional[dict]:
    """Return the item at `key`, or None if it doesn't exist."""
    response = _table(table_name_env_var).get_item(Key=key)
    return response.get("Item")


def put_item(
    table_name_env_var: str, item: dict, *, if_not_exists_key: Optional[str] = None
) -> bool:
    """Write `item`. If `if_not_exists_key` is given, the write only
    happens when that attribute isn't already present on an existing item
    at the same key — an idempotent create. Returns False (without
    raising) when that condition fails, True when the item was written.
    """
    kwargs: dict[str, Any] = {"Item": item}
    if if_not_exists_key is not None:
        kwargs["ConditionExpression"] = f"attribute_not_exists({if_not_exists_key})"
    try:
        _table(table_name_env_var).put_item(**kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def update_item(
    table_name_env_var: str,
    key: dict,
    values: Optional[dict] = None,
    *,
    remove: Optional[list] = None,
) -> dict:
    """SET each attribute in `values` (if any) and REMOVE each attribute
    named in `remove` (if any) on the item at `key`. Returns the updated
    attributes (removed attributes are never part of the return value —
    DynamoDB doesn't report them).
    """
    values = values or {}
    remove = remove or []

    names: dict[str, str] = {}
    expr_values: dict[str, Any] = {}
    clauses = []

    if values:
        set_parts = []
        for i, (name, value) in enumerate(values.items()):
            alias = f"#s{i}"
            val_alias = f":v{i}"
            names[alias] = name
            expr_values[val_alias] = value
            set_parts.append(f"{alias} = {val_alias}")
        clauses.append("SET " + ", ".join(set_parts))

    if remove:
        remove_aliases = []
        for i, name in enumerate(remove):
            alias = f"#r{i}"
            names[alias] = name
            remove_aliases.append(alias)
        clauses.append("REMOVE " + ", ".join(remove_aliases))

    kwargs: dict[str, Any] = {
        "Key": key,
        "UpdateExpression": " ".join(clauses),
        "ExpressionAttributeNames": names,
        "ReturnValues": "UPDATED_NEW",
    }
    if expr_values:
        kwargs["ExpressionAttributeValues"] = expr_values

    response = _table(table_name_env_var).update_item(**kwargs)
    return response.get("Attributes", {})


def increment(
    table_name_env_var: str,
    key: dict,
    attribute: str,
    *,
    start: int = 0,
    amount: int = 1,
) -> int:
    """Atomically add `amount` to a numeric attribute (creating it at
    `start` first if absent) and return the new value.
    """
    response = _table(table_name_env_var).update_item(
        Key=key,
        UpdateExpression="SET #a = if_not_exists(#a, :start) + :amount",
        ExpressionAttributeNames={"#a": attribute},
        ExpressionAttributeValues={":start": start, ":amount": amount},
        ReturnValues="UPDATED_NEW",
    )
    return int(response["Attributes"][attribute])
