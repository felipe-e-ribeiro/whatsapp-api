import boto3
import pytest
from moto import mock_aws


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
        table.put_item(Item={"requestId": "8k", "number": "11987654321", "status": "pending"})

        monkeypatch.setenv("LINKS_V3_TABLE_NAME", "links-v3")

        import src.links_store as links_store

        links_store._dynamodb = dynamodb

        yield {"table": table}


class TestLambdaHandler:
    def test_persists_completed_result(self, aws):
        from src.links_v3_persist import lambda_handler

        lambda_handler(
            {"requestId": "8k", "status": "completed", "result": "https://wa.me/5511987654321"},
            None,
        )

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "completed"
        assert item["result"] == "https://wa.me/5511987654321"
        assert "completedAt" in item

    def test_sets_updated_at(self, aws):
        from src.links_v3_persist import lambda_handler

        lambda_handler(
            {"requestId": "8k", "status": "completed", "result": "https://wa.me/5511987654321"},
            None,
        )

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert "updatedAt" in item

    def test_persists_invalid_status_without_result(self, aws):
        from src.links_v3_persist import lambda_handler

        lambda_handler({"requestId": "8k", "status": "invalid"}, None)

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "invalid"
        assert "result" not in item

    def test_a_stale_last_error_is_cleared_on_success(self, aws):
        """A request that failed, got reprocessed, and now succeeds
        shouldn't keep showing the error from its earlier failed run.
        """
        from src.links_v3_persist import lambda_handler

        aws["table"].update_item(
            Key={"requestId": "8k"},
            UpdateExpression="SET lastError = :e",
            ExpressionAttributeValues={":e": "boom from a previous attempt"},
        )

        lambda_handler(
            {"requestId": "8k", "status": "completed", "result": "https://wa.me/5511987654321"},
            None,
        )

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert "lastError" not in item
