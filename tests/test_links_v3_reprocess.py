import json

import boto3
import pytest
from moto import mock_aws


def _event(request_id):
    return {"pathParameters": {"requestId": request_id}}


_MINIMAL_DEFINITION = json.dumps(
    {"StartAt": "Noop", "States": {"Noop": {"Type": "Pass", "End": True}}}
)


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

        sfn = boto3.client("stepfunctions", region_name=region)
        state_machine_arn = sfn.create_state_machine(
            name="links-v3-pipeline",
            definition=_MINIMAL_DEFINITION,
            roleArn="arn:aws:iam::123456789012:role/dummy-role",
        )["stateMachineArn"]

        monkeypatch.setenv("LINKS_V3_TABLE_NAME", "links-v3")
        monkeypatch.setenv("LINKS_V3_STATE_MACHINE_ARN", state_machine_arn)

        import src.links_store as links_store
        import src.links_v3_reprocess as links_v3_reprocess

        links_store._dynamodb = dynamodb
        links_v3_reprocess._sfn = sfn

        yield {
            "links_table": links_table,
            "sfn": sfn,
            "state_machine_arn": state_machine_arn,
        }


class TestLambdaHandler:
    def test_reprocessing_a_failed_request_flips_it_back_to_pending(self, aws):
        from src.links_v3_reprocess import lambda_handler

        aws["links_table"].put_item(
            Item={
                "requestId": "8k",
                "number": "11987654321",
                "status": "failed",
                "lastError": "boom",
                "attempts": 4,
            }
        )

        response = lambda_handler(_event("8k"), None)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body == {"requestId": "8k", "status": "pending", "reprocessCount": 1}

        item = aws["links_table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "pending"
        assert "lastError" not in item
        assert int(item["reprocessCount"]) == 1

    def test_reprocessing_starts_a_new_execution(self, aws):
        from src.links_v3_reprocess import lambda_handler

        aws["links_table"].put_item(
            Item={"requestId": "8k", "number": "11987654321", "status": "failed"}
        )

        lambda_handler(_event("8k"), None)

        executions = aws["sfn"].list_executions(
            stateMachineArn=aws["state_machine_arn"]
        )["executions"]
        assert len(executions) == 1
        assert executions[0]["name"] == "8k-r1"

    def test_reprocessing_twice_increments_the_counter_and_execution_name(self, aws):
        from src.links_v3_reprocess import lambda_handler

        aws["links_table"].put_item(
            Item={"requestId": "8k", "number": "11987654321", "status": "failed"}
        )

        lambda_handler(_event("8k"), None)
        # Simulate the pipeline failing again before the second reprocess.
        aws["links_table"].update_item(
            Key={"requestId": "8k"},
            UpdateExpression="SET #s = :failed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":failed": "failed"},
        )

        response = lambda_handler(_event("8k"), None)

        assert json.loads(response["body"])["reprocessCount"] == 2
        executions = aws["sfn"].list_executions(
            stateMachineArn=aws["state_machine_arn"]
        )["executions"]
        names = {execution["name"] for execution in executions}
        assert names == {"8k-r1", "8k-r2"}

    def test_unknown_request_id_returns_404(self, aws):
        from src.links_v3_reprocess import lambda_handler

        response = lambda_handler(_event("doesnotexist"), None)

        assert response["statusCode"] == 404

    def test_non_failed_request_is_rejected(self, aws):
        from src.links_v3_reprocess import lambda_handler

        aws["links_table"].put_item(
            Item={"requestId": "8k", "number": "11987654321", "status": "completed"}
        )

        response = lambda_handler(_event("8k"), None)

        assert response["statusCode"] == 409
        executions = aws["sfn"].list_executions(
            stateMachineArn=aws["state_machine_arn"]
        )["executions"]
        assert len(executions) == 0
