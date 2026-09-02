import boto3
import pytest
from moto import mock_aws


def _event(request_id, number, digits, simulate_failures=None):
    event = {
        "requestId": request_id,
        "number": number,
        "validation": {"Payload": {"valid": True, "digits": digits}},
    }
    if simulate_failures is not None:
        event["simulateFailures"] = simulate_failures
    return event


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

        monkeypatch.setenv("LINKS_V3_TABLE_NAME", "links-v3")

        import src.links_store as links_store

        links_store._dynamodb = dynamodb

        yield {"table": table}


class TestLambdaHandler:
    def test_succeeds_on_first_attempt(self, aws):
        from src.links_v3_resolve import lambda_handler

        result = lambda_handler(_event("8k", "11987654321", "11987654321"), None)

        assert result == {"result": "https://wa.me/5511987654321"}
        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert int(item["attempts"]) == 1
        assert "updatedAt" in item

    def test_simulated_failures_are_retried_then_succeed(self, aws):
        from src.links_v3_resolve import TransientResolutionError, lambda_handler

        event = _event("8k", "11987654321", "11987654321", simulate_failures=2)

        with pytest.raises(TransientResolutionError):
            lambda_handler(event, None)
        with pytest.raises(TransientResolutionError):
            lambda_handler(event, None)

        result = lambda_handler(event, None)

        assert result == {"result": "https://wa.me/5511987654321"}
        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert int(item["attempts"]) == 3

    def test_simulated_failure_records_last_error(self, aws):
        from src.links_v3_resolve import TransientResolutionError, lambda_handler

        event = _event("8k", "11987654321", "11987654321", simulate_failures=1)

        with pytest.raises(TransientResolutionError):
            lambda_handler(event, None)

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert "lastError" in item
