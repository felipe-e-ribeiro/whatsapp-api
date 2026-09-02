import json

import boto3
import pytest
from moto import mock_aws


def _sqs_event(*bodies):
    return {"Records": [{"body": json.dumps(body) if not isinstance(body, str) else body} for body in bodies]}


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        region = "us-east-1"
        dynamodb = boto3.resource("dynamodb", region_name=region)

        table = dynamodb.create_table(
            TableName="links-v3",
            KeySchema=[{"AttributeName": "requestId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "requestId", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.put_item(
            Item={"requestId": "8k", "number": "11987654321", "status": "pending"}
        )

        monkeypatch.setenv("LINKS_V3_TABLE_NAME", "links-v3")

        import src.links_store as links_store

        links_store._dynamodb = dynamodb

        yield {"table": table}


class TestLambdaHandler:
    def test_marks_request_failed_with_error_cause(self, aws):
        from src.links_v3_dlq_consumer import lambda_handler

        message = {
            "requestId": "8k",
            "number": "11987654321",
            "error": {
                "Error": "TransientResolutionError",
                "Cause": "Simulated transient failure (attempt 4 of 99 requested)",
            },
        }

        lambda_handler(_sqs_event(message), None)

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "failed"
        assert item["lastError"] == "Simulated transient failure (attempt 4 of 99 requested)"
        assert "completedAt" in item
        assert "updatedAt" in item

    def test_falls_back_to_a_generic_message_when_error_has_no_cause(self, aws):
        from src.links_v3_dlq_consumer import lambda_handler

        message = {"requestId": "8k", "number": "11987654321", "error": {}}

        lambda_handler(_sqs_event(message), None)

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "failed"
        assert item["lastError"] == "Unknown error"

    def test_processes_multiple_records(self, aws):
        from src.links_v3_dlq_consumer import lambda_handler

        aws["table"].put_item(
            Item={"requestId": "8l", "number": "11912345678", "status": "pending"}
        )

        lambda_handler(
            _sqs_event(
                {"requestId": "8k", "error": {"Cause": "boom-1"}},
                {"requestId": "8l", "error": {"Cause": "boom-2"}},
            ),
            None,
        )

        assert aws["table"].get_item(Key={"requestId": "8k"})["Item"]["lastError"] == "boom-1"
        assert aws["table"].get_item(Key={"requestId": "8l"})["Item"]["lastError"] == "boom-2"
