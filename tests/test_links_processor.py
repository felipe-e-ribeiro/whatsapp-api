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

        import src.links_processor as links_processor

        links_processor._dynamodb = dynamodb

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
