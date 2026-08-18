import json

import boto3
import pytest
from moto import mock_aws


def _event(body):
    return {"body": json.dumps(body) if not isinstance(body, str) else body}


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
        counter_table = dynamodb.create_table(
            TableName="links-counter",
            KeySchema=[{"AttributeName": "counterId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "counterId", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        sqs = boto3.client("sqs", region_name=region)
        queue_url = sqs.create_queue(QueueName="links-queue")["QueueUrl"]

        monkeypatch.setenv("LINKS_TABLE_NAME", "links")
        monkeypatch.setenv("LINKS_COUNTER_TABLE_NAME", "links-counter")
        monkeypatch.setenv("LINKS_QUEUE_URL", queue_url)

        import src.links_submit as links_submit

        links_submit._dynamodb = dynamodb
        links_submit._sqs = sqs

        yield {
            "links_table": links_table,
            "sqs": sqs,
            "queue_url": queue_url,
        }


class TestLambdaHandler:
    def test_valid_submission_is_accepted(self, aws):
        from src.links_submit import lambda_handler

        response = lambda_handler(_event({"number": "11987654321"}), None)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["status"] == "pending"
        assert "requestId" in body

    def test_first_ever_id_is_8k(self, aws):
        from src.links_submit import lambda_handler

        response = lambda_handler(_event({"number": "11987654321"}), None)

        assert json.loads(response["body"])["requestId"] == "8k"

    def test_sequential_requests_get_distinct_ids(self, aws):
        from src.links_submit import lambda_handler

        first = json.loads(
            lambda_handler(_event({"number": "11987654321"}), None)["body"]
        )
        second = json.loads(
            lambda_handler(_event({"number": "11912345678"}), None)["body"]
        )

        assert first["requestId"] != second["requestId"]

    def test_submission_writes_pending_record(self, aws):
        from src.links_submit import lambda_handler

        response = lambda_handler(_event({"number": "11987654321"}), None)
        request_id = json.loads(response["body"])["requestId"]

        item = aws["links_table"].get_item(Key={"requestId": request_id})["Item"]
        assert item["status"] == "pending"
        assert item["number"] == "11987654321"

    def test_submission_enqueues_a_message(self, aws):
        from src.links_submit import lambda_handler

        lambda_handler(_event({"number": "11987654321"}), None)

        messages = aws["sqs"].receive_message(QueueUrl=aws["queue_url"])
        assert len(messages.get("Messages", [])) == 1

    def test_missing_number_is_rejected(self, aws):
        from src.links_submit import lambda_handler

        response = lambda_handler(_event({}), None)

        assert response["statusCode"] == 400
        assert aws["links_table"].scan()["Count"] == 0

    def test_non_string_number_is_rejected(self, aws):
        from src.links_submit import lambda_handler

        response = lambda_handler(_event({"number": 123}), None)

        assert response["statusCode"] == 400

    def test_malformed_json_body_is_rejected(self, aws):
        from src.links_submit import lambda_handler

        response = lambda_handler(_event("not json"), None)

        assert response["statusCode"] == 400
