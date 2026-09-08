import json

import boto3
import pytest
from moto import mock_aws


def _sqs_event(*bodies):
    return {"Records": [{"body": json.dumps(body)} for body in bodies]}


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        region = "us-east-1"
        dynamodb = boto3.resource("dynamodb", region_name=region)

        links_table = dynamodb.create_table(
            TableName="links",
            KeySchema=[{"AttributeName": "requestId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "requestId", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        monkeypatch.setenv("LINKS_TABLE_NAME", "links")

        import src.links_store as links_store

        links_store._dynamodb = dynamodb

        yield {"links_table": links_table}


class TestLambdaHandler:
    def test_valid_number_resolves_to_url(self, aws):
        from src.links_processor import lambda_handler

        aws["links_table"].put_item(
            Item={"requestId": "8k", "number": "11987654321", "status": "pending"}
        )

        lambda_handler(
            _sqs_event({"requestId": "8k", "number": "11987654321"}), None
        )

        item = aws["links_table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "completed"
        assert item["result"] == "https://wa.me/5511987654321"
        assert "completedAt" in item

    def test_unrecognized_number_resolves_to_false(self, aws):
        from src.links_processor import lambda_handler

        aws["links_table"].put_item(
            Item={"requestId": "8l", "number": "123", "status": "pending"}
        )

        lambda_handler(_sqs_event({"requestId": "8l", "number": "123"}), None)

        item = aws["links_table"].get_item(Key={"requestId": "8l"})["Item"]
        assert item["status"] == "completed"
        assert item["result"] is False

    def test_malformed_record_raises_instead_of_swallowing(self, aws):
        from src.links_processor import lambda_handler

        with pytest.raises(Exception):
            lambda_handler({"Records": [{"body": "not json"}]}, None)

    def test_downstream_failure_is_logged_then_reraised(self, aws, monkeypatch, capsys):
        from src.links_processor import lambda_handler

        # A table name that doesn't exist makes links_store.update_item's
        # DynamoDB call fail with a ClientError, exercising the except
        # branch: the failure must be logged with full context *and*
        # still propagate, so SQS redelivers the message.
        monkeypatch.setenv("LINKS_TABLE_NAME", "does-not-exist")

        with pytest.raises(Exception):
            lambda_handler(
                _sqs_event({"requestId": "8k", "number": "11987654321"}), None
            )

        log_lines = [
            json.loads(line)
            for line in capsys.readouterr().out.strip().splitlines()
            if line.strip()
        ]
        failure_logs = [line for line in log_lines if line.get("level") == "ERROR"]
        assert len(failure_logs) == 1
        assert failure_logs[0]["requestId"] == "8k"
        assert failure_logs[0]["number"] == "*******4321"
        assert "error" in failure_logs[0]
