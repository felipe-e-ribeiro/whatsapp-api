import json

import boto3
import pytest
from moto import mock_aws


def _event(request_id):
    return {"pathParameters": {"requestId": request_id}}


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        region = "us-east-1"
        dynamodb = boto3.resource("dynamodb", region_name=region)

        links_table = dynamodb.create_table(
            TableName="links-v3",
            KeySchema=[{"AttributeName": "requestId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "requestId", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        monkeypatch.setenv("LINKS_V3_TABLE_NAME", "links-v3")

        import src.links_store as links_store

        links_store._dynamodb = dynamodb

        yield {"links_table": links_table}


class TestLambdaHandler:
    def test_pending_request(self, aws):
        from src.links_v3_status import lambda_handler

        aws["links_table"].put_item(
            Item={"requestId": "8k", "number": "11987654321", "status": "pending"}
        )

        response = lambda_handler(_event("8k"), None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"requestId": "8k", "status": "pending"}

    def test_completed_request_includes_result_and_attempts(self, aws):
        from src.links_v3_status import lambda_handler

        aws["links_table"].put_item(
            Item={
                "requestId": "8k",
                "status": "completed",
                "result": "https://wa.me/5511987654321",
                "attempts": 1,
            }
        )

        response = lambda_handler(_event("8k"), None)

        body = json.loads(response["body"])
        assert body == {
            "requestId": "8k",
            "status": "completed",
            "result": "https://wa.me/5511987654321",
            "attempts": 1,
        }

    def test_invalid_request_has_no_result(self, aws):
        from src.links_v3_status import lambda_handler

        aws["links_table"].put_item(Item={"requestId": "8k", "status": "invalid"})

        response = lambda_handler(_event("8k"), None)

        assert json.loads(response["body"]) == {"requestId": "8k", "status": "invalid"}

    def test_failed_request_includes_attempts_and_last_error(self, aws):
        from src.links_v3_status import lambda_handler

        aws["links_table"].put_item(
            Item={
                "requestId": "8k",
                "status": "failed",
                "attempts": 4,
                "lastError": "boom",
            }
        )

        response = lambda_handler(_event("8k"), None)

        body = json.loads(response["body"])
        assert body["status"] == "failed"
        assert body["attempts"] == 4
        assert body["lastError"] == "boom"

    def test_unknown_request_id_returns_404(self, aws):
        from src.links_v3_status import lambda_handler

        response = lambda_handler(_event("doesnotexist"), None)

        assert response["statusCode"] == 404
