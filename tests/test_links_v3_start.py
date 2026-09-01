import json

import boto3
import pytest
from moto import mock_aws


def _event(body, headers=None):
    event = {"body": json.dumps(body) if not isinstance(body, str) else body}
    if headers:
        event["headers"] = headers
    return event


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
        import src.links_v3_start as links_v3_start

        links_store._dynamodb = dynamodb
        links_v3_start._sfn = sfn

        yield {
            "links_table": links_table,
            "sfn": sfn,
            "state_machine_arn": state_machine_arn,
        }


class TestLambdaHandler:
    def test_valid_submission_is_accepted(self, aws):
        from src.links_v3_start import lambda_handler

        response = lambda_handler(_event({"number": "11987654321"}), None)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["status"] == "pending"
        assert "requestId" in body

    def test_submission_writes_pending_record(self, aws):
        from src.links_v3_start import lambda_handler

        response = lambda_handler(_event({"number": "11987654321"}), None)
        request_id = json.loads(response["body"])["requestId"]

        item = aws["links_table"].get_item(Key={"requestId": request_id})["Item"]
        assert item["status"] == "pending"
        assert item["number"] == "11987654321"

    def test_submission_starts_an_execution(self, aws):
        from src.links_v3_start import lambda_handler

        lambda_handler(_event({"number": "11987654321"}), None)

        executions = aws["sfn"].list_executions(
            stateMachineArn=aws["state_machine_arn"]
        )["executions"]
        assert len(executions) == 1

    def test_client_supplied_idempotency_key_is_used_as_request_id(self, aws):
        from src.links_v3_start import lambda_handler

        response = lambda_handler(
            _event({"number": "11987654321"}, {"idempotency-key": "client-key-1"}),
            None,
        )

        assert json.loads(response["body"])["requestId"] == "client-key-1"

    def test_missing_number_is_rejected(self, aws):
        from src.links_v3_start import lambda_handler

        response = lambda_handler(_event({}), None)

        assert response["statusCode"] == 400
        assert aws["links_table"].scan()["Count"] == 0

    def test_non_string_number_is_rejected(self, aws):
        from src.links_v3_start import lambda_handler

        response = lambda_handler(_event({"number": 123}), None)

        assert response["statusCode"] == 400

    def test_malformed_json_body_is_rejected(self, aws):
        from src.links_v3_start import lambda_handler

        response = lambda_handler(_event("not json"), None)

        assert response["statusCode"] == 400

    def test_simulate_failures_is_passed_through_to_execution_input(self, aws):
        from src.links_v3_start import lambda_handler

        lambda_handler(
            _event({"number": "11987654321", "simulateFailures": 2}), None
        )

        executions = aws["sfn"].list_executions(
            stateMachineArn=aws["state_machine_arn"]
        )["executions"]
        execution = aws["sfn"].describe_execution(
            executionArn=executions[0]["executionArn"]
        )
        assert json.loads(execution["input"])["simulateFailures"] == 2


class TestIdempotentResubmission:
    def test_execution_already_exists_is_treated_as_success(self, aws, monkeypatch):
        from botocore.exceptions import ClientError

        import src.links_v3_start as links_v3_start

        real_start_execution = aws["sfn"].start_execution
        call_count = {"n": 0}

        def fake_start_execution(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return real_start_execution(**kwargs)
            raise ClientError(
                {
                    "Error": {
                        "Code": "ExecutionAlreadyExists",
                        "Message": "Execution already exists",
                    }
                },
                "StartExecution",
            )

        monkeypatch.setattr(links_v3_start._sfn, "start_execution", fake_start_execution)

        headers = {"idempotency-key": "client-key-1"}
        first = links_v3_start.lambda_handler(
            _event({"number": "11987654321"}, headers), None
        )
        second = links_v3_start.lambda_handler(
            _event({"number": "11987654321"}, headers), None
        )

        assert first["statusCode"] == 202
        assert second["statusCode"] == 202
        assert (
            json.loads(first["body"])["requestId"]
            == json.loads(second["body"])["requestId"]
            == "client-key-1"
        )
