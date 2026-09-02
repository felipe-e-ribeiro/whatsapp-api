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
    def test_pending_request(self, aws):
        from src.links_status import lambda_handler

        aws["links_table"].put_item(
            Item={"requestId": "8k", "number": "11987654321", "status": "pending"}
        )

        response = lambda_handler(_event("8k"), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body == {"requestId": "8k", "status": "pending"}

    def test_completed_request(self, aws):
        from src.links_status import lambda_handler

        aws["links_table"].put_item(
            Item={
                "requestId": "8k",
                "number": "11987654321",
                "status": "completed",
                "result": "https://wa.me/5511987654321",
            }
        )

        response = lambda_handler(_event("8k"), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body == {
            "requestId": "8k",
            "status": "completed",
            "result": "https://wa.me/5511987654321",
        }

    def test_unknown_request_id_returns_404(self, aws):
        from src.links_status import lambda_handler

        response = lambda_handler(_event("doesnotexist"), None)

        assert response["statusCode"] == 404
